Instrumenting Services To Receive Calls
=======================================

Next, we need to capture the incoming metadata and propagate it to any further service calls.  We need to notify the Filibuster server of the service that was reached to resolve dynamic binding.

Metadata Propagation
--------------------

We extract the metadata from the request metadata, assign a request id if the current request does not have one, and then assign it to the thread context.

.. code-block:: python

        ## *******************************************************************************************
        ## START PARSE METADATA AND CONTEXT PROPAGATION
        ## *******************************************************************************************

        metadata = dict(context.invocation_metadata())

        request_id = None
        sleep_interval = 0

        # Parse incoming metadata.

        if 'x-filibuster-request-id' in metadata:
            request_id = metadata['x-filibuster-request-id']

        generated_id = metadata['x-filibuster-generated-id']
        vclock_str = metadata['x-filibuster-vclock']
        vclock = vclock_fromstring(vclock_str)
        origin_vclock_str = metadata['x-filibuster-origin-vclock']
        origin_vclock = vclock_fromstring(origin_vclock_str)
        execution_index = metadata['x-filibuster-execution-index']

        if 'x-filibuster-forced-sleep' in metadata:
            sleep_interval = int(metadata['x-filibuster-forced-sleep'])

        notice("request_id: " + str(request_id))
        notice("generated_id: " + str(generated_id))
        notice("vclock: " + str(vclock))
        notice("origin_vclock: " + str(origin_vclock))
        notice("execution_index: " + str(execution_index))
        notice("sleep_interval: " + str(sleep_interval))

        # Assign request id if none is provided.
        if request_id is None:
            request_id = str(uuid.uuid4())

        # Attach metadata to thread context.
        attach(set_value(_FILIBUSTER_VCLOCK_KEY, vclock_str))
        attach(set_value(_FILIBUSTER_REQUEST_ID_KEY, request_id))
        attach(set_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY, origin_vclock))
        attach(set_value(_FILIBUSTER_EXECUTION_INDEX_KEY, execution_index))

        ## *******************************************************************************************
        ## END PARSE METADATA AND CONTEXT PROPAGATION
        ## *******************************************************************************************

Instrumentation Call
--------------------

Finally, we issue a call to the Filibuster server to notify it of which server the request arrived at.  We only do this if the request has a generated id, which means it is an instrumented Filibuster request.

.. code-block:: python

        ## *******************************************************************************************
        ## START INSTRUMENTATION CALL
        ## *******************************************************************************************

        if generated_id:
            notice("Generated id is set, issuing update.")

            payload = {
                'instrumentation_type': 'request_received',
                'generated_id': str(generated_id),
                'target_service_name': service_name
            }

            token = attach(set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))
            if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')):
                try:
                    requests.post(filibuster_update_url(filibuster_url), json=payload)
                except Exception as e:
                    warning("Exception raised during instrumentation (_record_successful_response)!")
                    print(e, file=sys.stderr)
                finally:
                    notice("Removing instrumentation key for Filibuster.")
                    detach(token)
        else:
            notice("No generated id.")

        ## *******************************************************************************************
        ## END INSTRUMENTATION CALL
        ## *******************************************************************************************
