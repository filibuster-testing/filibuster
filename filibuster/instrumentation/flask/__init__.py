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

# Note: This package is not named "flask" because of
# https://github.com/PyCQA/pylint/issues/2648

"""
This library builds on the OpenTelemetry WSGI middleware to track web requests
in Flask applications. In addition to opentelemetry-util-http, it
supports Flask-specific features such as:

* The Flask url rule pattern is used as the Span name.
* The ``http.route`` Span attribute is set so that one can see which URL rule
  matched a request.

Usage
-----

.. code-block:: python

    from flask import Flask
    from opentelemetry.instrumentation.flask import FlaskInstrumentor

    app = Flask(__name__)

    FlaskInstrumentor().instrument_app(app)

    @app.route("/")
    def hello():
        return "Hello!"

    if __name__ == "__main__":
        app.run(debug=True)

API
---
"""
import time
from logging import getLogger

import sys
import os
import flask
import requests
import uuid 

import opentelemetry.instrumentation.wsgi as otel_wsgi

from filibuster.datatypes import TestExecution
from filibuster.logger import error, warning, notice, info, debug

from opentelemetry import context, propagators, trace
from opentelemetry.instrumentation.flask.version import __version__
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.util import time_ns
from opentelemetry.util.http import get_excluded_urls

from filibuster.server_helpers import load_counterexample

_logger = getLogger(__name__)

_ENVIRON_STARTTIME_KEY = "opentelemetry-flask.starttime_key"
_ENVIRON_SPAN_KEY = "opentelemetry-flask.span_key"
_ENVIRON_ACTIVATION_KEY = "opentelemetry-flask.activation_key"
_ENVIRON_TOKEN = "opentelemetry-flask.token"

_FILIBUSTER_INSTRUMENTATION_KEY = "filibuster_instrumentation"
_FILIBUSTER_VCLOCK_KEY = "filibuster_vclock"
_FILIBUSTER_ORIGIN_VCLOCK_KEY = "filibuster_origin_vclock"
_FILIBUSTER_EXECUTION_INDEX_KEY = "filibuster_execution_index"
_FILIBUSTER_REQUEST_ID_KEY = "filibuster_request_id"

_excluded_urls = get_excluded_urls("FLASK")

from os.path import exists

COUNTEREXAMPLE_FILE = "/tmp/filibuster/counterexample.json"
if exists(COUNTEREXAMPLE_FILE):
    notice("Counterexample file present!")
    counterexample = load_counterexample(COUNTEREXAMPLE_FILE)
    counterexample_test_execution = TestExecution.from_json(counterexample['TestExecution']) if counterexample else None
    print(counterexample_test_execution.failures)
else:
    counterexample = None


def get_default_span_name():
    span_name = ""
    try:
        span_name = flask.request.url_rule.rule
    except AttributeError:
        span_name = otel_wsgi.get_default_span_name(flask.request.environ)
    return span_name


def _rewrapped_app(wsgi_app):
    def _wrapped_app(wrapped_app_environ, start_response):
        # We want to measure the time for route matching, etc.
        # In theory, we could start the span here and use
        # update_name later but that API is "highly discouraged" so
        # we better avoid it.
        wrapped_app_environ[_ENVIRON_STARTTIME_KEY] = time_ns()

        def _start_response(status, response_headers, *args, **kwargs):
            if not _excluded_urls.url_disabled(flask.request.url):
                span = flask.request.environ.get(_ENVIRON_SPAN_KEY)

                if span:
                    otel_wsgi.add_response_attributes(
                        span, status, response_headers
                    )
                else:
                    _logger.warning(
                        "Flask environ's OpenTelemetry span "
                        "missing at _start_response(%s)",
                        status,
                    )

            return start_response(status, response_headers, *args, **kwargs)

        return wsgi_app(wrapped_app_environ, _start_response)

    return _wrapped_app

def filibuster_update_url(filibuster_url):
    return "{}/{}/update".format(filibuster_url, 'filibuster')

def _wrapped_before_request(name_callback, service_name, filibuster_url):
    def _before_request():
        if _excluded_urls.url_disabled(flask.request.url):
            return

        # Each request needs to maintain some things independently of the global state (e.g. 
        # execution_index, vclock) for when we issue multiple requests. Unique request_ids
        # can distinguish one request from another. Generate a new unique request_id if one
        # doesn't already exist (new request), otherwise use the existing one.
        if 'X-Filibuster-Request-Id' in flask.request.headers and flask.request.headers['X-Filibuster-Request-Id'] is not None:
            request_id = flask.request.headers['X-Filibuster-Request-Id']
            debug("Using old request_id: " + request_id)
        else:
            request_id = str(uuid.uuid4())
            debug("Using new request_id: " + request_id)
        context.attach(context.set_value(_FILIBUSTER_REQUEST_ID_KEY, request_id))
        debug("** [FLASK] [" + service_name + "]: request-id attached to context: " + str(context.get_value(_FILIBUSTER_REQUEST_ID_KEY)))

        if 'X-Filibuster-Execution-Index' in flask.request.headers and flask.request.headers['X-Filibuster-Execution-Index'] is not None:

            payload = { 
                'instrumentation_type': 'request_received',
                'generated_id': str(flask.request.headers['X-Filibuster-Generated-Id']),
                'execution_index': str(flask.request.headers['X-Filibuster-Execution-Index']),
                'target_service_name': service_name
            }

            # All this is responsible for doing is putting the header execution index into the context
            # so that any requests that are triggered from this have the existing execution index.
            context.attach(context.set_value(_FILIBUSTER_EXECUTION_INDEX_KEY, flask.request.headers['X-Filibuster-Execution-Index']))
            debug("** [FLASK] [" + service_name + "]: execution-index attached to context: " + str(context.get_value(_FILIBUSTER_EXECUTION_INDEX_KEY)))

            # All this is responsible for doing is putting the header vclock into the context
            # so that any requests that are triggered from this, know to merge the incoming vclock in.
            context.attach(context.set_value(_FILIBUSTER_VCLOCK_KEY, flask.request.headers['X-Filibuster-VClock']))
            debug("** [FLASK] [" + service_name + "]: vclock attached to context: " + str(context.get_value(_FILIBUSTER_VCLOCK_KEY)))

            # All this is responsible for doing is putting the header origin vclock into the context
            # so that any requests that are triggered from this, know to merge the incoming vclock in.
            context.attach(context.set_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY, flask.request.headers['X-Filibuster-Origin-VClock']))
            debug("** [FLASK] [" + service_name + "]: origin-vclock attached to context: " + str(context.get_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY)))

            if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')) and counterexample is None:
                try:
                    debug("Setting Filibuster instrumentation key...")
                    token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

                    requests.post(filibuster_update_url(filibuster_url), json = payload)
                except Exception as e:
                    warning("Exception raised during instrumentation (_record_successful_response)!")
                    print(e, file=sys.stderr)
                finally:
                    debug("Removing instrumentation key for Filibuster.")
                    context.detach(token)

        # If we should delay the request to simulate timeouts, do it.
        if 'X-Filibuster-Forced-Sleep' in flask.request.headers and flask.request.headers['X-Filibuster-Forced-Sleep'] is not None:
            sleep_interval_string = flask.request.headers['X-Filibuster-Forced-Sleep']
            sleep_interval = int(sleep_interval_string)
            if sleep_interval != 0:
                time.sleep(sleep_interval)

        flask_request_environ = flask.request.environ
        span_name = name_callback()
        token = context.attach(
            propagators.extract(
                otel_wsgi.carrier_getter, flask_request_environ
            )
        )

        tracer = trace.get_tracer(__name__, __version__)

        span = tracer.start_span(
            span_name,
            kind=trace.SpanKind.SERVER,
            start_time=flask_request_environ.get(_ENVIRON_STARTTIME_KEY),
        )
        if span.is_recording():
            attributes = otel_wsgi.collect_request_attributes(
                flask_request_environ
            )
            if flask.request.url_rule:
                # For 404 that result from no route found, etc, we
                # don't have a url_rule.
                attributes["http.route"] = flask.request.url_rule.rule
            for key, value in attributes.items():
                span.set_attribute(key, value)

        activation = tracer.use_span(span, end_on_exit=True)
        activation.__enter__()
        flask_request_environ[_ENVIRON_ACTIVATION_KEY] = activation
        flask_request_environ[_ENVIRON_SPAN_KEY] = span
        flask_request_environ[_ENVIRON_TOKEN] = token

    return _before_request


def _teardown_request(exc):
    if _excluded_urls.url_disabled(flask.request.url):
        return

    activation = flask.request.environ.get(_ENVIRON_ACTIVATION_KEY)
    if not activation:
        # This request didn't start a span, maybe because it was created in a
        # way that doesn't run `before_request`, like when it is created with
        # `app.test_request_context`.
        return

    if exc is None:
        activation.__exit__(None, None, None)
    else:
        activation.__exit__(
            type(exc), exc, getattr(exc, "__traceback__", None)
        )
    context.detach(flask.request.environ.get(_ENVIRON_TOKEN))


class _InstrumentedFlask(flask.Flask):

    name_callback = get_default_span_name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._original_wsgi_ = self.wsgi_app
        self.wsgi_app = _rewrapped_app(self.wsgi_app)

        _before_request = _wrapped_before_request(
            _InstrumentedFlask.name_callback
        )
        self._before_request = _before_request
        self.before_request(_before_request)
        self.teardown_request(_teardown_request)


class FlaskInstrumentor(BaseInstrumentor):
    # pylint: disable=protected-access,attribute-defined-outside-init
    """An instrumentor for flask.Flask

    See `BaseInstrumentor`
    """

    def _instrument(self, **kwargs):
        self._original_flask = flask.Flask
        name_callback = kwargs.get("name_callback")
        if callable(name_callback):
            _InstrumentedFlask.name_callback = name_callback
        flask.Flask = _InstrumentedFlask

    def instrument_app(
        self, app, name_callback=get_default_span_name, service_name=None, filibuster_url=None
    ):  # pylint: disable=no-self-use
        if (os.environ.get('DISABLE_INSTRUMENTATION', '')):
            debug("Not instrumenting. DISABLE_INSTRUMENTATION set.")
            return
            
        if not hasattr(app, "_is_instrumented"):
            app._is_instrumented = False

        if not app._is_instrumented:
            app._original_wsgi_app = app.wsgi_app
            app.wsgi_app = _rewrapped_app(app.wsgi_app)

            _before_request = _wrapped_before_request(name_callback, service_name, filibuster_url)
            app._before_request = _before_request
            app.before_request(_before_request)
            app.teardown_request(_teardown_request)
            app._is_instrumented = True
        else:
            _logger.warning(
                "Attempting to instrument Flask app while already instrumented"
            )

    def _uninstrument(self, **kwargs):
        flask.Flask = self._original_flask

    def uninstrument_app(self, app):  # pylint: disable=no-self-use
        if not hasattr(app, "_is_instrumented"):
            app._is_instrumented = False

        if app._is_instrumented:
            app.wsgi_app = app._original_wsgi_app

            app.before_request_funcs[None].remove(app._before_request)
            app.teardown_request_funcs[None].remove(_teardown_request)
            del app._original_wsgi_app

            app._is_instrumented = False
        else:
            _logger.warning(
                "Attempting to uninstrument Flask "
                "app while already uninstrumented"
            )