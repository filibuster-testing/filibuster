Instrumentation Overview
========================

In this section, we will discuss the Filibuster instrumentation and how it is used for in fault injection testing.  The focus of this presentation will be on our built-in HTTP instrumentation.  However, the insights that we provide are valuable to anyone looking to instrument other libraries for use with Filibuster.

Goals
-----

The goals of instrumenting libraries for use with Filibuster are the following:

- Identify when and where remote calls are made between two different services.

- Alter the responses of remote service calls: either by throwing an exception at the callsite or returning a response that indicates an error.

- Propagating required instrumentation metadata from service to service as calls are made.

We discuss each goal below to outline the overall architecture of Filibuster.

Filibuster Architecture
-----------------------

.. image:: /_static/diagrams/architecture-horiz.png

Filibuster runs a server that is responsible for running the functional test for the application, generating additional test executions that try the various ways calls can fail between services, running those additional test executions, gathering coverage data and reporting the results back to the developer.

We now look at the concrete functionality we need to address the three goals:

- In order for Filibuster to know what additional test executions to generate, the Filibuster server must be notified of the remote calls made between different services.  For this, the Filibuster server exposes an HTTP API that instrumented libraries communicate with.

- When executing subsequent test executions and injecting failures, Filibuster will notify the instrumentation through the responses to the HTTP API calls with information on whether or not a failure should be injected.  It is up to the instrumentation to inject the appropriate failure based on the information returned by the Filibuster server.

- Filibuster's dynamic reduction algorithm requires that both requests between different services are able to be uniquely identified across executions (using execution indexes) and that we are able to understand the causal relationships between requests across service boundaries (using vector clocks.)  This information needs to be propagated between requests through instrumentation.

Anatomy of a Request
--------------------

To understand how Filibuster addresses the first two goals, we look at a diagram that shows when, and from where, the instrumentation calls are made.

.. note::
    To understand the data format and API of these instrumentation calls, we refer you to the Filibuster Server API section of the documentation.

.. |nbsp| unicode:: 0xA0
   :trim:

.. image:: /_static/diagrams/instrumentation.png

Referencing the above diagram, instrumentation works as follows.  First, before the target method is invoked, instrumented libraries should first issue an invocation call to Filibuster to notify it of the remote call that is about to be issued.  The return value from this call will notify the instrumentation on whether or not a fault should be injected.  Next, if the call is issued, the target of the call should notify the Filibuster server of the service that received the remote call.  Finally, if the call is actually issued, the instrumentation should notify the Filibuster that the call has completed with the response value.

The table below and diagram describes where these instrumentation calls should be placed in the request path.

.. list-table:: Request process with instrumentation endpoints and instrumentation types
   :widths: auto
   :header-rows: 1
   :align: left

   * - No.
     - Type
     - Endpoint
     - Type
     - Description
   * - 1.0
     - Request
     -
     -
     - Request originates at Service A
   * - 2.0
     - Request
     -
     -
     - `requests.get` used by Service A to issue a request to B
   * - |nbsp| |nbsp| 2.1
     - *Instrumentation*
     - ``PUT /filibuster/create``
     - ``invocation``
     - *Notify Filibuster server invocation with call site and metadata*
   * - |nbsp| |nbsp| 2.2
     - Request
     -
     -
     - Issue call to Service B if fault should not be injected
   * - |nbsp| |nbsp| |nbsp| |nbsp| 2.2.1
     - *Instrumentation*
     - ``POST /filibuster/update``
     - ``request_received``
     - *Notify Filibuster server of invoked service*
   * - |nbsp| |nbsp| 2.3
     - *Instrumentation*
     - ``POST /filibuster/update``
     - ``invocation_complete``
     - *Notify Filibuster of return value when call completes*

Metadata Propagation
--------------------

We now look at how we address the third goal.

Filibuster requires that instrumentation metadata be propagated between services on nested service calls.  To achieve this, our instrumentation automatically assigns these values to headers associated with each call and then parses these values when received with an incoming call.

We refer the reader to the following diagram for a depiction of how this occurs in the case of our examples written with Flask and the ``requests`` library.

.. image:: /_static/diagrams/instrumentation-metadata.png

Instrumentation calls made to the Filibuster server require that five values be present, we discuss these below.

.. list-table:: Metadata propagated by instrumentation required in instrumentation calls
   :widths: auto
   :header-rows: 1
   :align: left

   * - Field
     - Presence
     - Data Type
     - Description
   * - ``generated_id``
     - Optional
     - Integer
     - A totally ordered identifier for this request in this test execution
   * - ``vclock``
     - Required
     - VClock (Map)
     - Vector clock associated with this outgoing request
   * - ``origin_vclock``
     - Required
     - VClock (Map)
     - Vector clock associated with the request that originated this request
   * - ``execution_index``
     - Required
     - EI (String)
     - Encoded execution associated with this outgoing request
   * - ``request_id``
     - String
     - Required
     - Unique identifier for the user request; used to assign a vector clock and execution index.



