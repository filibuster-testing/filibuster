Static Analysis
===============

For this, we use a particularly crude static analysis.  We use a basic regexp match on the source
code of each service to look for any code that references a ``grpc.StatusCode`` exception type.
Even if that error isn't directly returned -- we don't rule out dead code where this code is
referenced but not used, we test the code for that error.

Here's the code that returns a json object containing the error.

First, we setup an empty object that says any of the following exceptions are allowed
if the calling method is ``grpc.insecure_channel``.

.. code-block:: python

    instrumentation['grpc'] = {}
    instrumentation['grpc']['pattern'] = "grpc\\.insecure\_channel"
    instrumentation['grpc']['exceptions'] = []

Then, for each service implementation file, we do the following, adding to the list of exceptions
to throw for that service.

.. code-block:: python

    file = open(filename, "r")
    for line in file:
        z = re.match(r'.*code_pb2.(\w*).*', line)
        if z is not None:
            for match in z.groups():
                if match:
                    instrumentation['grpc']['exceptions'].append(
                        {'name': 'grpc._channel._InactiveRpcError',
                         'metadata': {'code': "grpc.StatusCode." + str(match)}})