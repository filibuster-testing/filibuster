HTTP API: New Test Execution
============================

The New Test Execution API (``GET /filibuster/new-test-execution/<service_name>``) provided by the Filibuster server can be used by instrumentation to determine if the request that was just received is part of the same test execution that the previous request was in.  This is important because it allows the system to reset system state for a new test without having to restart all of the services (see the bypass restart options in the Make Targets section.)

Request
-------

This request only takes one parameter in the URL: the name of the service that is calling the API.

Response
--------

The response contains a single boolean in a JSON body that indicates if this is the first request to this service in a new test execution.

Field Descriptions
~~~~~~~~~~~~~~~~~~

In the following table, we present descriptions of the fields in the response body.

.. list-table:: Field Descriptions: Response Body
   :widths: auto
   :header-rows: 1
   :align: left
   :class: force-left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``new_test_execution``
     - Required
     - Boolean
     - Is this the first request to this service in a new test execution?

Example Body: Request Received
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Included below, is an example response.

.. code-block:: json

    {
        "new_test_execution": false
    }