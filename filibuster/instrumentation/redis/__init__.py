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
#
"""
Instrument `redis`_ to report Redis queries.

There are two options for instrumenting code. The first option is to use the
``opentelemetry-instrumentation`` executable which will automatically
instrument your Redis client. The second is to programmatically enable
instrumentation via the following code:

.. _redis: https://pypi.org/project/redis/

Usage
-----

.. code:: python

    from opentelemetry.instrumentation.redis import RedisInstrumentor
    import redis

    # Instrument redis
    RedisInstrumentor().instrument()

    # This will report a span with the default settings
    client = redis.StrictRedis(host="localhost", port=6379)
    client.get("my-key")

The `instrument` method accepts the following keyword args:

tracer_provider (TracerProvider) - an optional tracer provider

request_hook (Callable) - a function with extra user-defined logic to be performed before performing the request
this function signature is:  def request_hook(span: Span, instance: redis.connection.Connection, args, kwargs) -> None

response_hook (Callable) - a function with extra user-defined logic to be performed after performing the request
this function signature is: def response_hook(span: Span, instance: redis.connection.Connection, response) -> None

for example:

.. code: python

    from opentelemetry.instrumentation.redis import RedisInstrumentor
    import redis

    def request_hook(span, instance, args, kwargs):
        if span and span.is_recording():
            span.set_attribute("custom_user_attribute_from_request_hook", "some-value")

    def response_hook(span, instance, response):
        if span and span.is_recording():
            span.set_attribute("custom_user_attribute_from_response_hook", "some-value")

    # Instrument redis with hooks
    RedisInstrumentor().instrument(request_hook=request_hook, response_hook=response_hook)

    # This will report a span with the default settings and the custom attributes added from the hooks
    client = redis.StrictRedis(host="localhost", port=6379)
    client.get("my-key")

API
---
"""
import typing
from typing import Any, Collection

import redis
from wrapt import wrap_function_wrapper

import functools
import types
import json
import time

import sys
import re
import hashlib
import os

from threading import Lock

import requests
from requests.models import Response

from opentelemetry import context
from opentelemetry import trace
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.redis.util import (
    _extract_conn_attributes,
    _format_command_args,
)
from opentelemetry.instrumentation.redis.version import __version__
from opentelemetry.instrumentation.utils import unwrap
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import Span

import importlib

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

_RequestHookT = typing.Optional[
    typing.Callable[
        [Span, redis.connection.Connection, typing.List, typing.Dict], None
    ]
]
_ResponseHookT = typing.Optional[
    typing.Callable[[Span, redis.connection.Connection, Any], None]
]


def _set_connection_attributes(span, conn):
    if not span.is_recording():
        return
    for key, value in _extract_conn_attributes(
        conn.connection_pool.connection_kwargs
    ).items():
        span.set_attribute(key, value)


def _instrument(
    tracer,
    request_hook: _RequestHookT = None,
    response_hook: _ResponseHookT = None,
    service_name=None,
    filibuster_url=None
):
    def filibuster_update_url(filibuster_url):
        return "{}/{}/update".format(filibuster_url, 'filibuster')

    def filibuster_create_url(filibuster_url):
        return "{}/{}/create".format(filibuster_url, 'filibuster')

    def filibuster_new_test_execution_url(filibuster_url, service_name):
        return "{}/{}/new-test-execution/{}".format(filibuster_url, 'filibuster', service_name)

    def _traced_execute_command(func, instance, args, kwargs):
        query = _format_command_args(args)
        name = ""
        if len(args) > 0 and args[0]:
            name = args[0]
        else:
            name = instance.connection_pool.connection_kwargs.get("db", 0)

        with tracer.start_as_current_span(
            name, kind=trace.SpanKind.CLIENT
        ) as span:
            if span.is_recording():
                span.set_attribute(SpanAttributes.DB_STATEMENT, query)
                _set_connection_attributes(span, instance)
                span.set_attribute("db.redis.args_length", len(args))

            if callable(request_hook):
                request_hook(span, instance, args, kwargs)

            response = _instrumented_redis_call(service_name, func, name, args, **kwargs)
            if callable(response_hook):
                response_hook(span, instance, response)
            return response

    def _traced_execute_pipeline(func, instance, args, kwargs):
        cmds = [_format_command_args(c) for c, _ in instance.command_stack]
        resource = "\n".join(cmds)

        span_name = " ".join([args[0] for args, _ in instance.command_stack])

        with tracer.start_as_current_span(
            span_name, kind=trace.SpanKind.CLIENT
        ) as span:
            if span.is_recording():
                span.set_attribute(SpanAttributes.DB_STATEMENT, resource)
                _set_connection_attributes(span, instance)
                span.set_attribute(
                    "db.redis.pipeline_length", len(instance.command_stack)
                )
            response = func(*args, **kwargs)
            if callable(response_hook):
                response_hook(span, instance, response)
            return response

    def _instrumented_redis_call(
            service_name, func, name: str, args, **kwargs
        ):
            generated_id = None
            has_execution_index = False
            exception = None
            should_inject_fault = False
            should_abort = True
            should_sleep_interval = 0
            vclock = None
            origin_vclock = None
            execution_index = None

            debug("_instrumented_redis_call entering; method: " + name)

            # Record that a call is being made to an external service
            if not context.get_value("suppress_instrumentation"):
                callsite_file, callsite_line, full_traceback_hash = get_full_traceback_hash(service_name)
                debug("")
                debug("Recording call using Filibuster instrumentation service. ********************")

                # VClock handling

                # Figure out if we should reset the node's vector clock, which should happen in between test executions.
                debug("Setting Filibuster instrumentation key...")
                token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                response = None
                if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
                    requests.post('get', filibuster_new_test_execution_url(filibuster_url, service_name))
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

                ## TODO: double check if this url replacement is ok
                ## TODO: pretty print execution_index_hash, like in requests code?
                ## TODO: need use url instead (on two different redis nodes)
                ## TODO: name could be execute_command instead
                execution_index_hash = unique_request_hash(
                    [full_traceback_hash, 'redis', 'execute_command', json.dumps(args), json.dumps(kwargs)])

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
                response = _record_call(service_name, func, name, args, callsite_file, callsite_line, full_traceback_hash, vclock,
                                        incoming_origin_vclock, execution_index_tostring(execution_index), **kwargs)

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

                    ## TODO: fix once Filibuster injects faulty responses
                    if 'failure_metadata' in response:
                        if 'return_value' in response['failure_metadata'] and 'status_code' in \
                                response['failure_metadata']['return_value']:
                            should_inject_fault = True

                debug("Finished recording call using Filibuster instrumentation service. ***********")
                debug("")
            else:
                debug("Instrumentation suppressed, skipping Filibuster instrumentation.")

            try:
                if not should_inject_fault:
                    # no need to propagate vclock and origin vclock forward,
                    # since redis-server won't use it
                    result = func(*args, **kwargs)
                elif should_inject_fault and not should_abort:
                    # If we should delay the request to simulate timeouts, do it.
                    if should_sleep_interval != 0:
                        time.sleep(should_sleep_interval)

                    # no need to propagate vclock and origin vclock forward,
                    # since redis-server won't use it
                    result = func(*args, **kwargs)
                else:
                    # Return entirely fake response and do not make request.
                    ## TODO: fix (redis may return 0 for s.ismember if it doesn't find it)
                    result = None
            except Exception as exc:
                exception = exc
                result = getattr(exc, "response", None)
            finally:
                debug("Removing instrumentation key for Filibuster.")
                # context.detach(token)

            # Result was an actual response.
            if not result is None and (exception is None or exception == "None"):
                debug("_instrumented_requests_call got response!")

                if has_execution_index:
                    _update_execution_index()

                 # Notify the filibuster server of the actual response.
                if generated_id is not None:
                    _record_successful_response(generated_id, execution_index_tostring(execution_index), vclock,
                                                result)

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
                        _update_execution_index()

                    # Notify the filibuster server of the actual exception we encountered.
                    if generated_id is not None:
                        _record_exceptional_response(generated_id, execution_index_tostring(execution_index), vclock,
                                                    exception, should_sleep_interval, should_abort)

                    if use_traceback:
                        raise exception.with_traceback(exception.__traceback__)
                    else:
                        raise exception

            debug("_instrumented_requests_call exiting; method: " + name)

            return result

    def _record_call(service_name, func, name, args, callsite_file, callsite_line, full_traceback, vclock, origin_vclock,
                     execution_index, **kwargs):
        response = None
        parsed_content = None

        try:
            debug("Setting Filibuster instrumentation key...")
            token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

            payload = {
                'instrumentation_type': 'invocation',
                'source_service_name': service_name,
                'module': 'redis',
                ## TODO: fix this hardcoding
                'method': "execute_command",
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

            if counterexample is not None and counterexample_test_execution is not None:
                notice("Using counterexample without contacting server.")
                response = should_fail_request_with(payload, counterexample_test_execution.failures)
                if response is None:
                    response = {'execution_index': execution_index}

            if os.environ.get('DISABLE_SERVER_COMMUNICATION', ''):
                warning("Server communication disabled.")
            elif counterexample is not None:
                notice("Skipping request, replaying from local counterexample.")
            else:
                requests.post(filibuster_create_url(filibuster_url), json = payload)
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

    def _update_execution_index():
        global ei_and_vclock_mutex

        ei_and_vclock_mutex.acquire()

        execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
        request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
        if request_id_string in execution_indices_by_request:
            execution_indices_by_request[request_id_string] = execution_index_pop(
                execution_indices_by_request[request_id_string])
            _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

        ei_and_vclock_mutex.release()

    def _record_successful_response(generated_id, execution_index, vclock, result):
        # assumes no asynchrony or threads at calling service.

        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
            try:
                debug("Setting Filibuster instrumentation key...")
                token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                ## TODO: double check if this is ok
                return_value = {
                    '__class__': str(result.__class__.__name__),
                    'value': result,
                    'text': hashlib.md5(result.text.encode()).hexdigest()
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
                warning("Exception raised (_record_successful_response)!")
                print(e, file=sys.stderr)
            finally:
                debug("Removing instrumentation key for Filibuster.")
                context.detach(token)

        return True

    def _record_exceptional_response(generated_id, execution_index, vclock, exception, should_sleep_interval,
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

                requests.post(filibuster_update_url(filibuster_url), json=payload)
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

    pipeline_class = (
        "BasePipeline" if redis.VERSION < (3, 0, 0) else "Pipeline"
    )
    redis_class = "StrictRedis" if redis.VERSION < (3, 0, 0) else "Redis"

    wrap_function_wrapper(
        "redis", f"{redis_class}.execute_command", _traced_execute_command
    )
    wrap_function_wrapper(
        "redis.client",
        f"{pipeline_class}.execute",
        _traced_execute_pipeline,
    )
    wrap_function_wrapper(
        "redis.client",
        f"{pipeline_class}.immediate_execute_command",
        _traced_execute_command,
    )


class RedisInstrumentor(BaseInstrumentor):
    """An instrumentor for Redis
    See `BaseInstrumentor`
    """

    def _instrument(self, **kwargs):
        """Instruments the redis module

        Args:
            **kwargs: Optional arguments
                ``tracer_provider``: a TracerProvider, defaults to global.
                ``response_hook``: An optional callback which is invoked right before the span is finished processing a response.
        """
        tracer_provider = kwargs.get("tracer_provider")
        tracer = trace.get_tracer(
            __name__, __version__, tracer_provider=tracer_provider
        )
        _instrument(
            tracer,
            request_hook=kwargs.get("request_hook"),
            response_hook=kwargs.get("response_hook"),
            service_name=kwargs.get("service_name"),
            filibuster_url=kwargs.get("filibuster_url")
        )

    def _uninstrument(self, **kwargs):
        if redis.VERSION < (3, 0, 0):
            unwrap(redis.StrictRedis, "execute_command")
            unwrap(redis.StrictRedis, "pipeline")
            unwrap(redis.Redis, "pipeline")
            unwrap(
                redis.client.BasePipeline,  # pylint:disable=no-member
                "execute",
            )
            unwrap(
                redis.client.BasePipeline,  # pylint:disable=no-member
                "immediate_execute_command",
            )
        else:
            unwrap(redis.Redis, "execute_command")
            unwrap(redis.Redis, "pipeline")
            unwrap(redis.client.Pipeline, "execute")
            unwrap(redis.client.Pipeline, "immediate_execute_command")