Tutorial
========

This tutorial contains step-by-step instructions for debugging a local application using Filibuster.

In this tutorial, you will:

1. Create three Flask apps that work together to respond "foo bar baz" to a client (one of which contains a bug.)
2. Write functional tests for your Flask apps.
3. Use Filibuster to find the bug.
4. Fix the bug and verify resilience with Filibuster in your local, development environment.

Creating your Flask Apps
------------------------

For this tutorial, we will build our example application in the style of an application in our corpus.  Therefore,
you should first clone the Filibuster corpus.

.. code-block:: shell

    git clone http://github.com/filibuster-testing/filibuster-corpus.git
    cd filibuster-corpus

Flask App Setup
~~~~~~~~~~~~~~~

Navigate to ``examples``.  Then, create the basic structure for your apps:

.. code-block:: shell

    mkdir filibuster-tutorial                                # This is where you'll be putting all files for this tutorial.
    mkdir filibuster-tutorial/services                       # This is where you will write your apps.
    mkdir filibuster-tutorial/functional
    touch filibuster-tutorial/functional/test_foo_bar_baz.py # This is where you will write the functional test for your apps.
    touch filibuster-tutorial/networking.json                # This is where you will write networking information for your apps.
    touch filibuster-tutorial/Makefile                       # This is where you will write the Makefile for your apps.

``filibuster-tutorial/networking.json``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``filibuster-tutorial/networking.json`` specifies networking information including ports, hosts, and timeout
lengths for your apps.  Our corpus has a makefile for starting, waiting for services to come online, and stopping
services that uses this networking information to make requests to each of your services.

In ``filibuster-tutorial/networking.json``, add networking
information for each of our three services (``foo``, ``bar``, and ``baz``) and ``filibuster``:

.. code-block:: javascript

    {
        "foo" : {
          "port": 5000,
          "default-host": "0.0.0.0",
          "timeout-seconds": 6
        },
        "bar" : {
          "port": 5001,
          "default-host": "0.0.0.0",
          "timeout-seconds": 6
        },
        "baz" : {
          "port": 5002,
          "default-host": "0.0.0.0",
          "timeout-seconds": 6
        },
        "filibuster": {
          "port": 5005,
          "default-host": "0.0.0.0",
          "timeout-seconds": 10
        }
    }

``filibuster-tutorial/Makefile``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In ``filibuster-tutorial/Makefile``, add the following to define the services you are implementing, the ports that those
services run on and then include the shared makefile that provides helpers for automatically starting and stopping each
of your services.

.. code-block:: make

    .PHONY: reqs unit functional

    example = filibuster-tutorial
    services = foo bar baz
    ports = 5000 5001 5002
    filibuster-port = 5005

    include ../shared_build_examples.mk

Then create the files you will be working with for this tutorial. These files will specify the three different Flask apps needed
to respond "foo bar baz" to a client. These files include ``python`` files as well as the infrastructure needed to run the apps 
using Filibuster. Run the following:

.. code-block:: shell

    # Loop through the three services that we want to create (and their associated ports) and create initial file structure.
    # Note the services and corresponding ports correspond to filibuster-tutorial/networking.json
    for i in "foo 5000" "bar 5001" "baz 5002"
    do
        set -- $i
        service=$1
        port=$2

        mkdir -p "filibuster-tutorial/services/$service/$service"
        touch "filibuster-tutorial/services/$service/$service/__init__.py"

        # This is where you will will implement your Flask apps.
        touch "filibuster-tutorial/services/$service/$service/app.py"

        # Each service must have a Makefile specifying information for Filibuster.
        makefile="APP=filibuster-tutorial\nSERVICE=$service\nPORT=$port\n\n.PHONY: test reqs\n\ninclude ../../../shared_build_services.mk"

        # Specify information about the service, used by Filibuster.
        echo -e $makefile >> filibuster-tutorial/services/$service/Makefile
    done

Creating the ``baz`` App
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In ``filibuster-tutorial/service/baz/baz/app.py``, add the following code to implement the service.

.. code-block:: python

    from flask import Flask, jsonify
    from werkzeug.exceptions import ServiceUnavailable
    import os
    import sys

    examples_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))))
    sys.path.append(examples_path)

    import helper
    helper = helper.Helper("filibuster-tutorial")

    app = Flask(__name__)

    ## Instrument using filibuster

    sys.path.append(os.path.dirname(examples_path))

    from filibuster.instrumentation.requests import RequestsInstrumentor as FilibusterRequestsInstrumentor
    FilibusterRequestsInstrumentor().instrument(service_name="baz", filibuster_url=helper.get_service_url('filibuster'))

    from filibuster.instrumentation.flask import FlaskInstrumentor as FilibusterFlaskInstrumentor
    FilibusterFlaskInstrumentor().instrument_app(app, service_name="baz", filibuster_url=helper.get_service_url('filibuster'))

    # filibuster requires a health check app to ensure service is running
    @app.route("/health-check", methods=['GET'])
    def baz_health_check():
        return jsonify({ "status": "OK" })

    @app.route("/baz", methods=['GET'])
    def baz():
        return "baz"

    if __name__ == "__main__":
        app.run(port=helper.get_port('baz'), host="0.0.0.0", debug=helper.get_debug())


Note the instrumentation code under ``## Instrument using filibuster``:

.. code-block:: python 

    from filibuster.instrumentation.requests import RequestsInstrumentor as FilibusterRequestsInstrumentor
    FilibusterRequestsInstrumentor().instrument(service_name="baz", filibuster_url=helper.get_service_url('filibuster'))

    from filibuster.instrumentation.flask import FlaskInstrumentor as FilibusterFlaskInstrumentor
    FilibusterFlaskInstrumentor().instrument_app(app, service_name="baz", filibuster_url=helper.get_service_url('filibuster'))

Each service you create will need to include this code, with ``service_name`` updated accordingly. This instrumentation 
code allows Filibuster to instrument both ``flask`` and ``requests``, which in turn allows Filibuster to test
different fault combinations.

Creating the ``bar`` App
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In ``filibuster-tutorial/service/bar/bar/app.py``, add the following code.

.. code-block:: python

    from flask import Flask, jsonify
    from werkzeug.exceptions import ServiceUnavailable
    import requests
    import os
    import sys

    examples_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))))
    sys.path.append(examples_path)

    import helper
    helper = helper.Helper("filibuster-tutorial")

    app = Flask(__name__)

    ## Instrument using filibuster

    sys.path.append(os.path.dirname(examples_path))

    from filibuster.instrumentation.requests import RequestsInstrumentor as FilibusterRequestsInstrumentor
    FilibusterRequestsInstrumentor().instrument(service_name="bar", filibuster_url=helper.get_service_url('filibuster'))

    from filibuster.instrumentation.flask import FlaskInstrumentor as FilibusterFlaskInstrumentor
    FilibusterFlaskInstrumentor().instrument_app(app, service_name="bar", filibuster_url=helper.get_service_url('filibuster'))

    # filibuster requires a health check app to ensure service is running
    @app.route("/health-check", methods=['GET'])
    def bar_health_check():
        return jsonify({ "status": "OK" })

    @app.route("/bar/baz", methods=['GET'])
    def bar():
        try:
            response = requests.get("{}/baz".format(helper.get_service_url('baz')), timeout=helper.get_timeout('baz'))
        except requests.exceptions.ConnectionError:
            raise ServiceUnavailable("The baz service is unavailable.")
        except requests.exceptions.Timeout:
            raise ServiceUnavailable("The baz service timed out.")

        if response.status_code != 200:
            raise ServiceUnavailable("The baz service is malfunctioning.")

        return "bar " + response.text

    if __name__ == "__main__":
        app.run(port=helper.get_port('bar'), host="0.0.0.0", debug=helper.get_debug())


Creating the ``foo`` App
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In ``filibuster-tutorial/service/foo/foo/app.py``, add the following code.

.. code-block:: python

    from flask import Flask, jsonify
    from werkzeug.exceptions import ServiceUnavailable
    import requests
    import os
    import sys

    examples_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))))
    sys.path.append(examples_path)

    import helper
    helper = helper.Helper("filibuster-tutorial")

    app = Flask(__name__)

    ## Start OpenTelemetry Configuration

    from opentelemetry import trace
    from opentelemetry.exporter import jaeger
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchExportSpanProcessor
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    trace.set_tracer_provider(TracerProvider())

    jaeger_exporter = jaeger.JaegerSpanExporter(
        service_name="foo",
        agent_host_name=helper.jaeger_agent_host_name(),
        agent_port=helper.jaeger_agent_port()
    )

    trace.get_tracer_provider().add_span_processor(
        BatchExportSpanProcessor(jaeger_exporter)
    )

    tracer = trace.get_tracer(__name__)

    ## Instrument using filibuster

    sys.path.append(os.path.dirname(examples_path))
    from filibuster.instrumentation.requests import RequestsInstrumentor as FilibusterRequestsInstrumentor

    FilibusterRequestsInstrumentor().instrument(service_name="foo",
                                                filibuster_url=helper.get_service_url('filibuster'))

    from filibuster.instrumentation.flask import FlaskInstrumentor as FilibusterFlaskInstrumentor

    FilibusterFlaskInstrumentor().instrument_app(app, service_name="foo",
                                                filibuster_url=helper.get_service_url('filibuster'))

    RequestsInstrumentor().instrument()

    # filibuster requires a health check app to ensure service is running
    @app.route("/health-check", methods=['GET'])
    def foo_health_check():
        return jsonify({ "status": "OK" })

    @app.route("/foo/bar/baz", methods=['GET'])
    def foo():
        try:
            response = requests.get("{}/bar/baz".format(helper.get_service_url('bar')), timeout=helper.get_timeout('bar'))
        except requests.exceptions.Timeout:
            raise ServiceUnavailable("The bar service timed out.")

        if response.status_code != 200:
            raise ServiceUnavailable("The bar service is malfunctioning.")

        return "foo " + response.text

    if __name__ == "__main__":
        app.run(port=helper.get_port('foo'), host="0.0.0.0", debug=helper.get_debug())

Functional Testing
------------------

Now that your Flask apps are created, write a functional test. This test will ensure that our three apps work 
together to return "foo bar baz" to a client. In ``filibuster-tutorial/functional/test_foo_bar_baz.py``, add 
the following code.

.. code-block:: python

    import requests
    import os
    import sys

    examples_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    sys.path.append(examples_path)

    import helper
    helper = helper.Helper("filibuster-tutorial")

    # Note that tests should be prefixed with test_functional for filibuster compatibility
    def test_functional_foo_bar_baz():
        response = requests.get("{}/foo/bar/baz".format(helper.get_service_url('foo')), timeout=helper.get_timeout('foo'))
        assert response.status_code == 200 and response.text == "foo bar baz"

    if __name__ == "__main__":
        test_functional_foo_bar_baz()

Now, verify that the functional test passes:

``cd filibuster-tutorial; make local-functional-via-filibuster-server``

You should get something like the following output:

.. code-block:: shell

    [FILIBUSTER] [NOTICE]: Running test test_functional_foo_bar_baz
    [FILIBUSTER] [INFO]: Running initial non-failing execution (test 1) &ltmodule 'test_foo_bar_baz' from '/Users/filibuster-user/nufilibuster/examples/filibuster-tutorial/functional/test_foo_bar_baz.py'&gt
    [FILIBUSTER] [INFO]: [DONE] Running initial non-failing execution (test 1)
    [FILIBUSTER] [NOTICE]: Completed testing test_functional_foo_bar_baz
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Test executions actually ran:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 1
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: None.
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Test executions actually pruned:
    [FILIBUSTER] [INFO]: None.
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Number of tests attempted: 1
    [FILIBUSTER] [INFO]: Number of test executions ran: 1
    [FILIBUSTER] [INFO]: Test executions pruned with only dynamic pruning: 0
    [FILIBUSTER] [INFO]: Total tests: 1
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Time elapsed: 0.134443998336792 seconds.


Finding the Bug
---------------

Now, we will use ``filibuster`` to inject faults.

First we need to update our test a bit. Instead of only ensuring that our three apps successfully return "foo bar baz" to a client,
we also want to allow the request to ``foo`` to fail gracefully. To ensure the request fails only when it should, we should use the
``helper`` module. ``helper``'s ``fault_injected()`` tells us whether:

* a fault has been injected, meaning ``response.status_code`` should be a failure status code
* or not, meaning ``response.status_code`` should be ``200`` and "foo bar baz" should be returned

Adjust ``filibuster-tutorial/functional/test_foo_bar_baz.py`` to incorporate ``helper``'s ``fault_injected()`` so that it matches the following:

.. code-block:: python

    import requests
    import os
    import sys

    examples_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    sys.path.append(examples_path)

    import helper
    helper = helper.Helper("filibuster-tutorial")

    # Note that tests should be prefixed with test_functional for filibuster compatibility
    def test_functional_foo_bar_baz():
        response = requests.get("{}/foo/bar/baz".format(helper.get_service_url('foo')), timeout=helper.get_timeout('foo'))
        if response.status_code == 200:
            assert (not helper.fault_injected()) and response.text == "foo bar baz"
        else:
            assert helper.fault_injected() and response.status_code in [503, 404]

    if __name__ == "__main__":
        test_functional_foo_bar_baz()

Run the following:

``cd filibuster-tutorial; make local-functional-with-fault-injection-bypass-stop-start``

You should get the following output:

.. code-block:: shell

    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 8
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 0: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]: =====================================================================================
    127.0.0.1 - - [18/May/2021 17:02:25] "GET /filibuster/new-test-execution/foo HTTP/1.1" 200 -
    127.0.0.1 - - [18/May/2021 17:02:25] "PUT /filibuster/create HTTP/1.1" 200 -
    127.0.0.1 - - [18/May/2021 17:02:25] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [18/May/2021 17:02:25] "POST /filibuster/update HTTP/1.1" 200 -
    Traceback (most recent call last):
      File "/Users/filibuster-user/nufilibuster/examples/filibuster-tutorial/functional/test_foo_bar_baz.py", line 20, in <module>
        test_functional_foo_bar_baz()
      File "/Users/filibuster-user/nufilibuster/examples/filibuster-tutorial/functional/test_foo_bar_baz.py", line 17, in test_functional_foo_bar_baz
        assert helper.fault_injected() and response.status_code in [503, 404]
    AssertionError

Fixing the Bug
--------------

Clearly there is a bug! To fix the bug, we see that a Connection Error caused a failed assertion. We forgot to handle the case where ``foo``'s request to ``bar`` fails due to a ``ConnectionError``. In ``filibuster-tutorial/service/foo/foo/app.py``'s ``foo`` method, add the following code right after ``foo`` handles the timeout.

.. code-block:: python

    except requests.exceptions.ConnectionError:
        raise ServiceUnavailable("The bar service is unavailable.")

Testing the Fix
---------------

Now, verify that the bug is fixed. Rerun just the specific bug we found using (note the ``RUN_COUNTEREXAMPLE`` flag which allows us to rerun just the failed test):

``cd filibuster-tutorial; RUN_COUNTEREXAMPLE=true make local-functional-with-fault-injection``

The previously failed test should pass:

.. code-block:: shell

    [FILIBUSTER] [NOTICE]: Completed testing test_functional_foo_bar_baz
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Test executions actually ran:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 1
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 0: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Test executions actually pruned:
    [FILIBUSTER] [INFO]: None.
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Number of tests attempted: 1
    [FILIBUSTER] [INFO]: Number of test executions ran: 1
    [FILIBUSTER] [INFO]: Test executions pruned with only dynamic pruning: 0
    [FILIBUSTER] [INFO]: Total tests: 1
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Time elapsed: 2.2366678714752197 seconds.

Lastly, run all of the ``filibuster`` tests again to verify fault tolerance:

``cd filibuster-tutorial; make local-functional-with-fault-injection-bypass-start-stop``

Now, all tests should pass! There should be a total of 8 tests generated by ``filibuster``:

.. code-block:: shell

    [FILIBUSTER] [NOTICE]: Completed testing test_functional_foo_bar_baz
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Test executions actually ran:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 1
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 1: args: ['http://0.0.0.0:5002/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1], ["19341e59858927e30ff947bd62841716", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1, 'bar': 1}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: None.
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 2
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 1: args: ['http://0.0.0.0:5002/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1], ["19341e59858927e30ff947bd62841716", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1, 'bar': 1}
    [FILIBUSTER] [INFO]: * Failed with metadata: [('return_value', {'status_code': 500})]
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 1: [('return_value', {'status_code': 500})]
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 3
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 1: args: ['http://0.0.0.0:5002/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1], ["19341e59858927e30ff947bd62841716", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1, 'bar': 1}
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.Timeout'}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 1: {'name': 'requests.exceptions.Timeout'}
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 4
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 1: args: ['http://0.0.0.0:5002/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1], ["19341e59858927e30ff947bd62841716", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1, 'bar': 1}
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 1: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 5
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]: * Failed with metadata: [('return_value', {'status_code': 500})]
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 0: [('return_value', {'status_code': 500})]
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 6
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.Timeout'}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 0: {'name': 'requests.exceptions.Timeout'}
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 7
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 0: {'name': 'requests.exceptions.ConnectionError'}
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Test executions actually pruned:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 1
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: 0: args: ['http://0.0.0.0:5001/bar/baz'] kwargs: {}
    [FILIBUSTER] [INFO]:   execution_index: [["82c72a199994ec4617027843481fafce", 1]]
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]: * Failed with metadata: [('return_value', {'status_code': 503})]
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: 0: [('return_value', {'status_code': 503})]
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Number of tests attempted: 7
    [FILIBUSTER] [INFO]: Number of test executions ran: 7
    [FILIBUSTER] [INFO]: Test executions pruned with only dynamic pruning: 1
    [FILIBUSTER] [INFO]: Total tests: 8
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Time elapsed: 1.0523009300231934 seconds.

Integrating Docker
------------------

Once your application runs with ``filibuster`` locally, by adding just a few files you can make run your application using Docker. Add and populate some of the files:

.. code-block:: shell

    touch filibuster-tutorial/docker-compose.yaml
    reqs="Flask==1.0.0\npytest\nrequests\nopentelemetry-sdk==1.0.0rc1\nopentelemetry-api==1.0.0rc1\nopentelemetry-instrumentation==0.18b0\nopentelemetry-exporter-jaeger==1.0.0rc1\nopentelemetry-instrumentation-flask==0.18b1\nopentelemetry-instrumentation-requests==0.18b1\ndocker\nkubernetes"
    echo -e $reqs >> filibuster-tutorial/base_requirements.txt
    for service in foo bar baz
    do
        # Each service must have a Dockerfile.
        dockerfile="FROM filibuster-tutorial:configuration\n\nWORKDIR /nufilibuster/examples/filibuster-tutorial/services/$service\n\nCOPY . /nufilibuster/examples/filibuster-tutorial/services/$service\n\nENTRYPOINT [ \"python3\" ]\nCMD [ \"-m\", \"$service.app\" ] "
        echo -e $dockerfile >> filibuster-tutorial/services/$service/Dockerfile
    done

In ``filibuster-tutorial/docker-compose.yaml`` add:

.. code-block:: dockerfile

    version: '3'

    services:
        foo:
            image: ${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/filibuster-tutorial:foo
            build:
                context: './services/foo/'
                dockerfile: './Dockerfile'
            ports:
                - "5000:5000"
        bar:
            image: ${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/filibuster-tutorial:bar
            build:
                context: './services/bar'
                dockerfile: './Dockerfile'
            ports:
                - "5001:5001"
        baz:
            image: ${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/filibuster-tutorial:baz
            build:
                context: './services/baz'
                dockerfile: './Dockerfile'
            ports:
                - "5002:5002"

Now you can run things using Docker. Try running ``cd filibuster-tutorial; make docker-functional-with-fault-injection-bypass-start-stop``.


Integrating Minikube
--------------------
Finally, once your application runs with ``filibuster`` using docker, you can easily make it run using Minikube. Define service and deployment files as follows for each of the services:

.. code-block:: shell

    # Note the services and corresponding ports correspond to filibuster-tutorial/networking.json
    for i in "foo 5000" "bar 5001" "baz 5002"
    do
        set -- $i
        service=$1
        port=$2

        serviceyaml="apiVersion: v1\nkind: Service\nmetadata:\n  name: $service\nspec:\n  type: NodePort\n  ports:\n    - name: \"$port\"\n      port: $port\n      targetPort: $port\n  selector:\n    io.kompose.service: $service\n"
        deploymentyaml="apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  labels:\n    io.kompose.service: $service\n  name: $service\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      io.kompose.service: $service\n  template:\n    metadata:\n      labels:\n        io.kompose.service: $service\n    spec:\n      containers:\n        - image: \${AWS_ACCOUNT_ID}.dkr.ecr.\${REGION}.amazonaws.com/filibuster-tutorial:$service\n          name: $service\n          ports:\n          - containerPort: $port\n          imagePullPolicy: IfNotPresent\n      restartPolicy: Always\n      imagePullSecrets:\n        - name: regcred"

        mkdir filibuster-tutorial/services/$service/k8s
        echo -e "$serviceyaml" >> filibuster-tutorial/services/$service/k8s/service.yaml
        echo -e "$deploymentyaml" >> filibuster-tutorial/services/$service/k8s/deployment.yaml
    done
    env="example=filibuster-tutorial\nservices=\"foo bar baz\""
    echo -e $env >> filibuster-tutorial/env.txt

Now you can run things using Minikube. Try running ``cd filibuster-tutorial; make minikube-functional-with-fault-injection-bypass-start-stop``.
