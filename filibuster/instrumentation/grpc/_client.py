# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint:disable=relative-beyond-top-level
# pylint:disable=arguments-differ
# pylint:disable=no-member
# pylint:disable=signature-differs

"""Implementation of the invocation-side open-telemetry interceptor."""
import hashlib
import json
import os
import re
import sys
from collections import OrderedDict
from threading import Lock
from typing import MutableMapping

import grpc
import requests
from grpc._channel import _RPCState
from grpc._cython import cygrpc

from opentelemetry import context
from opentelemetry import propagators, trace

from filibuster.datatypes import TestExecution
from filibuster.execution_index import execution_index_new, execution_index_fromstring, execution_index_push, \
    execution_index_tostring, execution_index_pop
from filibuster.instrumentation.grpc import grpcext
from filibuster.instrumentation.grpc._utilities import RpcInfo
from opentelemetry.trace.status import Status, StatusCode

# Start Filibuster configuration

# A key to a context variable to avoid creating duplicate spans when instrumenting
# both, Session.request and Session.send, since Session.request calls into Session.send
from filibuster.logger import notice, warning, debug
from filibuster.instrumentation.helpers import get_full_traceback_hash
from filibuster.vclock import vclock_new, vclock_merge, vclock_fromstring, vclock_increment, vclock_tostring
from filibuster.global_context import get_value as _filibuster_global_context_get_value
from filibuster.global_context import set_value as _filibuster_global_context_set_value
from filibuster.server_helpers import should_fail_request_with, load_counterexample
from filibuster.instrumentation.helpers import get_full_traceback_hash


_FILIBUSTER_SUPPRESS_REQUESTS_INSTRUMENTATION_KEY = "filibuster_suppress_requests_instrumentation"

# We do not want to instrument the instrumentation, so use this key to detect when we
# are inside of a Filibuster instrumentation call to suppress further instrumentation.
_FILIBUSTER_INSTRUMENTATION_KEY = "filibuster_instrumentation"

# Key for the Filibuster vclock in the context.
_FILIBUSTER_VCLOCK_KEY = "filibuster_vclock"

# Key for the Filibuster origin vclock in the context.
_FILIBUSTER_ORIGIN_VCLOCK_KEY = "filibuster_origin_vclock"

# Key for the Filibuster execution index in the context.
_FILIBUSTER_EXECUTION_INDEX_KEY = "filibuster_execution_index"

# Key for the Filibuster request id in the context.
_FILIBUSTER_REQUEST_ID_KEY = "filibuster_request_id"

# We're making an assumption here that test files start with test_ (Pytest)
TEST_PREFIX = "test_"

# We're making an assumption here that test files start with test_ (Pytest)
INSTRUMENTATION_PREFIX = "filibuster/instrumentation"

# Key for Filibuster vclock mapping.
_FILIBUSTER_VCLOCK_BY_REQUEST_KEY = "filibuster_vclock_by_request"
_filibuster_global_context_set_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY, {})

# Mutex for vclock and execution_index.
ei_and_vclock_mutex = Lock()

# Last used execution index.
# (this is mutated under the same mutex as the vclock.)
_FILIBUSTER_EI_BY_REQUEST_KEY = "filibuster_execution_indices_by_request"
_filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, {})

# Service name, set from global context during instrumentor instantiation.
service_name = None

# Filibuster URL, set from global context during instrumentor instantiation.
filibuster_url = None

# Mutex for vclock and execution_index.
ei_and_vclock_mutex = Lock()

# End Filibuster configuration

class _GuardedSpan:
    def __init__(self, span):
        self.span = span
        self.generated_span = None
        self._engaged = True

    def __enter__(self):
        self.generated_span = self.span.__enter__()
        return self

    def __exit__(self, *args, **kwargs):
        if self._engaged:
            self.generated_span = None
            return self.span.__exit__(*args, **kwargs)
        return False

    def release(self):
        self._engaged = False
        return self.span

## *******************************************************************************************
## START FILIBUSTER HELPERS
## *******************************************************************************************

from os.path import exists

COUNTEREXAMPLE_FILE = "/tmp/filibuster/counterexample.json"
if exists(COUNTEREXAMPLE_FILE):
    notice("Counterexample file present!")
    counterexample = load_counterexample(COUNTEREXAMPLE_FILE)
    counterexample_test_execution = TestExecution.from_json(counterexample['TestExecution']) if counterexample else None
    print(counterexample_test_execution.failures)
else:
    counterexample = None

# For a given request, return a unique hash that can be used to identify it.
def unique_request_hash(args):
    hash_string = "-".join(args)
    hex_digest = hashlib.md5(hash_string.encode()).hexdigest()
    return hex_digest

## *******************************************************************************************
## END FILIBUSTER HELPERS
## *******************************************************************************************

## *******************************************************************************************
## START FILIBUSTER ENDPOINTS
## *******************************************************************************************

def filibuster_update_url(url):
    return "{}/{}/update".format(url, 'filibuster')

def filibuster_create_url(url):
    return "{}/{}/create".format(url, 'filibuster')

def filibuster_new_test_execution_url(url, service):
    return "{}/{}/new-test-execution/{}".format(url, 'filibuster', service)

## *******************************************************************************************
## END FILIBUSTER ENDPOINTS
## *******************************************************************************************

def _inject_span_context(metadata: MutableMapping[str, str]) -> None:
    # pylint:disable=unused-argument
    def append_metadata(
        carrier: MutableMapping[str, str], key: str, value: str
    ):
        metadata[key] = value

    # Inject current active span from the context
    propagators.inject(append_metadata, metadata)


def _make_future_done_callback(span, rpc_info):
    def callback(response_future):
        with span:
            code = response_future.code()
            if code != grpc.StatusCode.OK:
                rpc_info.error = code
                return
            response = response_future.result()
            rpc_info.response = response

    return callback


class OpenTelemetryClientInterceptor(
    grpcext.UnaryClientInterceptor, grpcext.StreamClientInterceptor
):
    def __init__(self, tracer):
        self._tracer = tracer

        global service_name
        service_name = _filibuster_global_context_get_value("filibuster_service_name")

        global filibuster_url
        filibuster_url = _filibuster_global_context_get_value("filibuster_url")

    def _start_span(self, method):
        service, meth = method.lstrip("/").split("/", 1)
        attributes = {
            "rpc.system": "grpc",
            "rpc.grpc.status_code": grpc.StatusCode.OK.value[0],
            "rpc.method": meth,
            "rpc.service": service,
        }

        return self._tracer.start_as_current_span(
            name=method, kind=trace.SpanKind.CLIENT, attributes=attributes
        )

    # pylint:disable=no-self-use
    def _trace_result(self, guarded_span, rpc_info, result):
        # If the RPC is called asynchronously, release the guard and add a
        # callback so that the span can be finished once the future is done.
        if isinstance(result, grpc.Future):
            result.add_done_callback(
                _make_future_done_callback(guarded_span.release(), rpc_info)
            )
            return result
        response = result
        # Handle the case when the RPC is initiated via the with_call
        # method and the result is a tuple with the first element as the
        # response.
        # http://www.grpc.io/grpc/python/grpc.html#grpc.UnaryUnaryMultiCallable.with_call
        if isinstance(result, tuple):
            response = result[0]
        rpc_info.response = response

        return result

    def _start_guarded_span(self, *args, **kwargs):
        return _GuardedSpan(self._start_span(*args, **kwargs))

    def intercept_unary(self, request, metadata, client_info, invoker):
        notice("Interceptor invoked!")

        global ei_and_vclock_mutex
        ei_and_vclock_mutex.acquire()

        ## *******************************************************************************************
        ## START CALLSITE INFORMATION
        ## *******************************************************************************************

        callsite_file, callsite_line, full_traceback_hash = get_full_traceback_hash(service_name)
        notice("=> full_traceback_hash: " + full_traceback_hash)

        ## *******************************************************************************************
        ## END CALLSITE INFORMATION
        ## *******************************************************************************************

        ## *******************************************************************************************
        ## START CLOCK RESET
        ## *******************************************************************************************

        # Get the request id.
        request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
        notice("request_id_string: " + str(request_id_string))

        # Figure out if this is the first request in a new test execution.
        debug("Setting Filibuster instrumentation key...")
        token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))
        response = None
        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
            response = requests.get(filibuster_new_test_execution_url(filibuster_url, service_name))
            if response is not None:
                response = response.json()
                notice("clock reset response: " + str(response))
        debug("Removing instrumentation key for Filibuster.")
        context.detach(token)

        # Reset EI and vclock if this is a new test execution.
        if response and ('new-test-execution' in response) and (response['new-test-execution']):
            vclocks_by_request = {request_id_string: vclock_new()}
            _filibuster_global_context_set_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY, vclocks_by_request)

            execution_indices_by_request = {request_id_string: execution_index_new()}
            _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

        ## *******************************************************************************************
        ## END CLOCK RESET
        ## *******************************************************************************************

        ## *******************************************************************************************
        ## START INCOMING AND LOCAL CLOCK WORK
        ## *******************************************************************************************

        # Incoming clock from the request that triggered this service to be reached.
        incoming_vclock_string = context.get_value(_FILIBUSTER_VCLOCK_KEY)

        # If it's not none, we probably need to merge with our clock, first, since our clock is keeping
        # track of *our* requests from this node.
        if incoming_vclock_string is not None:
            incoming_vclock = vclock_fromstring(incoming_vclock_string)
            vclocks_by_request = _filibuster_global_context_get_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY)
            local_vclock = vclocks_by_request.get(request_id_string, vclock_new())
            new_local_vclock = vclock_merge(incoming_vclock, local_vclock)
            vclocks_by_request[request_id_string] = new_local_vclock
            _filibuster_global_context_set_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY, vclocks_by_request)

        # Finally, advance the clock to account for this request.
        vclocks_by_request = _filibuster_global_context_get_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY)
        local_vclock = vclocks_by_request.get(request_id_string, vclock_new())
        new_local_vclock = vclock_increment(local_vclock, service_name)
        vclocks_by_request[request_id_string] = new_local_vclock
        _filibuster_global_context_set_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY, vclocks_by_request)
        vclock = vclocks_by_request.get(request_id_string, vclock_new())

        notice("clock now: " + str(vclocks_by_request.get(request_id_string, vclock_new())))

        ## *******************************************************************************************
        ## END INCOMING AND LOCAL CLOCK WORK
        ## *******************************************************************************************

        ## *******************************************************************************************
        ## START EXECUTION INDEX WORK
        ## *******************************************************************************************

        # Get incoming execution index.
        incoming_execution_index_string = context.get_value(_FILIBUSTER_EXECUTION_INDEX_KEY)

        if incoming_execution_index_string is not None:
            incoming_execution_index = execution_index_fromstring(incoming_execution_index_string)
        else:
            execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
            incoming_execution_index = execution_indices_by_request.get(request_id_string, execution_index_new())

        execution_index_hash = unique_request_hash([full_traceback_hash])

        # Advance execution index.
        execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
        execution_indices_by_request[request_id_string] = execution_index_push(execution_index_hash, incoming_execution_index)
        _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)
        execution_index = execution_index_tostring(execution_indices_by_request[request_id_string])

        notice("execution index now: " + str(execution_index_tostring(execution_indices_by_request[request_id_string])))

        ## *******************************************************************************************
        ## END EXECUTION INDEX WORK
        ## *******************************************************************************************

        ## *******************************************************************************************
        ## START ORIGIN CLOCK WORK
        ## *******************************************************************************************

        # Get the incoming origin vclock from the context.
        incoming_origin_vclock_string = context.get_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY)

        # Either use the incoming clock as origin or set to an empty clock.
        if incoming_origin_vclock_string is not None:
            origin_vclock = vclock_fromstring(incoming_origin_vclock_string)
        else:
            origin_vclock = vclock_new()

        notice("origin_clock: " + str(origin_vclock))

        ## *******************************************************************************************
        ## END ORIGIN CLOCK WORK
        ## *******************************************************************************************

        ei_and_vclock_mutex.release()

        ## *******************************************************************************************
        ## START RECORD CALL WORK
        ## *******************************************************************************************

        notice("---")
        notice("full_method: " + str(client_info.full_method))
        notice("timeout: " + str(client_info.timeout))
        notice("metadata: " + str(metadata))
        notice("request: " + str(request))
        notice("---")

        response = None
        parsed_content = None
        generated_id = None
        should_sleep_interval = 0
        exception = None
        should_abort = True
        exception_code = None

        try:
            debug("Setting Filibuster instrumentation key...")
            token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

            payload = {
                'instrumentation_type': 'invocation',
                'source_service_name': service_name,
                'module': 'grpc',
                'method': 'insecure_channel',
                'args': [str(client_info.full_method), str(request)],
                'kwargs': {},
                'callsite_file': callsite_file,
                'callsite_line': callsite_line,
                'full_traceback': full_traceback_hash,
                'metadata': {},
                'vclock': vclock,
                'origin_vclock': origin_vclock,
                'execution_index': execution_index
            }

            if client_info.timeout is not None:
                payload['metadata']['timeout'] = client_info.timeout

            if counterexample is not None and counterexample_test_execution is not None:
                notice("Using counterexample without contacting server.")
                response = should_fail_request_with(payload, counterexample_test_execution.failures)
                if response is None:
                    response = {'execution_index': execution_index}
                print(response)
            elif os.environ.get('DISABLE_SERVER_COMMUNICATION', ''):
                warning("Server communication disabled.")
            else:
                warning("Issuing request")
                response = requests.put(filibuster_create_url(filibuster_url), json=payload)
        except Exception as e:
            warning("Exception raised (invocation)!")
            print(e, file=sys.stderr)
            return None
        finally:
            debug("Removing instrumentation key for Filibuster.")
            context.detach(token)

        if response is not None:
            try:
                if isinstance(response, dict):
                    parsed_content = response
                else:
                    parsed_content = response.json()

                if 'generated_id' in parsed_content:
                    generated_id = parsed_content['generated_id']

                if 'forced_exception' in parsed_content:
                    exception = parsed_content['forced_exception']['name']

                    if 'metadata' in parsed_content['forced_exception'] and parsed_content['forced_exception']['metadata'] is not None:
                        exception_metadata = parsed_content['forced_exception']['metadata']
                        if 'abort' in exception_metadata and exception_metadata['abort'] is not None:
                            should_abort = exception_metadata['abort']
                        if 'sleep' in exception_metadata and exception_metadata['sleep'] is not None:
                            should_sleep_interval = exception_metadata['sleep']
                        if 'code' in exception_metadata and exception_metadata['code'] is not None:
                            exception_code = exception_metadata['code']

                if 'failure_metadata' in parsed_content:
                    if 'exception' in parsed_content['failure_metadata']:
                        if 'metadata' in parsed_content['failure_metadata']['exception']:
                            exception = "grpc._channel._InactiveRpcError"
                            exception_metadata = parsed_content['failure_metadata']['exception']['metadata']

                            if 'code' in exception_metadata and exception_metadata['code'] is not None:
                                exception_code = exception_metadata['code']

            except Exception as e:
                warning("Exception raised (invocation get_json)!")
                print(e, file=sys.stderr)
                return None

        ## -------------------------------------------------------------
        ## Start generate exception instance from exception description.
        ## -------------------------------------------------------------

        _UNARY_UNARY_INITIAL_DUE = (
            cygrpc.OperationType.send_initial_metadata,
            cygrpc.OperationType.send_message,
            cygrpc.OperationType.send_close_from_client,
            cygrpc.OperationType.receive_initial_metadata,
            cygrpc.OperationType.receive_message,
            cygrpc.OperationType.receive_status_on_client,
        )

        if exception and exception_code:
            exception_class = eval(exception)
            exception = exception_class(_RPCState(_UNARY_UNARY_INITIAL_DUE, None, None, None, None))
            exception_code = eval("grpc.StatusCode." + exception_code)
            exception._state.code = exception_code

        ## -------------------------------------------------------------
        ## End generate exception instance from exception description.
        ## -------------------------------------------------------------

        notice("parsed_content: " + str(json.dumps(parsed_content, indent=2)))
        notice("generated_id: " + str(generated_id))
        notice("exception: " + str(exception))
        notice("exception_code: " + str(exception_code))
        notice("should_sleep_interval: " + str(should_sleep_interval))
        notice("should_abort: " + str(should_abort))

        ## *******************************************************************************************
        ## END RECORD CALL WORK
        ## *******************************************************************************************

        ## *******************************************************************************************
        ## START METADATA WORK
        ## *******************************************************************************************

        notice("metadata before: " + str(metadata))

        if not metadata:
            metadata = []
        metadata.append(('x-filibuster-generated-id', str(generated_id)))
        metadata.append(('x-filibuster-vclock', vclock_tostring(vclock)))
        metadata.append(('x-filibuster-origin-vclock', vclock_tostring(origin_vclock)))
        metadata.append(('x-filibuster-execution-index', execution_index))
        metadata.append(('x-filibuster-request-id', request_id_string))
        metadata.append(('x-filibuster-forced-sleep', str(should_sleep_interval)))

        notice("metadata after: " + str(metadata))

        ## *******************************************************************************************
        ## END METADATA WORK
        ## *******************************************************************************************

        if not metadata:
            mutable_metadata = OrderedDict()
        else:
            mutable_metadata = OrderedDict(metadata)

        print(mutable_metadata)

        with self._start_guarded_span(client_info.full_method) as guarded_span:
            _inject_span_context(mutable_metadata)
            metadata = tuple(mutable_metadata.items())

            rpc_info = RpcInfo(
                full_method=client_info.full_method,
                metadata=metadata,
                timeout=client_info.timeout,
                request=request,
            )

            if exception and exception_code:
                notice("Raising exception!")
                print(exception)

                ## *******************************************************************************************
                ## START RECORD EXCEPTIONAL RESPONSE
                ## *******************************************************************************************

                # Remove request from the execution index.
                execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
                request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
                execution_indices_by_request[request_id_string] = execution_index_pop(execution_indices_by_request.get(request_id_string, execution_index_new()))
                _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

                # Notify the Filibuster server that the call succeeded.
                if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
                    try:
                        debug("Setting Filibuster instrumentation key...")
                        token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                        payload = {
                            'instrumentation_type': 'invocation_complete',
                            'generated_id': generated_id,
                            'execution_index': execution_index,
                            'vclock': vclock,
                            'exception': {
                                'name': "grpc._channel._InactiveRpcError",
                                'metadata': {
                                    'code': str(exception_code)
                                }
                            }
                        }

                        if should_sleep_interval > 0:
                            payload['exception']['metadata']['sleep'] = should_sleep_interval

                        if should_abort is not True:
                            payload['exception']['metadata']['abort'] = should_abort

                        requests.post(filibuster_update_url(filibuster_url), json=payload)
                    except Exception as e:
                        warning("Exception raised recording exceptional response!")
                        print(e, file=sys.stderr)
                    finally:
                        debug("Removing instrumentation key for Filibuster.")
                        context.detach(token)

                ## *******************************************************************************************
                ## END RECORD EXCEPTIONAL RESPONSE
                ## *******************************************************************************************

                raise exception
            else:
                try:
                    result = invoker(request, metadata)

                    ## *******************************************************************************************
                    ## START RECORD SUCCESSFUL RESPONSE
                    ## *******************************************************************************************

                    # Remove request from the execution index.
                    execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
                    request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
                    execution_indices_by_request[request_id_string] = execution_index_pop(execution_indices_by_request.get(request_id_string, execution_index_new()))
                    _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

                    # Notify the Filibuster server that the call succeeded.
                    if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
                        try:
                            debug("Setting Filibuster instrumentation key...")
                            token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                            return_value = {
                                '__class__': str(result.__class__.__name__)
                            }
                            payload = {
                                'instrumentation_type': 'invocation_complete',
                                'generated_id': generated_id,
                                'execution_index': execution_index,
                                'vclock': vclock,
                                'return_value': return_value
                            }
                            requests.post(filibuster_update_url(filibuster_url), json=payload)
                        except Exception as e:
                            warning("Exception raised recording successful response!")
                            print(e, file=sys.stderr)
                        finally:
                            debug("Removing instrumentation key for Filibuster.")
                            context.detach(token)

                    ## *******************************************************************************************
                    ## END RECORD SUCCESSFUL RESPONSE
                    ## *******************************************************************************************

                except grpc.RpcError as err:

                    ## *******************************************************************************************
                    ## START RECORD EXCEPTIONAL RESPONSE
                    ## *******************************************************************************************

                    # Remove request from the execution index.
                    execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
                    request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
                    execution_indices_by_request[request_id_string] = execution_index_pop(execution_indices_by_request.get(request_id_string, execution_index_new()))
                    _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

                    # Notify the Filibuster server that the call succeeded.
                    if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
                        try:
                            debug("Setting Filibuster instrumentation key...")
                            token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                            payload = {
                                'instrumentation_type': 'invocation_complete',
                                'generated_id': generated_id,
                                'execution_index': execution_index,
                                'vclock': vclock,
                                'exception': {
                                    'name': "grpc._channel._InactiveRpcError",
                                    'metadata': {
                                        'code': str(err.code()).replace("StatusCode.", "")
                                    }
                                }
                            }

                            if should_sleep_interval > 0:
                                payload['exception']['metadata']['sleep'] = should_sleep_interval

                            if should_abort is not True:
                                payload['exception']['metadata']['abort'] = should_abort

                            requests.post(filibuster_update_url(filibuster_url), json=payload)
                        except Exception as e:
                            warning("Exception raised recording exceptional response!")
                            print(e, file=sys.stderr)
                        finally:
                            debug("Removing instrumentation key for Filibuster.")
                            context.detach(token)

                    ## *******************************************************************************************
                    ## END RECORD EXCEPTIONAL RESPONSE
                    ## *******************************************************************************************

                    guarded_span.generated_span.set_status(
                        Status(StatusCode.ERROR)
                    )
                    guarded_span.generated_span.set_attribute(
                        "rpc.grpc.status_code", err.code().value[0]
                    )

                    raise err

            return self._trace_result(guarded_span, rpc_info, result)

    # For RPCs that stream responses, the result can be a generator. To record
    # the span across the generated responses and detect any errors, we wrap
    # the result in a new generator that yields the response values.
    def _intercept_server_stream(
        self, request_or_iterator, metadata, client_info, invoker
    ):
        if not metadata:
            mutable_metadata = OrderedDict()
        else:
            mutable_metadata = OrderedDict(metadata)

        with self._start_span(client_info.full_method) as span:
            _inject_span_context(mutable_metadata)
            metadata = tuple(mutable_metadata.items())
            rpc_info = RpcInfo(
                full_method=client_info.full_method,
                metadata=metadata,
                timeout=client_info.timeout,
            )

            if client_info.is_client_stream:
                rpc_info.request = request_or_iterator

            try:
                result = invoker(request_or_iterator, metadata)

                for response in result:
                    yield response
            except grpc.RpcError as err:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("rpc.grpc.status_code", err.code().value[0])
                raise err

    def intercept_stream(
        self, request_or_iterator, metadata, client_info, invoker
    ):
        if client_info.is_server_stream:
            return self._intercept_server_stream(
                request_or_iterator, metadata, client_info, invoker
            )

        if not metadata:
            mutable_metadata = OrderedDict()
        else:
            mutable_metadata = OrderedDict(metadata)

        with self._start_guarded_span(client_info.full_method) as guarded_span:
            _inject_span_context(mutable_metadata)
            metadata = tuple(mutable_metadata.items())
            rpc_info = RpcInfo(
                full_method=client_info.full_method,
                metadata=metadata,
                timeout=client_info.timeout,
                request=request_or_iterator,
            )

            rpc_info.request = request_or_iterator

            try:
                result = invoker(request_or_iterator, metadata)
            except grpc.RpcError as err:
                guarded_span.generated_span.set_status(
                    Status(StatusCode.ERROR)
                )
                guarded_span.generated_span.set_attribute(
                    "rpc.grpc.status_code", err.code().value[0],
                )
                raise err

            return self._trace_result(guarded_span, rpc_info, result)
