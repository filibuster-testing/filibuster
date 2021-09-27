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

Create the basic structure for your apps:

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

    ## Instrument using filibuster

    sys.path.append(os.path.dirname(examples_path))

    from filibuster.instrumentation.requests import RequestsInstrumentor as FilibusterRequestsInstrumentor
    FilibusterRequestsInstrumentor().instrument(service_name="foo", filibuster_url=helper.get_service_url('filibuster'))

    from filibuster.instrumentation.flask import FlaskInstrumentor as FilibusterFlaskInstrumentor
    FilibusterFlaskInstrumentor().instrument_app(app, service_name="foo", filibuster_url=helper.get_service_url('filibuster'))

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

    #!/usr/bin/env python

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


Now, let's verify that the functional test passes.  First, let's start the required services.

.. code-block:: shell

    cd filibuster-tutorial
    make local-start

Now, run the functional test.

.. code-block:: shell

    chmod 755 functionaal/test_foo_bar_baz.py
    ./functional/test_foo_bar_baz.py

At this point, your test should pass.  If it doesn't, please make sure your services were implemented correctly as
described above, and that you have started the services using the ``local-start`` make target.

Finding the Bug
~~~~~~~~~~~~~~~

Let's use Filibuster to identify bugs using fault injection.  First, we can use Filibuster to identify bugs using a
default set of faults for the application.  We can do that using the Filibuster CLI tool.

First, install Filibuster.

.. code-block:: shell

    pip install filibuster

Next, provide the Filibuster CLI tool with the path to the functional test.  If we don't specify what faults to inject,
Filibuster will use test default set of common faults.

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py

We should see output like the following:

.. code-block:: shell

     * Serving Flask app "filibuster.server" (lazy loading)
     * Environment: production
       WARNING: Do not use the development server in a production environment.
       Use a production WSGI server instead.
     * Debug mode: off
     * Running on all addresses.
       WARNING: This is a development server. Do not use it in a production deployment.
     * Running on http://100.68.79.169:5005/ (Press CTRL+C to quit)
    127.0.0.1 - - [27/Sep/2021 10:35:05] "GET /health-check HTTP/1.1" 200 -
    [FILIBUSTER] [NOTICE]: Running test ./functional/test_foo_bar_baz.py
    [FILIBUSTER] [INFO]: Running initial non-failing execution (test 1) ./functional/test_foo_bar_baz.py
    127.0.0.1 - - [27/Sep/2021 10:35:05] "GET /filibuster/new-test-execution/foo HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "PUT /filibuster/create HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "GET /filibuster/new-test-execution/bar HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "PUT /filibuster/create HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    [FILIBUSTER] [INFO]: [DONE] Running initial non-failing execution (test 1)
    [FILIBUSTER] [INFO]: Running test 2
    [FILIBUSTER] [INFO]: Total tests pruned so far: 0
    [FILIBUSTER] [INFO]: Total tests remaining: 9
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 2
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: gen_id: 0
    [FILIBUSTER] [INFO]:   module: requests
    [FILIBUSTER] [INFO]:   method: get
    [FILIBUSTER] [INFO]:   args: ['5001/bar/baz']
    [FILIBUSTER] [INFO]:   kwargs: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   execution_index: [["b13f73ac8ced79cb093a638972923de1", 1]]
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: gen_id: 1
    [FILIBUSTER] [INFO]:   module: requests
    [FILIBUSTER] [INFO]:   method: get
    [FILIBUSTER] [INFO]:   args: ['5002/baz']
    [FILIBUSTER] [INFO]:   kwargs: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1, 'bar': 1}
    [FILIBUSTER] [INFO]:   origin_vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   execution_index: [["b13f73ac8ced79cb093a638972923de1", 1], ["e654c4b77587b601e5a5767a82a27f45", 1]]
    [FILIBUSTER] [INFO]: * Failed with metadata: [('return_value', {'status_code': '503'})]
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: [["b13f73ac8ced79cb093a638972923de1", 1], ["e654c4b77587b601e5a5767a82a27f45", 1]]: [('return_value', {'status_code': '503'})]
    [FILIBUSTER] [INFO]: =====================================================================================
    127.0.0.1 - - [27/Sep/2021 10:35:05] "GET /filibuster/new-test-execution/foo HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "PUT /filibuster/create HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "GET /filibuster/new-test-execution/bar HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "PUT /filibuster/create HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:35:05] "POST /filibuster/update HTTP/1.1" 200 -
    Traceback (most recent call last):
      File "/private/tmp/filibuster-corpus/filibuster-tutorial/./functional/test_foo_bar_baz.py", line 19, in <module>
        test_functional_foo_bar_baz()
      File "/private/tmp/filibuster-corpus/filibuster-tutorial/./functional/test_foo_bar_baz.py", line 16, in test_functional_foo_bar_baz
        assert response.status_code == 200 and response.text == "foo bar baz"
    AssertionError
    [FILIBUSTER] [FAIL]: Test failed; counterexample file written: counterexample.json

What we see here is an assertion failure: the status code and text do not match when a fault was injected.  We can see
from further back in the output the precise fault that was injected.

.. code-block:: shell

    [FILIBUSTER] [INFO]: gen_id: 1
    [FILIBUSTER] [INFO]:   module: requests
    [FILIBUSTER] [INFO]:   method: get
    [FILIBUSTER] [INFO]:   args: ['5002/baz']
    [FILIBUSTER] [INFO]:   kwargs: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1, 'bar': 1}
    [FILIBUSTER] [INFO]:   origin_vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   execution_index: [["b13f73ac8ced79cb093a638972923de1", 1], ["e654c4b77587b601e5a5767a82a27f45", 1]]
    [FILIBUSTER] [INFO]: * Failed with metadata: [('return_value', {'status_code': '503'})]

Here, we see that the request from ``bar`` to ``baz`` was failed with a 503 Service Unavailable response.  This response caused the entire request to no longer return a 200 OK containing "foo bar baz".

If we want to re-run that precise test, we can using the counterexample that Filibuster provided.

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py --counterexample-file counterexample.json

Updating our Functional Test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to keep testing, we need to update our assertions in our test to reflect the behavior we expect under failure.

Instead of only ensuring that our three apps successfully return "foo bar baz" to a client, we also want to allow the
request to ``foo`` to fail gracefully.  To ensure the request fails only when it should, we should use the
``filibuster.assertions`` module. ``filibuster.assertions``'s ``was_fault_injected()`` tells us whether:

* a fault has been injected, meaning ``response.status_code`` should be a failure status code
* or not, meaning ``response.status_code`` should be ``200`` and "foo bar baz" should be returned

Adjust ``filibuster-tutorial/functional/test_foo_bar_baz.py`` to incorporate ``filibuster.assertions``'s ``was_fault_injected()`` so that it matches the following:

.. code-block:: python

    #!/usr/bin/env python

    import requests
    import os
    import sys

    from filibuster.assertions import was_fault_injected

    examples_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    sys.path.append(examples_path)

    import helper
    helper = helper.Helper("filibuster-tutorial")

    # Note that tests should be prefixed with test_functional for filibuster compatibility
    def test_functional_foo_bar_baz():
        response = requests.get("{}/foo/bar/baz".format(helper.get_service_url('foo')), timeout=helper.get_timeout('foo'))
        if response.status_code == 200:
            assert (not was_fault_injected()) and response.text == "foo bar baz"
        else:
            assert was_fault_injected() and response.status_code in [503, 404]

    if __name__ == "__main__":
        test_functional_foo_bar_baz()

Filibuster's assertions module also provides a more granular assertion: ``was_fault_injected_on(service_name)`` that can
be used to write more precise assertions.

Let's re-run the counterexample; with our updated assertion, the test should now pass!

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py --counterexample-file counterexample.json

Now, we can run Filibuster again and test for the whole default set of failures as well.

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py

After 10 tests, we run into another failure.

.. code-block:: shell

    [FILIBUSTER] [INFO]: Running test 11
    [FILIBUSTER] [INFO]: Total tests pruned so far: 1
    [FILIBUSTER] [INFO]: Total tests remaining: 0
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: =====================================================================================
    [FILIBUSTER] [INFO]: Test number: 11
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: gen_id: 0
    [FILIBUSTER] [INFO]:   module: requests
    [FILIBUSTER] [INFO]:   method: get
    [FILIBUSTER] [INFO]:   args: ['5001/bar/baz']
    [FILIBUSTER] [INFO]:   kwargs: {}
    [FILIBUSTER] [INFO]:   vclock: {'foo': 1}
    [FILIBUSTER] [INFO]:   origin_vclock: {}
    [FILIBUSTER] [INFO]:   execution_index: [["b13f73ac8ced79cb093a638972923de1", 1]]
    [FILIBUSTER] [INFO]: * Failed with exception: {'name': 'requests.exceptions.ConnectionError', 'metadata': {}}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Failures for this execution:
    [FILIBUSTER] [INFO]: [["b13f73ac8ced79cb093a638972923de1", 1]]: {'name': 'requests.exceptions.ConnectionError', 'metadata': {}}
    [FILIBUSTER] [INFO]: =====================================================================================
    127.0.0.1 - - [27/Sep/2021 10:55:54] "GET /filibuster/new-test-execution/foo HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:55:54] "PUT /filibuster/create HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:55:54] "POST /filibuster/update HTTP/1.1" 200 -
    127.0.0.1 - - [27/Sep/2021 10:55:54] "GET /fault-injected HTTP/1.1" 200 -
    Traceback (most recent call last):
      File "/private/tmp/filibuster-corpus/filibuster-tutorial/./functional/test_foo_bar_baz.py", line 24, in <module>
        test_functional_foo_bar_baz()
      File "/private/tmp/filibuster-corpus/filibuster-tutorial/./functional/test_foo_bar_baz.py", line 21, in test_functional_foo_bar_baz
        assert was_fault_injected() and response.status_code in [503, 404]
    AssertionError
    [FILIBUSTER] [FAIL]: Test failed; counterexample file written: counterexample.json

Again, we have another counterexample file.  If we look at the precise fault that was injected, we can see that the
request between ``foo`` and ``bar`` was failed with a ConnectionError exception.  Since the ``foo`` service does not
have an exception handler for this fault, the service returns a 500 Internal Server Error: we do not expect this response
in our functional test.

Instead of altering our functional test to allow for a 500 Internal Server Error, we want the service to return a 503
Service Unavailable if one of the dependencies is down.  Therefore, we will modify the implementation of the ``foo``
service to handle this failure.

.. code-block:: python

    except requests.exceptions.ConnectionError:
        raise ServiceUnavailable("The bar service is unavailable.")

We can verify our fix using counterexample replay.

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py --counterexample-file counterexample.json

Finally, we can run Filibuster again and test for the whole default set of failures as well.

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py

At this point, everything passes!

Computing Coverage
~~~~~~~~~~~~~~~~~~

From here, you can use Filibuster to compute coverage.  Coverage files are not available until the services are shutdown,
so we must shut the services down.  Then, we can use the Filibuster tool to generate coverage, which will be rendered as
html in the ``htmlcov`` directory.

.. code-block:: shell

    make local-stop
    filibuster-coverage

You can see that, even though we only wrote a test that exercised the failure-free path of the ``foo`` service,
Filibuster automatically generated the necessary tests to cover the failure scenarios.  This coverage is aggregated
across all generated Filibuster tests and for all services.

.. image:: /_static/images/tutorial-coverage.png

Targeting Precise Errors
------------------------

Up to now, we have been using Filibuster with a default set of faults.  However, what if your application generates
a failure that is not included in the default set?  To do that, we can use the Filibuster analysis tool to generate
a custom list of faults and failures to inject.

To do this, we run the following command.

.. code-block:: shell

    filibuster-analysis --services-directory services --output-file analysis.json

This command will invoke the Filibuster static analysis tool.  The analysis tool will look in the directory ``services``
for the implementation of each service and output an ``analysis.json`` file that can be provided to Filibuster for
more targeted fault injection.

You should see output like the following:

.. code-block:: shell

    [FILIBUSTER] [INFO]: About to analyze directory: services
    [FILIBUSTER] [INFO]: * found service implementation: services/foo
    [FILIBUSTER] [INFO]: * found service implementation: services/baz
    [FILIBUSTER] [INFO]: * found service implementation: services/bar
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Found services: ['foo', 'baz', 'bar']
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Analyzing service foo at directory services/foo
    [FILIBUSTER] [INFO]: * starting analysis of Python file: services/foo/foo/__init__.py
    [FILIBUSTER] [INFO]: * identified HTTP error: {'return_value': {'status_code': '500'}}
    [FILIBUSTER] [INFO]: * starting analysis of Python file: services/foo/foo/app.py
    [FILIBUSTER] [INFO]: * identified HTTP error: {'return_value': {'status_code': '503'}}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Analyzing service baz at directory services/baz
    [FILIBUSTER] [INFO]: * starting analysis of Python file: services/baz/baz/__init__.py
    [FILIBUSTER] [INFO]: * identified HTTP error: {'return_value': {'status_code': '500'}}
    [FILIBUSTER] [INFO]: * starting analysis of Python file: services/baz/baz/app.py
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Analyzing service bar at directory services/bar
    [FILIBUSTER] [INFO]: * starting analysis of Python file: services/bar/bar/__init__.py
    [FILIBUSTER] [INFO]: * identified HTTP error: {'return_value': {'status_code': '500'}}
    [FILIBUSTER] [INFO]: * starting analysis of Python file: services/bar/bar/app.py
    [FILIBUSTER] [INFO]: * identified HTTP error: {'return_value': {'status_code': '503'}}
    [FILIBUSTER] [INFO]:
    [FILIBUSTER] [INFO]: Writing output file: analysis.json
    [FILIBUSTER] [INFO]: Done.

From here, you can provide the analysis file directly to the Filibuster tool.

.. code-block:: shell

    filibuster --functional-test ./functional/test_foo_bar_baz.py --analysis-file analysis.json