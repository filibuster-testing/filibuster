# Copyright The OpenTelemetry Authors
# Copyright Christopher Meiklejohn
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

import functools
import types
import json

import sys
import re
import hashlib
import uuid

import requests
import os

from requests.models import Response
from requests.sessions import Session
from requests.structures import CaseInsensitiveDict
from requests import exceptions

from threading import Lock

from filibuster.global_context import get_value as _filibuster_global_context_get_value
from filibuster.global_context import set_value as _filibuster_global_context_set_value
from filibuster.execution_index import execution_index_new, execution_index_fromstring, \
    execution_index_tostring, execution_index_push, execution_index_pop
from filibuster.instrumentation.helpers import get_full_traceback_hash, should_load_counterexample_file, \
    counterexample_file
from filibuster.logger import warning, debug, notice, info
from filibuster.vclock import vclock_new, vclock_tostring, vclock_fromstring, vclock_increment, vclock_merge
from filibuster.nginx_http_special_response import get_response
from filibuster.server_helpers import should_fail_request_with, load_counterexample
from filibuster.datatypes import TestExecution
from filibuster.instrumentation.helpers import get_full_traceback_hash

import importlib

from opentelemetry import context
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.requests.version import __version__
from opentelemetry.instrumentation.utils import http_status_to_status_code
from opentelemetry.trace import SpanKind, get_tracer
from opentelemetry.trace.status import Status

# A key to a context variable to avoid creating duplicate spans when instrumenting
# both, Session.request and Session.send, since Session.request calls into Session.send
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

# Key for Filibuster vclock mapping.
_FILIBUSTER_VCLOCK_BY_REQUEST_KEY = "filibuster_vclock_by_request"
_filibuster_global_context_set_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY, {})

# Mutex for vclock and execution_index.
ei_and_vclock_mutex = Lock()

# Last used execution index.
# (this is mutated under the same mutex as the vclock.)
_FILIBUSTER_EI_BY_REQUEST_KEY = "filibuster_execution_indices_by_request"
_filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, {})

if should_load_counterexample_file():
    notice("Counterexample file present!")
    counterexample = load_counterexample(counterexample_file())
    counterexample_test_execution = TestExecution.from_json(counterexample['TestExecution']) if counterexample else None
    print(counterexample_test_execution.failures)
else:
    counterexample = None


# pylint: disable=unused-argument
# pylint: disable=R0915
def _instrument(service_name=None, filibuster_url=None):
    """Enables tracing of all requests calls that go through
    :code:`requests.session.Session.request` (this includes
    :code:`requests.get`, etc.)."""

    # Since
    # https://github.com/psf/requests/commit/d72d1162142d1bf8b1b5711c664fbbd674f349d1
    # (v0.7.0, Oct 23, 2011), get, post, etc are implemented via request which
    # again, is implemented via Session.request (`Session` was named `session`
    # before v1.0.0, Dec 17, 2012, see
    # https://github.com/psf/requests/commit/4e5c4a6ab7bb0195dececdd19bb8505b872fe120)

    wrapped_request = Session.request
    wrapped_send = Session.send

    def filibuster_update_url(filibuster_url):
        return "{}/{}/update".format(filibuster_url, 'filibuster')

    def filibuster_create_url(filibuster_url):
        return "{}/{}/create".format(filibuster_url, 'filibuster')

    def filibuster_new_test_execution_url(filibuster_url, service_name):
        return "{}/{}/new-test-execution/{}".format(filibuster_url, 'filibuster', service_name)

    @functools.wraps(wrapped_request)
    def instrumented_request(self, method, url, *args, **kwargs):
        debug("instrumented_request entering; method: " + method + " url: " + url)

        def get_or_create_headers():
            headers = kwargs.get("headers")
            if headers is None:
                headers = {}
                kwargs["headers"] = headers

            return headers

        def call_wrapped(additional_headers):
            debug("instrumented_request.call_wrapped entering")

            # Merge headers: don't worry about collisions, we're only adding information.
            if 'headers' in kwargs and kwargs['headers'] is not None:
                headers = kwargs['headers']
                for key in additional_headers:
                    headers[key] = additional_headers[key]
                kwargs['headers'] = headers
            else:
                kwargs['headers'] = additional_headers

            response = wrapped_request(self, method, url, *args, **kwargs)
            debug("instrumented_request.call_wrapped exiting")
            return response

        response = _instrumented_requests_call(
            self, method, url, call_wrapped, get_or_create_headers, kwargs
        )

        debug("instrumented_request exiting; method: " + method + " url: " + url)
        return response

    @functools.wraps(wrapped_send)
    def instrumented_send(self, request, **kwargs):
        debug("instrumented_send entering; method: " + request.method + " url: " + request.url)

        def get_or_create_headers():
            request.headers = (
                request.headers
                if request.headers is not None
                else CaseInsensitiveDict()
            )
            return request.headers

        def call_wrapped(additional_headers):
            debug("instrumented_send.call_wrapped entering")
            response = wrapped_send(self, request, **kwargs)
            debug("instrumented_send.call_wrapped exiting")
            return response

        response = _instrumented_requests_call(
            self, request.method, request.url, call_wrapped, get_or_create_headers, kwargs
        )

        debug("instrumented_send exiting; method: " + request.method + " url: " + request.url)
        return response

    def _instrumented_requests_call(
            self, method: str, url: str, call_wrapped, get_or_create_headers, kwargs
    ):
        generated_id = None
        has_execution_index = False
        exception = None
        status_code = None
        should_inject_fault = False
        should_abort = True
        should_sleep_interval = 0

        debug("_instrumented_requests_call entering; method: " + method + " url: " + url)

        # Bail early if we are in nested instrumentation calls.

        if context.get_value("suppress_instrumentation") or context.get_value(
                _FILIBUSTER_SUPPRESS_REQUESTS_INSTRUMENTATION_KEY
        ):
            debug(
                "_instrumented_requests_call returning call_wrapped() because _FILIBUSTER_SUPPRESS_REQUESTS_INSTRUMENTATION_KEY set.")
            return call_wrapped({})

        vclock = None

        origin_vclock = None

        execution_index = None

        # Record that a call is being made to an external service.
        if not context.get_value(_FILIBUSTER_INSTRUMENTATION_KEY):
            if not context.get_value("suppress_instrumentation"):
                callsite_file, callsite_line, full_traceback_hash = get_full_traceback_hash(service_name)

                debug("")
                debug("Recording call using Filibuster instrumentation service. ********************")

                # VClock handling.

                # Figure out if we should reset the node's vector clock, which should happen in between test executions.
                debug("Setting Filibuster instrumentation key...")
                token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                response = None
                if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
                    response = wrapped_request(self, 'get',
                                               filibuster_new_test_execution_url(filibuster_url, service_name))
                    if response is not None:
                        response = response.json()

                debug("Removing instrumentation key for Filibuster.")
                context.detach(token)
                reset_local_vclock = False
                if response and ('new-test-execution' in response) and (response['new-test-execution']):
                    reset_local_vclock = True

                global ei_and_vclock_mutex
                ei_and_vclock_mutex.acquire()

                request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)

                if request_id_string is None:
                    request_id_string = str(uuid.uuid4())
                    context.attach(context.set_value(_FILIBUSTER_REQUEST_ID_KEY, request_id_string))

                if reset_local_vclock:
                    # Reset everything, since there is a new test execution.
                    debug("New test execution. Resetting vclocks_by_request and execution_indices_by_request.")

                    vclocks_by_request = {request_id_string: vclock_new()}
                    _filibuster_global_context_set_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY, vclocks_by_request)

                    execution_indices_by_request = {request_id_string: execution_index_new()}
                    _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

                # Incoming clock from the request that triggered this service to be reached.
                incoming_vclock_string = context.get_value(_FILIBUSTER_VCLOCK_KEY)

                # If it's not None, we probably need to merge with our clock, first, since our clock is keeping
                # track of *our* requests from this node.
                if incoming_vclock_string is not None:
                    vclocks_by_request = _filibuster_global_context_get_value(_FILIBUSTER_VCLOCK_BY_REQUEST_KEY)
                    incoming_vclock = vclock_fromstring(incoming_vclock_string)
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

                vclock = new_local_vclock

                notice("clock now: " + str(vclocks_by_request.get(request_id_string, vclock_new())))

                # Maintain the execution index for each request.

                incoming_execution_index_string = context.get_value(_FILIBUSTER_EXECUTION_INDEX_KEY)

                if incoming_execution_index_string is not None:
                    incoming_execution_index = execution_index_fromstring(incoming_execution_index_string)
                else:
                    execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
                    incoming_execution_index = execution_indices_by_request.get(request_id_string,
                                                                                execution_index_new())

                debug("clock now: " + str(vclocks_by_request.get(request_id_string, vclock_new())))

                if os.environ.get("PRETTY_EXECUTION_INDEXES", ""):
                    execution_index_hash = url
                else:
                    # TODO: can't include kwargs here, not sure why, i think it's metadata?  anyway, should be blank mostly since
                    #       everything should be converted to args by this point.
                    #       could also be None?
                    # Remove host information. This allows us to run counterexamples across different
                    # platforms (local, docker, eks) that use different hosts to resolve networking.
                    # I.e. since we want http://0.0.0.0:5000/users (local) and http://users:5000/users
                    # (docker) to have the same execution index hash, standardize the url to include 
                    # only the port and path (5000/users). 
                    url = url.replace('http://', '')
                    if ":" in url:
                        url = url.split(":", 1)[1]

                    if os.environ.get("EI_DISABLE_CALL_STACK_HASH", ""):
                        execution_index_hash = unique_request_hash(
                            ['requests', method, json.dumps(url)])
                    else:
                        execution_index_hash = unique_request_hash(
                            [full_traceback_hash, 'requests', method, json.dumps(url)])

                execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
                execution_indices_by_request[request_id_string] = execution_index_push(execution_index_hash,
                                                                                       incoming_execution_index)
                execution_index = execution_indices_by_request[request_id_string]
                _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

                ei_and_vclock_mutex.release()

                # Origin VClock Handling.

                # origin-vclock are used to track the explicit request chain
                # that caused this call to be made: more precise than
                # happens-before and required for the reduction strategy to
                # work.
                #
                # For example, if Service A does 4 requests, in sequence,
                # before making a call to Service B, happens-before can be used
                # to show those four requests happened before the call to
                # Service B.  This is correct: vector/Lamport clock track both 
                # program order and the communication between nodes in their encoding.
                #
                # However, for the reduction strategy to work, we need to know
                # precisely *what* call in in Service A triggered the call to
                # Service B (and, recursively if Service B is to make any
                # calls, as well.) This is because the key to the reduction
                # strategy is to remove tests from the execution list where
                # there is no observable difference at the boundary between the
                # two services. Therefore, we need to identify precisely where
                # these boundary points are.
                #

                # This is a clock that's been received through Flask as part of processing the current request.
                # (flask receives context via header and sets into context object; requests reads it.)
                incoming_origin_vclock_string = context.get_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY)
                debug("** [REQUESTS] [" + service_name + "]: getting incoming origin vclock string: " + str(
                    incoming_origin_vclock_string))

                # This isn't used in the record_call, but just propagated through the headers in the subsequent request.
                origin_vclock = vclock

                # Record call with the incoming origin clock and advanced clock.
                if incoming_origin_vclock_string is not None:
                    incoming_origin_vclock = vclock_fromstring(incoming_origin_vclock_string)
                else:
                    incoming_origin_vclock = vclock_new()
                response = _record_call(self, method, [url], callsite_file, callsite_line, full_traceback_hash, vclock,
                                        incoming_origin_vclock, execution_index_tostring(execution_index), kwargs)

                if response is not None:
                    if 'generated_id' in response:
                        generated_id = response['generated_id']

                    if 'execution_index' in response:
                        has_execution_index = True

                    if 'forced_exception' in response:
                        exception = response['forced_exception']['name']

                        if 'metadata' in response['forced_exception'] and response['forced_exception'][
                            'metadata'] is not None:
                            exception_metadata = response['forced_exception']['metadata']
                            if 'abort' in exception_metadata and exception_metadata['abort'] is not None:
                                should_abort = exception_metadata['abort']
                            if 'sleep' in exception_metadata and exception_metadata['sleep'] is not None:
                                should_sleep_interval = exception_metadata['sleep']

                        should_inject_fault = True

                    if 'failure_metadata' in response:
                        if 'return_value' in response['failure_metadata'] and 'status_code' in \
                                response['failure_metadata']['return_value']:
                            status_code = response['failure_metadata']['return_value']['status_code']
                            should_inject_fault = True

                debug("Finished recording call using Filibuster instrumentation service. ***********")
                debug("")
            else:
                debug("Instrumentation suppressed, skipping Filibuster instrumentation.")

        try:
            debug("Setting Filibuster instrumentation key...")
            token = context.attach(context.set_value(_FILIBUSTER_SUPPRESS_REQUESTS_INSTRUMENTATION_KEY, True))

            if has_execution_index:
                request_id = context.get_value("filibuster_request_id")
                if not should_inject_fault:
                    # Propagate vclock and origin vclock forward.
                    result = call_wrapped(
                        {
                            'X-Filibuster-Generated-Id': str(generated_id),
                            'X-Filibuster-VClock': vclock_tostring(vclock),
                            'X-Filibuster-Origin-VClock': vclock_tostring(origin_vclock),
                            'X-Filibuster-Execution-Index': execution_index_tostring(execution_index),
                            'X-Filibuster-Request-Id': str(request_id)
                        }
                    )
                elif should_inject_fault and not should_abort:
                    # Propagate vclock and origin vclock forward.
                    result = call_wrapped(
                        {
                            'X-Filibuster-Generated-Id': str(generated_id),
                            'X-Filibuster-VClock': vclock_tostring(vclock),
                            'X-Filibuster-Origin-VClock': vclock_tostring(origin_vclock),
                            'X-Filibuster-Execution-Index': execution_index_tostring(execution_index),
                            'X-Filibuster-Forced-Sleep': str(should_sleep_interval),
                            'X-Filibuster-Request-Id': str(request_id)
                        }
                    )
                else:
                    # Return entirely fake response and do not make request.
                    #
                    # Since this isn't a real result object, there's some attribute that's
                    # being set to None and that's causing -- for these requests -- the opentelemetry
                    # to not be able to report this correctly with the following error in the output:
                    # 
                    # "Invalid type NoneType for attribute value.
                    # Expected one of ['bool', 'str', 'int', 'float'] or a sequence of those types"
                    #
                    # I'm going to ignore this for now, because if we reorder the instrumentation
                    # so that the opentelemetry is installed *before* the Filibuster instrumentation
                    # we should be able to avoid this -- it's because we're returning an invalid
                    # object through the opentelemetry instrumentation.
                    #
                    result = Response()
            else:
                result = call_wrapped({})
        except Exception as exc:
            exception = exc
            result = getattr(exc, "response", None)
        finally:
            debug("Removing instrumentation key for Filibuster.")
            context.detach(token)

        # Result was an actual response.
        if isinstance(result, Response) and (exception is None or exception == "None"):
            debug("_instrumented_requests_call got response!")

            if has_execution_index:
                _update_execution_index(self)

            if should_inject_fault:
                # If the status code should be something else, change it.
                if status_code is not None:
                    result.status_code = int(status_code)
                    # Get the default response for the status code.
                    default_response = ''
                    if os.environ.get('SET_ERROR_CONTENT', ''):
                        default_response = get_response(status_code)
                    result.headers['Content-Type'] = 'text/html'
                    result._content = default_response.encode()

            # Notify the filibuster server of the actual response.
            if generated_id is not None:
                _record_successful_response(self, generated_id, execution_index_tostring(execution_index), vclock,
                                            result)

            if result.raw and result.raw.version:
                version = (str(result.raw.version)[:1] + "." + str(result.raw.version)[:-1])
                debug("=> http.version: " + version)

            debug("=> http.status_code: " + str(result.status_code))

        # Result was an exception. 
        if exception is not None and exception != "None":
            if isinstance(exception, str):
                exception_class = eval(exception)
                exception = exception_class()
                use_traceback = False
            else:
                if context.get_value(_FILIBUSTER_INSTRUMENTATION_KEY):
                    # If the Filibuster instrumentation call failed, ignore.  This just means
                    # that the test server is unavailable.
                    warning("Filibuster instrumentation server unreachable, ignoring...")
                    warning("If fault injection is enabled... this indicates that something isn't working properly.")
                else:
                    try:
                        exception_info = exception.rsplit('.', 1)
                        m = importlib.import_module(exception_info[0])
                        exception = getattr(m, exception_info[1])
                    except Exception:
                        warning("Couldn't get actual exception due to exception parse error.")

                use_traceback = True

            if not context.get_value(_FILIBUSTER_INSTRUMENTATION_KEY):
                debug("got exception!")
                debug("=> exception: " + str(exception))

                if has_execution_index:
                    _update_execution_index(self)

                # Notify the filibuster server of the actual exception we encountered.
                if generated_id is not None:
                    _record_exceptional_response(self, generated_id, execution_index_tostring(execution_index), vclock,
                                                 exception, should_sleep_interval, should_abort)

                if use_traceback:
                    raise exception.with_traceback(exception.__traceback__)
                else:
                    raise exception

        debug("_instrumented_requests_call exiting; method: " + method + " url: " + url)
        return result

    instrumented_request.opentelemetry_instrumentation_requests_applied = True
    Session.request = instrumented_request

    instrumented_send.opentelemetry_instrumentation_requests_applied = True
    Session.send = instrumented_send

    def _record_call(self, method, args, callsite_file, callsite_line, full_traceback, vclock, origin_vclock,
                     execution_index, kwargs):
        response = None
        parsed_content = None

        try:
            debug("Setting Filibuster instrumentation key...")
            token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

            payload = {
                'instrumentation_type': 'invocation',
                'source_service_name': service_name,
                'module': 'requests',
                'method': method,
                'args': args,
                'kwargs': {},
                'callsite_file': callsite_file,
                'callsite_line': callsite_line,
                'full_traceback': full_traceback,
                'metadata': {},
                'vclock': vclock,
                'origin_vclock': origin_vclock,
                'execution_index': execution_index
            }

            if 'timeout' in kwargs:
                if kwargs['timeout'] is not None:
                    debug("=> timeout for call is set to " + str(kwargs['timeout']))
                    payload['metadata']['timeout'] = kwargs['timeout']
                try:
                    if args.index('https') >= 0:
                        payload['metadata']['ssl'] = True
                except ValueError:
                    pass

            if counterexample is not None and counterexample_test_execution is not None:
                debug("Using counterexample without contacting server.")
                response = should_fail_request_with(payload, counterexample_test_execution.failures)
                if response is None:
                    response = {'execution_index': execution_index}
            if os.environ.get('DISABLE_SERVER_COMMUNICATION', ''):
                warning("Server communication disabled.")
            elif counterexample is not None:
                debug("Skipping request, replaying from local counterexample.")
            else:
                response = wrapped_request(self, 'put', filibuster_create_url(filibuster_url), json=payload)
        except Exception as e:
            warning("Exception raised (_record_call)!")
            print(e, file=sys.stderr)
            return None
        finally:
            debug("Removing instrumentation key for Filibuster.")
            context.detach(token)

        if isinstance(response, dict):
            parsed_content = response
        elif response is not None:
            try:
                parsed_content = response.json()
            except Exception as e:
                warning("Exception raised (_record_call get_json)!")
                print(e, file=sys.stderr)
                return None

        return parsed_content

    def _update_execution_index(self):
        global ei_and_vclock_mutex

        ei_and_vclock_mutex.acquire()

        execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
        request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
        if request_id_string in execution_indices_by_request:
            execution_indices_by_request[request_id_string] = execution_index_pop(
                execution_indices_by_request[request_id_string])
            _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

        ei_and_vclock_mutex.release()

    def _record_successful_response(self, generated_id, execution_index, vclock, result):
        # assumes no asynchrony or threads at calling service.

        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
            try:
                debug("Setting Filibuster instrumentation key...")
                token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                return_value = {
                    '__class__': str(result.__class__.__name__),
                    'status_code': str(result.status_code),
                    'text': hashlib.md5(result.text.encode()).hexdigest()
                }
                payload = {
                    'instrumentation_type': 'invocation_complete',
                    'generated_id': generated_id,
                    'execution_index': execution_index,
                    'vclock': vclock,
                    'return_value': return_value
                }
                wrapped_request(self, 'post', filibuster_update_url(filibuster_url), json=payload)
            except Exception as e:
                warning("Exception raised (_record_successful_response)!")
                print(e, file=sys.stderr)
            finally:
                debug("Removing instrumentation key for Filibuster.")
                context.detach(token)

        return True

    def _record_exceptional_response(self, generated_id, execution_index, vclock, exception, should_sleep_interval,
                                     should_abort):
        # assumes no asynchrony or threads at calling service.

        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')):
            try:
                debug("Setting Filibuster instrumentation key...")
                token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                exception_to_string = str(type(exception))
                parsed_exception_string = re.findall(r"'(.*?)'", exception_to_string, re.DOTALL)[0]
                payload = {
                    'instrumentation_type': 'invocation_complete',
                    'generated_id': generated_id,
                    'execution_index': execution_index,
                    'vclock': vclock,
                    'exception': {
                        'name': parsed_exception_string,
                        'metadata': {

                        }
                    }
                }

                if should_sleep_interval > 0:
                    payload['exception']['metadata']['sleep'] = should_sleep_interval

                if should_abort is not True:
                    payload['exception']['metadata']['abort'] = should_abort

                wrapped_request(self, 'post', filibuster_update_url(filibuster_url), json=payload)
            except Exception as e:
                warning("Exception raised (_record_exceptional_response)!")
                print(e, file=sys.stderr)
            finally:
                debug("Removing instrumentation key for Filibuster.")
                context.detach(token)

        return True

    # For a given request, return a unique hash that can be used to identify it.
    def unique_request_hash(args):
        hash_string = "-".join(args)
        hex_digest = hashlib.md5(hash_string.encode()).hexdigest()
        return hex_digest


def _uninstrument():
    """Disables instrumentation of :code:`requests` through this module.

    Note that this only works if no other module also patches requests."""
    _uninstrument_from(Session)


def _uninstrument_from(instr_root, restore_as_bound_func=False):
    for instr_func_name in ("request", "send"):
        instr_func = getattr(instr_root, instr_func_name)
        if not getattr(
                instr_func,
                "opentelemetry_instrumentation_requests_applied",
                False,
        ):
            continue

        original = instr_func.__wrapped__  # pylint:disable=no-member
        if restore_as_bound_func:
            original = types.MethodType(original, instr_root)
        setattr(instr_root, instr_func_name, original)


class RequestsInstrumentor(BaseInstrumentor):
    """An instrumentor for requests
    See `BaseInstrumentor`
    """

    def _instrument(self, **kwargs):
        """Instruments requests module

        Args:
            **kwargs: Optional arguments
                ``tracer_provider``: a TracerProvider, defaults to global
                ``span_callback``: An optional callback invoked before returning the http response. Invoked with Span and requests.Response
                ``name_callback``: Callback which calculates a generic span name for an
                    outgoing HTTP request based on the method and url.
        """
        if (os.environ.get('DISABLE_INSTRUMENTATION', '')):
            debug("Not instrumenting. DISABLE_INSTRUMENTATION set.")
            return

        _instrument(
            service_name=kwargs.get("service_name"),
            filibuster_url=kwargs.get("filibuster_url")
        )

    def _uninstrument(self, **kwargs):
        _uninstrument()

    @staticmethod
    def uninstrument_session(session):
        """Disables instrumentation on the session object."""
        _uninstrument_from(session, restore_as_bound_func=True)
