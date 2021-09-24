HTTP API: Create
================

The CREATE API (``PUT /filibuster/create``) provided by the Filibuster server is responsible for registering remote call with the Filibuster test server in order to drive fault injection for these calls.

Request
-------

We describe the necessary parameters for a request below along with an example taken from the ``cinema-1`` example.

Field Descriptions
~~~~~~~~~~~~~~~~~~

In the following table, we present descriptions of the fields in the request payload.

.. list-table:: Field Descriptions: Request Payload
   :widths: auto
   :header-rows: 1
   :align: left
   :class: force-left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``instrumentation_type``
     - Required
     - Type (String)
     - The Filibuster instrumentation type; for ``CREATE``, should be ``invocation``
   * - ``source_service_name``
     - Required
     - String
     - The name of the service where the call originates
   * - ``module``
     - Required
     - String
     - Name of the module or class of the instrumented call
   * - ``method``
     - Required
     - String
     - Name of the method of the instrumented call
   * - ``args``
     - Required
     - List
     - List of arguments to the instrumented call
   * - ``kwargs``
     - Required
     - Map
     - Additional keyword arguments to the instrumented call (specific for Python)
   * - ``callsite_file``
     - Required
     - String
     - Application file where the instrumented call originates
   * - ``callsite_line``
     - Required
     - String
     - Line number in ``callsite_file`` where the call originates
   * - ``full_traceback``
     - Required
     - String
     - SHA1 or MD5 hash representing a unique callsite in application code
   * - ``metadata``
     - Required
     - Map
     - Any metadata that should be associated with the request for fault-injection (*e.g.*, timeouts)
   * - ``vclock``
     - Required
     - VClock (Map)
     - Vector clock of this request
   * - ``origin_vclock``
     - Required
     - VClock (Map)
     - Vector clock of the originating request
   * - ``execution_index``
     - Required
     - EI (String)
     - Encoded execution index for this request

Example Payload
~~~~~~~~~~~~~~~

Here is the example payload for an instrumentation request from the users service in the ``cinema-1`` example: the payload of ``PUT /filibuster/create``:

.. code-block:: json

    {
      "instrumentation_type": "invocation",
      "source_service_name": "users",
      "module": "requests",
      "method": "get",
      "args": [
        "http://0.0.0.0:5001/movies/267eedb8-0f5d-42d5-8f43-72426b9fb3e6"
      ],
      "kwargs": {},
      "callsite_file": "/Users/c.meiklejohn/Documents/GitHub/nufilibuster/examples/cinema-1/services/users/users/app.py",
      "callsite_line": "113",
      "full_traceback": "436928f8a571d50077e6c6972034959a",
      "metadata": {
        "timeout": 10
      },
      "vclock": {
        "users": 2
      },
      "origin_vclock": {},
      "execution_index": "[[\"68ae4deac392aa61feeeb0634d243d57\", 1]]"
    }

This payload describes an invocation of `requests.get` from the `users` service to the `movies` service.  The call originates from line 113 in the main application file and the call contains a 10 second timeout.  There's an associated vector clock and execution index; the origin clock here is an empty clock, since this was the first remote call made from one service to another.

Response
--------

We describe the necessary parameters in an response below along with an example taken from the ``cinema-1`` example.

Field Descriptions
~~~~~~~~~~~~~~~~~~

In the following table, we present descriptions of the fields in the response body.

.. list-table:: Field Descriptions: Response Body
   :widths: auto
   :header-rows: 1
   :align: left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``generated_id``
     - Required
     - Integer
     - A totally ordered identifier for this request in this test execution
   * - ``failure_metadata``
     - Optional
     - Object
     - Object, see ``failure_metadata`` below
   * - ``forced_exception``
     - Optional
     - Object
     - Object, see ``forced_exception`` below

.. list-table:: Field Descriptions: Response Body, ``failure_metadata``
   :widths: auto
   :header-rows: 1
   :align: left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``return_value``
     - Required
     - Object
     - Object containing the fields and values to set to those fields in the response object
   * - ``exception``
     - Required
     - Object
     - Object containing the fields and values to set to those fields in the response object

.. list-table:: Field Descriptions: Response Body, ``forced_exception``
   :widths: auto
   :header-rows: 1
   :align: left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``name``
     - Required
     - String
     - Name of the exception class to instantiate and throw at the callsite
   * - ``metadata``
     - Required
     - Object
     - Object, see ``metadata`` below.

.. list-table:: Field Descriptions: Response Body, ``failure_metadata.exception``
   :widths: auto
   :header-rows: 1
   :align: left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``name``
     - Optional
     - String
     - Name of the exception class to instantiate and throw at the callsite
   * - ``metadata``
     - Optional
     - Object
     - Object, see ``metadata`` below.

.. list-table:: Field Descriptions: Response Body, ``forced_exception.metadata`` and ``failure_metadata.exception.metadata``
   :widths: auto
   :header-rows: 1
   :align: left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``abort``
     - Optional
     - Boolean
     - Whether or not the request occurs before throw; defaults to ``True``
   * - ``sleep``
     - Optional
     - Float or Expression (String)
     - The amount of time to sleep or an expression based on the callsite.  See below.

Timeouts
~~~~~~~~

For timeouts, either a float can be provided (as fractional seconds: 0.001 for a single millisecond) or an expression in terms of the timeout specified at the callsite.  To specify a timeout that is in terms of the callsite, use the following syntax:

For example, the following takes the call site's timeout and adds a single milliscond and sleeps that interval, forcing the timeout to fire.

.. code-block:: python

    @expr(metadata['timeout'])+0.001


To sleep an interval that's slightly before the timeout, you could also do the following:

.. code-block:: python

    @expr(metadata['timeout'])-0.001


Dynamic Reduction Invariant
~~~~~~~~~~~~~~~~~~~~~~~~~~~

For dynamic reduction to work, the metadata object that is returned by the instrumentation must always contain the fields that were supplied; therefore, ensuring the invariant holds that any fault injected produces a metadata object that is strictly greater.  This ensures a strict partial order over objects, where they can be compared to ensure requests are equivalent.  Following from this, the metadata object can contain any fields that are instrumentation specific, as long as they are returned along with the response.

Example Body: No Fault Injection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The minimal response from the create call to the Filibuster server will contain a single field in a JSON object containing an identifier that uniquely identifies this request in the test exceution.

.. code-block:: json

    {
      "generated_id": 1
    }

Example Body: Fault Injection (Value)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This response from the create call informs the instrumentation that the response should be modified to change the ``status_code`` field on the ``Response`` object to a 500 Internal Server Error response.

The instrumentation is responsible for iterating this ``return_value`` dictionary and set the values on the response object.

.. code-block:: json

    {
      "generated_id": 1,
      "failure_metadata": {
        "return_value": {
          "status_code": 500
        }
      }
    }

Example Body: Fault Injection (Exception)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This response from the create call informs the instrumentation that instead of returning a response to the user that an exception should be thrown at the callsite; in this specific case, the ``requests.exceptions.ConnectionError`` exception will be instantiated and thrown.

The instrumentation is responsible in throwing this exception.

.. code-block:: json

    {
      "generated_id": 1,
      "forced_exception": {
        "name": "requests.exceptions.ConnectionError",
        "metadata": {
        }
      }
    }

Optional fields might also be present.  In the following response, a ``requests.exceptions.Timeout`` exception will be thrown, but only after the request is issued.

.. code-block:: json

    {
      "generated_id": 1,
      "forced_exception": {
        "name": "requests.exceptions.Timeout",
        "metadata": {
          "abort": false
        }
      }
    }

Finally, in the following response, a ``requests.exceptions.Timeout`` exception will be thrown, only after the request is issued and after sleeping ``@expr(metadata['timeout'])+0.001`` seconds.  This expression is evaluated by the instrumentation and is arbitrary based on the instrumentation's implementation.

.. code-block:: json

    {
      "generated_id": 1,
      "forced_exception": {
        "name": "requests.exceptions.Timeout",
        "metadata": {
          "sleep": "@expr(metadata['timeout'])+0.001",
          "abort": false
        }
      }
    }