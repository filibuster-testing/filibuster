Java Instrumentors
==================

For developers, Filibuster provides a client and server instrumentor library that can be used to ease the task of instrumenting libraries for use with Filibuster.

Client Instrumentor
-------------------

The Filibuster client instrumentor is used to setup the required metadata and record the request lifecycle of an outgoing request.  The instrumentor automatically maintains metadata, such as the vector clocks and execution indexes associated with this request, and notifies the Filibuster server of the request and it's outcome.

The client instrumentor should be instantiated with the service name and a boolean indicating whether or not the Filibuster server should be contacted or not (for testing.)  Once instantiated, the service should invoke the ``prepareForInvocation`` method, which will setup required metadata: the vector clocks and execution indexes that should be associated with this request.

Here is an example:

.. code-block:: java

    FilibusterClientInstrumentor filibusterClientInstrumentor = new FilibusterClientInstrumentor(
            serviceName,
            shouldCommunicateWithServer
    );
    filibusterClientInstrumentor.prepareForInvocation();

Next, before the request is performed by the underlying library, the ``beforeInvocation`` method should be invoked with the module/class name, method name, and serializable arguments.  These arguments are never deserialized by the Filibuster server, so the serialization format can be client specific; however, they should be unique enough to distinguish this call site from another.  In our case, we can use the destination URL and JSON payload of the request.

.. code-block:: java

    filibusterClientInstrumentor.beforeInvocation(module, method, args);

Next, the client needs to notify the Filibuster server whether or not the call completed succesfully or with an exception being thrown at the callsite.  To do this, the client instrumentor provides two methods.

First, if the call completes successfully, the ``afterInvocationComplete`` method can be used to provide the resulting class name (of the response object) along with the status code that was returned.

.. code-block:: java

    filibusterClientInstrumentor.afterInvocationComplete(className, statusCode);

If the call throws, the client needs to notify the Filibuster server with the exception that is thrown.  To do this, the ``afterInvocationWithException`` method can be used, providing the exception that was thrown.

.. code-block:: java

    filibusterClientInstrumentor.afterInvocationWithException(exception);

Fault Injection
~~~~~~~~~~~~~~~

After the ``beforeInvocation`` method is invoked, the ``getFailureMetadata`` and ``getForcedException`` methods can be used to determine if the client that is being instrumented should throw an exception or alter the response to indicate failure.  Both of these functions return a JSON object whose contents should be interpreted by the client itself.  We refer the reader to the section :ref:`HTTP API: Create` for details on what these fields these objects contain and how they should be interpreted.

It is the clients responsibility to ensure that when injecting faults that one of either the ``afterInvocationComplete`` or ``afterInvocationWithException`` methods are invoked to record the final response.

Server Instrumentor
-------------------

The Filibuster server instrumentor is used to setup required metadata and notify the Filibuster server of an incoming request.  The instrumentor automatically sends the ``request_received`` message to the Filibuster server and stores metadata in a global metadata context that is then used by the client instrumentor.

The server instrumentor should be instantiated with the service name, a boolean indicating whether or not the Filibuster server should be contacted or not (for testing) and the incoming metadata for the request.  The metadata must be provided explicitly to the server instrumentor: this metadata will be stored differently depending on the transport mechanism (*e.g.,* headers for HTTP requests, metadata for GRPC requests.)

Here is an example:

.. code-block:: java

    FilibusterServerInstrumentor filibusterServerInstrumentor = new FilibusterServerInstrumentor(
            String serviceName,
            boolean shouldCommunicateWithFilibusterServer,
            String requestId,
            String generatedId,
            String vectorClock,
            String originVectorClock,
            String executionIndex
    );

In our implementation for Armeria's ``WebClient``, we use the incoming request headers as storage of the metadata and pass them to the instrumentor as follows.

.. code-block:: java

    FilibusterServerInstrumentor filibusterServerInstrumentor = new FilibusterServerInstrumentor(
            serviceName,
            shouldCommunicateWithServer(),
            req.headers().get("X-Filibuster-Request-Id", Helper.generateNewRequestId().toString()),
            req.headers().get("X-Filibuster-Generated-Id"),
            req.headers().get("X-Filibuster-VClock"),
            req.headers().get("X-Filibuster-Origin-VClock"),
            req.headers().get("X-Filibuster-Execution-Index")
    );

Finally, before delegating the request to the underlying library, invoke the ``beforeInvocation`` method to perform the required instrumentation call to the Filibuster server.

.. code-block:: java

    filibusterServerInstrumentor.beforeInvocation();
