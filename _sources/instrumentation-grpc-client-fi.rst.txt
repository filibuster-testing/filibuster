Enabling Fault-Injection in the Client
======================================

Now, we look at the modifications made to the client to allow for fault injection.

Parse Invocation Response
-------------------------

We parse the response back from the invocation call to extract the metadata that indicates whether or not we need to
inject a failure or not.  If so, we record this information for use below.

In this example, we extract information about the exception class name, any parameters we need to set on that exception
class (*e.g.*, code), whether or not we should abort the request or sleep during execution.

.. code-block:: python

    if response is not None:
        try:
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

        except Exception as e:
            warning("Exception raised (invocation get_json)!")
            print(e, file=sys.stderr)
            return None

Instantiate Exception
---------------------

We then instantiate the exception class and set the attributes.  Here, we're only concerned with one exception type,
``grpc._channel._InactiveRpcError`` and it's associated code attribute, which is the enumeration ``grpc.StatusCode``.

.. code-block:: python

    ## -------------------------------------------------------------
    ## Start generate exception instance from exception description.
    ## -------------------------------------------------------------

     if exception and exception_code:
        exception_class = eval(exception)
        exception = exception_class(_RPCState(_UNARY_UNARY_INITIAL_DUE, None, None, None, None))
        exception_code = eval(exception_code)
        exception._state.code = exception_code

    ## -------------------------------------------------------------
    ## End generate exception instance from exception description.
    ## -------------------------------------------------------------

Raise and Record
----------------

Finally, we conditionally throw the error and notify the Filibuster of the exception using the previous exceptional
response call.  As that code was included in the previous section, we omit it here.

.. code-block:: python

    if exception and exception_code:
        raise exception