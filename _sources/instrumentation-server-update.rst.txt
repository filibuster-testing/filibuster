HTTP API: Update
================

The UPDATE API (``POST /filibuster/update``) provided by the Filibuster server is responsible for providing additional information about remote calls to the Filibuster server in order to generate additional fault injection scenarios.

Updates can come in two forms:

- ``request_received``: invoked by the target of a remote call after dynamic binding is resolved.  This is necessary to inject service specific failures, as we may not know the target of a remote call at the call site.
- ``invocation_complete``: invoked by the call site to report the value returned by the remote call.

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
     - Either ``request_received`` or ``invocation_complete``
   * - ``generated_id``
     - Required
     - Integer
     - A totally ordered identifier for this request in this test execution
   * - ``execution_index``
     - Required
     - EI (String)
     - Encoded execution index for this request
   * -
     - If ``request_received``:
     -
     -
   * - ``target_service_name``
     - Required
     - String
     - The name of the service where the request is received
   * -
     - If ``invocation_complete``:
     -
     -
   * - ``execution_index``
     - Required
     - EI (String)
     - Encoded execution index for this request
   * - ``vclock``
     - Required
     - VClock (Map)
     - Vector clock of this request
   * - ``return_value``
     - Required
     - Object
     - Object containing the fields and values to set to those fields in the response object

Example Payload: Request Received
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Here is an example payload for an instrumentation request from the bookings service in the ``cinema-1`` example after being called by the users service: the payload of ``POST /filibuster/update``:

.. code-block:: json

    {
      "instrumentation_type": "request_received",
      "generated_id": "0",
      "execution_index": "[[\"4e7d0eecdf181cf71b3cd538479b5927\", 1]]",
      "target_service_name": "bookings"
    }

This payload tells the Filibuster server that the service that received the remote call is the bookings service: this is necessary because with HTTP, requests are made using URLs which do not necessarily indicate the service that is contacted.

Example Payload: Invocation Complete
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Here is an example payload for an instrumentation request from the users service after the call to the bookings service returns.  This notifies the Filibuster service of the response.

.. code-block:: json

    {
      "instrumentation_type": "invocation_complete",
      "generated_id": 0,
      "execution_index": "[[\"4e7d0eecdf181cf71b3cd538479b5927\", 1]]",
      "vclock": {
        "users": 1
      },
      "return_value": {
        "__class__": "Response",
        "status_code": "200",
        "text": "5373923a3c6e2338d27835665066e38a"
      }
    }

This payload specifies that for the request with a certain generated id, execution index, and vector clock, the response was an instance of the ``Response`` class, where the status code and text attributes were set accordingly.

Example Payload: Invocation Completed with Exception
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Here is an example payload for an instrumentation request from the users service after the call to the bookings service throws an exception.  This notifies the Filibuster service of that exception: in this case, the exception could have occurred because of a failure in the remote service or because Filibuster injected that failure.

.. code-block:: json

    {
      "instrumentation_type": "invocation_complete",
      "generated_id": 0,
      "execution_index": "[[\"4e7d0eecdf181cf71b3cd538479b5927\", 1]]",
      "vclock": {
        "users": 1
      },
      "exception": {
        "name": "requests.exceptions.ConnectionError",
        "metadata": {
        }
      }
    }

This payload specifies that for the request with a certain generated id, execution index, and vector clock, the library call threw with an exception, ```requests.exceptions.ConnectionError```; this exception contains no additional metadata.

Response
--------

All updates return an empty JSON object.

.. code-block:: json

    {
    }