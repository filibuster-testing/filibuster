Instrumentation Example: Flask
==============================

We start with looking at our Flask instrumentation.

For our Flask instrumentation, we build on the popular ``opentelemetry`` library.  To do this, we modified a copy of the ``opentelemetry-instrumentation-flask`` library and made the following modifications.

We start by modifying the ``before_request`` callback that is executed when an incoming HTTP request is received, but before the application code associated with that route is executed.  We only execute the additional code we are adding if the headers of this request contain a Filibuster generated id header; this allows us to distinguish calls coming from a Filibuster instrumented service.

.. code-block:: python

    if 'X-Filibuster-Generated-Id' in flask.request.headers and flask.request.headers['X-Filibuster-Generated-Id'] is not None:

We next setup the instrumentation calls payload.  In this call, we are going to notify the Filibuster server of the service that the request was terminated at.  In the case of ``cinema-1``'s first request, it is a call from the users service to the bookings service; therefore, we set the ``target_service_name`` field to bookings and the other fields accordingly.

.. code-block:: python

    payload = {
        'instrumentation_type': 'request_received',
        'generated_id': str(flask.request.headers['X-Filibuster-Generated-Id']),
        'execution_index': str(flask.request.headers['X-Filibuster-Execution-Index']),
        'target_service_name': service_name
    }

Using a thread context object provided by the opentelemetry library we extend, we now set the values that we need to propagate to future calls.  This includes the origin vclock, the vclock, and the execution index.  In this example, the constants used here are just strings that represent the name of a key to use in this thread context dictionary.

.. code-block:: python

    context.attach(context.set_value(_FILIBUSTER_VCLOCK_KEY, flask.request.headers['X-Filibuster-VClock']))
    context.attach(context.set_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY, flask.request.headers['X-Filibuster-Origin-VClock']))
    context.attach(context.set_value(_FILIBUSTER_EXECUTION_INDEX_KEY, flask.request.headers['X-Filibuster-Execution-Index']))

Finally, we set a value on the thread context object to indicate that the next request we are going to issue is an instrumentation call -- therefore, we can avoid performing fault injection on our instrumentation -- issue the instrumentation call to the Filibuster server, unset the token, and then proceed on with the rest of the original implementation.

.. code-block:: python

    token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))
    try:
        requests.post(filibuster_update_url(filibuster_url), json = payload)
    except Exception as e:
        warning("Exception raised during instrumentation (_record_successful_response)!")
        print(e, file=sys.stderr)
    finally:
        debug("Removing instrumentation key for Filibuster.")
        context.detach(token)