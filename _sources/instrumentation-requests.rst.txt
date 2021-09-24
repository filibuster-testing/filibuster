Instrumentation Example: Requests
=================================

Now, we discuss the modifications made to the ``opentelemetry-instrumentation-requests`` library to allow us to modify outgoing calls to include the required metadata, support fault injection, and notify the Filibuster server of remote calls and their responses.

We assume you read the previous section on the modifications to Flask.

Metadata Reception
------------------

First, we only perform instrumentation if instrumentation is enabled for this request -- we don't want to instrument the calls to the Filibuster server.

.. code-block:: python

    if not context.get_value(_FILIBUSTER_INSTRUMENTATION_KEY):

Next, we have to compute a hash for this request based on the traceback to uniquely identify this request.  To do this, we use the service name and part of the traceback and compute a MD5.  This doesn't have to be cryptographically secure but just unique enough for this service.  We omit lines from the traceback that are calls within the instrumentation code, therefore only including lines in the application code.

.. code-block:: python

    raw_callsite = None

    for line in traceback.format_stack():
        if service_name in line and TEST_PREFIX not in line and INSTRUMENTATION_PREFIX not in line:
            raw_callsite = line
            break

    cs_search = re.compile("File \"(.*)\", line (.*), in")
    callsite = cs_search.search(raw_callsite)

    callsite_file = callsite.group(1)
    callsite_line = callsite.group(2)

    full_traceback = "\n".join(traceback.format_stack())
    full_traceback_hash = hashlib.md5(full_traceback.encode()).hexdigest()

Next, we extract the vclock from the thread context -- where we set the incoming vclock in the Flask instrumentation -- and increment the vclock using our service name.  This is because we are inside of the ``request``s instrumentation and therefore about to issue a request to an external service: we are taking an action that requires incrementing the vclock.

.. code-block:: python

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


We also need to advance the execution index to account for the service issuing a remote call to another service.

To do this, we use the call site hash that was generated in the example above and combine it with the module, method and arguments that were invoked.  This combined hash is then added to the execution index and set as the current execution index.

When this call returns, we will pop this from the execution index (this code is omitted for brevity and handled in the code that records the response below.    )

.. code-block:: python

    # Maintain the execution index for each request.
    incoming_execution_index_string = context.get_value(_FILIBUSTER_EXECUTION_INDEX_KEY)

    if incoming_execution_index_string is not None:
        incoming_execution_index = execution_index_fromstring(incoming_execution_index_string)
    else:
        execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
        incoming_execution_index = local_execution_index

    execution_index_hash = unique_request_hash([full_traceback_hash, 'requests', method, json.dumps(url)])

    execution_indices_by_request = _filibuster_global_context_get_value(_FILIBUSTER_EI_BY_REQUEST_KEY)
    execution_indices_by_request[request_id_string] = execution_index_push(execution_index_hash, incoming_execution_index)
    execution_index = execution_indices_by_request[request_id_string]
    _filibuster_global_context_set_value(_FILIBUSTER_EI_BY_REQUEST_KEY, execution_indices_by_request)

Finally, we have to set the incoming vclock as our origin vclock.  If we don't have an incoming vclock, it's the first request in the microservice application and we use a new vclock.

.. code-block:: python

    incoming_origin_vclock_string = context.get_value(_FILIBUSTER_ORIGIN_VCLOCK_KEY)

    # This isn't used in the record_call, but just propagated through the headers in the subsequent request.
    origin_vclock = vclock

    # Record call with the incoming origin clock and advanced clock.
    if incoming_origin_vclock_string is not None:
        incoming_origin_vclock = vclock_fromstring(incoming_origin_vclock_string)
    else:
        incoming_origin_vclock = vclock_new()

Now, we can make the call to the Filibuster server.  We elide the details of making a normal JSON call to the Filibuster server, which is covered in our API documentation.  We encode the execution index as string, as covered in the Data Types section of our API documentation.

.. code-block:: python

    response = _record_call(self,
                            method,
                            [url],
                            callsite_file,
                            callsite_line,
                            full_traceback_hash,
                            vclock,
                            incoming_origin_vclock,
                            execution_index_tostring(execution_index),
                            kwargs)


Fault Injection
---------------

If the Filibuster server notifies us that we have to inject a failure for this request, we will receive information in the response about what precise error to inject along with metadata describing how that fault should be injected.  We will omit the detailed information that describes parsing this response and injecting the actual failure, as it's instrumentation specific and fairly straightforward.

For demonstration purposes, we will show sample code used in the ``requests`` instrumentation about how we might parse this response and handle it.  In this code, we use the response from the Filibuster server to extract either the exception we should inject, or the changes we should make to the response returned to the user, from the Filibuster server.

.. code-block:: python

    if response is not None:
        if 'generated_id' in response:
            generated_id = response['generated_id']

        if 'forced_exception' in response:
            exception = response['forced_exception']['name']

            if 'metadata' in response['forced_exception'] and response['forced_exception']['metadata'] is not None:
                exception_metadata = response['forced_exception']['metadata']
                if 'abort' in exception_metadata and exception_metadata['abort'] is not None:
                    should_abort = exception_metadata['abort']
                if 'sleep' in exception_metadata and exception_metadata['sleep'] is not None:
                    should_sleep_interval = exception_metadata['sleep']

            should_inject_fault = True

        if 'failure_metadata' in response:
            if 'return_value' in response['failure_metadata'] and 'status_code' in response['failure_metadata']['return_value']:
                status_code = response['failure_metadata']['return_value']['status_code']
                should_inject_fault = True

These booleans (or other values), which are set based on the response from the Filibuster server, allow us to either make a request to the remote service (in the event of no fault injection), modify the response (in the case of value-based fault injection), or throw an exception (in the case of exception-based fault injection.)

As you can imagine, we made the following adjustments in the ``opentelemetry`` code to respect these values.  If we need to throw an exception, we skip the remote call and throw; if we need to modify the response, we skip the remote call, directly instantiate the response class and set the attributes accordingly before returning the response to the user.  We refer the reader to the implementation of our ``requests`` instrumentation; however, these modifications are rather straightforward.

Metadata Propagation
--------------------

In terms of metadata propagation, we modified the calls that are made to the remote service to include additional headers containing the required instrumentation metadata.  This was a simple modification to include a dictionary of headers containing values taken from the dictionary stored in the thread context.

Here, you will find an example of the additional headers provided to each call.  These headers are the ones discussed in our overview of how our instrumentation needs to propagate forward.

As HTTP headers require values that are strings, we encode these values as strings using a JSON to string serializer.

.. code-block:: python

    {
        'X-Filibuster-Generated-Id': str(generated_id),
        'X-Filibuster-VClock': vclock_tostring(vclock),
        'X-Filibuster-Origin-VClock': vclock_tostring(origin_vclock),
        'X-Filibuster-Execution-Index': execution_index_tostring(execution_index)
    }

Response Notification
---------------------

After the call completes (or, is potentially aborted based on fault injection), we have to notify the Filibuster server of the response.  We do this by extending the existing ``opentelemery`` instrumentation to notify the Filibuster server of success or failure, based on the value set above.

In the event of success, we notify Filibuster using the ``_record_successful_response`` callback; in the event of failure, we use the ``_record_exceptional_response`` callback.

Example: Successful Response Payload
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the response was successful -- either because Filibuster didn't inject a fault or Filibuster modified the response to return an error code, this payload includes the return value including the class of the response object and the attributes and values each attribute had to indicate the error.  It sets the ``instrumentation_type`` as ``invocation_complete`` indicating this request is the response of a remote call.  It also includes the associated vclock and execution index of the remote call.

.. code-block:: python

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

We omit the implementation detail of this method for brevity; as you can imagine, it's a call to the ``requests`` library where we set the context appropriately to ensure we do not instrument this call (as it's made to the Filibuster server, where we do not want to perform fault injection.)

Example: Exceptional Response Payload
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the response was unsuccessful because it threw an exception (by fault injection), this response includes the fully qualified name of the exception as a string, the vector clock associated with the request, and the execution index associate with this request.

.. code-block:: python

   payload = {
        'instrumentation_type': 'invocation_complete',
        'generated_id': generated_id,
        'execution_index': execution_index,
        'vclock': vclock,
        'exception': parsed_exception_string
   }

Again, we omit the implementation detail of this method for brevity; as you can imagine, it's a call to the requests library where we set the context appropriately to ensure we do not instrument this call (as it's made to the Filibuster server, where we do not want to perform fault injection.)
