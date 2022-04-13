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

import sys
import re
import hashlib
import os

from threading import Lock

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
    service_name=None
):
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
            status_code = None
            should_inject_fault = False
            should_abort = True
            should_sleep_interval = 0
            vclock = None
            origin_vclock = None
            execution_index = None

            debug("_instrumented_redis_call entering; method: " + name)

            fuck = context.get_value("suppress_instrumentation")

            # Record that a call is being made to an external service
            if not context.get_value("suppress_instrumentation"):
                callsite_file, callsite_line, full_traceback_hash = get_full_traceback_hash(service_name)
                debug("")
                debug("Recording call using Filibuster instrumentation service. ********************")

                # VClock handling

                # TODO: did not do stuff with new-test-excution

                global ei_and_vclock_mutex
                ei_and_vclock_mutex.acquire()

                request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)

                ## TODO: did not reset local vclock, since we don't reset things for new test executions?

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
                execution_index_hash = unique_request_hash(
                    [full_traceback_hash, 'redis', name, json.dumps(args), json.dumps(kwargs)])

                execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
                execution_indices_by_request[request_id_string] = execution_index_push(execution_index_hash,
                                                                                       incoming_execution_index)
                execution_index = execution_indices_by_request[request_id_string]
                _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

                ei_and_vclock_mutex.release()

                response = func(*args, **kwargs)

            else:
                debug("Instrumentation suppressed, skipping Filibuster instrumentation.")
                response = func(*args, **kwargs)
            return response

    # For a given request, return a unique hash that can be used to identify it.
    def unique_request_hash(args):
        for arg in args:
            print(arg)
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
            service_name=kwargs.get("service_name")
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