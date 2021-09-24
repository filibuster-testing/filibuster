Instrumenting Remote Service Calls
==================================

To start, we need to keep track of the remote calls issued by each service and their responses.  To enable dynamic reduction, we need to also associate vector clocks and execution indexes with each request that's issued.

To achieve this, we extend the `opentelemetry` instrumentation for `grpc` with the modifications listed below.

.. note::
    These modifications currently only cover the unary invoker on the insecure channel (without the use of futures.)  Those modifications are straightforward, but are omitted here for this prototype implementation.

Identifying the Call Site
-------------------------

First, we need to identify the call site uniquely.  We do this by including any lines of code in our instrumentation and
compute a hash based on this traceback.

.. code-block:: python

        ## *******************************************************************************************
        ## START CALLSITE INFORMATION
        ## *******************************************************************************************

        raw_callsite = None

        for line in traceback.format_stack():
            if service_name in line and TEST_PREFIX not in line and INSTRUMENTATION_PREFIX not in line:
                raw_callsite = line
                break

        cs_search = re.compile("File \"(.*)\", line (.*), in")
        callsite = cs_search.search(raw_callsite)

        callsite_file = callsite.group(1)
        callsite_line = callsite.group(2)
        notice("=> callsite_file: " + callsite_file)
        notice("=> callsite_line: " + callsite_line)

        full_traceback = "\n".join(traceback.format_stack())
        full_traceback_hash = hashlib.md5(full_traceback.encode()).hexdigest()
        notice("=> full_traceback_hash: " + full_traceback_hash)

        ## *******************************************************************************************
        ## END CALLSITE INFORMATION
        ## *******************************************************************************************


Potentially Reset State
-----------------------

If this is the first request in a new test execution, we reset the execution index and vector clock state.  Once we have
done that, we initialize a new vector clock and a new execution index and associate it with the request id for this request.

.. code-block:: python

        ## *******************************************************************************************
        ## START CLOCK RESET
        ## *******************************************************************************************

        # Get the request id.
        request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
        notice("request_id_string: " + str(request_id_string))

        # Figure out if this is the first request in a new test execution.
        token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))
        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')):
            response = requests.get(filibuster_new_test_execution_url(filibuster_url, service_name))
            if response is not None:
                response = response.json()
                notice("clock reset response: " + str(response))
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

Update the Vector Clock
-----------------------

We take the incoming vector clock from the thread context and merge it with the current vector clock associated with this
request id.  Then, we advance the clock to account for the current request being issued by the node.

.. code-block:: python

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

Update the Execution Index
--------------------------

Next, we update the execution index associated with the request by pushing on the unique hash of the callsite.

.. code-block:: python

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

        # TODO: need to have add additional fields: module, method, args.
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

Keep Track of the Origin VClock
-------------------------------

Finally, we extract the origin vclock that came in as part of the request from the thread context.

.. code-block:: python

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

Record the Invocation
---------------------

Before we issue the request, we make a request to the Filibuster test server registering the invocation.  We include
the module, method, arguments, callsite information along with the execution index, vector clock, and origin vector
clock.  We parse the response and extract out the generated id from the Filibuster server; this allows us to
update the information about this request when the call completes.

.. code-block:: python

        ## *******************************************************************************************
        ## START RECORD CALL WORK
        ## *******************************************************************************************

        response = None
        parsed_content = None
        generated_id = None

        token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')):
            try:
                # TODO: fix insecure channel hardcode for method
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

                response = requests.put(filibuster_create_url(filibuster_url), json=payload)
            except Exception as e:
                warning("Exception raised (invocation)!")
                print(e, file=sys.stderr)
                return None
            finally:
                notice("Removing instrumentation key for Filibuster.")
                context.detach(token)

        if response is not None:
            try:
                parsed_content = response.json()

                if 'generated_id' in parsed_content:
                    generated_id = parsed_content['generated_id']

            except Exception as e:
                warning("Exception raised (invocation get_json)!")
                print(e, file=sys.stderr)
                return None

        notice("parsed_content: " + str(json.dumps(parsed_content, indent=2)))
        notice("generated_id: " + str(generated_id))

        ## *******************************************************************************************
        ## END RECORD CALL WORK
        ## *******************************************************************************************

Add Metadata to Request
-----------------------

Before we issue the request, we need to tag it with metadata that will be forwarded to the service that receives the request.

.. code-block:: python

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

        notice("metadata after: " + str(metadata))

        ## *******************************************************************************************
        ## END METADATA WORK
        ## *******************************************************************************************

Invocation Completed: Success
-----------------------------

If the request completes successfully -- and we didn't inject a fault, which we will discuss in the following section --
then, we need to notify the Filibuster server so.  Here, we don't include the body of the response when the call is
successfully made, as Filibuster does not require that information for fault injection.

.. code-block:: python

        ## *******************************************************************************************
        ## START RECORD SUCCESSFUL RESPONSE
        ## *******************************************************************************************

        # Remove request from the execution index.
        execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
        request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
        execution_indices_by_request[request_id_string] = execution_index_pop(execution_indices_by_request.get(request_id_string, execution_index_new()))
        _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

        # Notify the Filibuster server that the call succeeded.
        token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')):
            try:
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
                notice("Removing instrumentation key for Filibuster.")
                context.detach(token)

        ## *******************************************************************************************
        ## END RECORD SUCCESSFUL RESPONSE
        ## *******************************************************************************************

Invocation Completed: Exception
-------------------------------

If the request completes with an exception, we notify the Filibuster server of the exceptional response and include the GRPC status code as metadata to the exception.

.. code-block:: python

        ## *******************************************************************************************
        ## START RECORD EXCEPTIONAL RESPONSE
        ## *******************************************************************************************

        # Remove request from the execution index.
        execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
        request_id_string = context.get_value(_FILIBUSTER_REQUEST_ID_KEY)
        execution_indices_by_request[request_id_string] = execution_index_pop(execution_indices_by_request.get(request_id_string, execution_index_new()))
        _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

        # Notify the Filibuster server that the call succeeded.
        token = context.attach(context.set_value(_FILIBUSTER_INSTRUMENTATION_KEY, True))

        if not (os.environ.get('DISABLE_SERVER_COMMUNICATION', '')):
            try:
                payload = {
                    'instrumentation_type': 'invocation_complete',
                    'generated_id': generated_id,
                    'execution_index': execution_index,
                    'vclock': vclock,
                    'exception': {
                        'name': str(err.__class__.__name__),
                        'metadata': {
                            'code': str(err.code()).replace("StatusCode.", "")
                        }
                    }
                }
                requests.post(filibuster_update_url(filibuster_url), json=payload)
            except Exception as e:
                warning("Exception raised recording exceptional response!")
                print(e, file=sys.stderr)
            finally:
                notice("Removing instrumentation key for Filibuster.")
                context.detach(token)

        ## *******************************************************************************************
        ## END RECORD EXCEPTIONAL RESPONSE
        ## *******************************************************************************************
