Industry Examples
========


Audible
-----------
Description
^^^^^^^^^^^
This diagram was taken from the `AWS re:Invent 2018 talk by Audible <https://www.youtube.com/watch?v=7uJG3oPw_AA>`_
titled *Chaos Engineering and Scalability at Audible.com*. This is a highly-simplified view of the actual architecture used at Audible.

.. image:: /_static/diagrams/audible.jpg

Fault Analysis
^^^^^^^^^^^^^^
The bug presented in the talk can be described in three stages.

1. In the first stage, there is an inconsistent content upload. ``audio-assets`` and ``asset-metadata`` (XML chapter descriptions) are not uploaded atomically. In the talk, an audiobook had a success upload in ``audio-assets`` but failed to upload to ``asset-metadata``. This results in the system being in an inconsistent state.
2. In the second stage, a user attempts to access this content. The ``content-delivery-service`` calls ``audible-download-service``, where are calls succeed, and then ``content-delivery-service`` calls ``audio-assets`` and ``asset-metadata``. The final call to ``asset-metadata`` returned an error because the chapter description was missing. The application programmer assumed that ``asset-metadata`` always contains the chapter description for the requested audiobook (after initial checks have passed), so there is no appropriate error handling code. As a result, ``content-delivery-service`` returns a generic ``500 Internal Server Error``.
3. In the third stage, both the system and the user responds to this generic error by initiating retries. Each retry makes all the previous requests again (and failing at ``asset-metadata`` again). This fault causes the system to perform work that will be abandoned, manifesting as system failure when all available compute capacity is exhausted.

We simulated the dormant fault by have an environment variable ``BAD_METADATA=1`` in ``asset-metadata``.
When the environment variable is set, this service always returns a ``404``. The other faults which exhaust
node capacity needs to be simulated in AWS.

Filibuster Analysis
^^^^^^^^^^^^^^^^^^^

No Reduction
''''''''''''

First, let's consider the ways each service can fail:

* ``content-delivery-engine`` can fail 4 ways: 2 exceptions and 2 error codes (any abort entire request);
* ``content-delivery-service`` can fail 6 ways: 2 exceptions and 4 error codes (any abort entire request);
   * ``audible-download-service`` can fail 6 ways: 2 exceptions and 4 error codes;
      * ``ownership`` can fail 5 ways: 2 exceptions, 3 error codes (any abort entire request);
      * ``activation`` can fail 4 ways: 2 exceptions, 2 status codes (any abort entire request);
      * ``stats`` can fail 3 ways: 2 exceptions, 1 status codes (doesn't impact request);
   * ``asset-metadata`` can fail 5 ways: 2 exceptions, 3 status codes (any abort entire request); and
   * ``audio-assets`` can fail 5 ways: 2 exceptions, 3 status codes (any abort entire request).

First, we have to consider the impact of ``content-delivery-engine`` failures and the passing execution.

.. math::
    1 + 4 = 5

Next, we consider ``content-delivery-service`` failures, where it makes no other requests.

.. math::
    1 + 4 + 6 = 11

Next, failures of the ``audible-download-service`` in isolation.

.. math::
    1 + 4 + 6 + 6 = 17

Next, we have to consider the failures of its dependencies (``ownership``, ``activation``, and ``stats``).

.. math::
    &1\ +\ 4\ +\ 6\ +\ 6\ +\ 5\ =\ 22 \\
    &1\ +\ 4\ +\ 6\ +\ 6\ +\ (5\ +\ 4)\ =\ 26 \\
    &1\ +\ 4\ +\ 6\ +\ 6\ +\ (5\ +\ 4\ +\ 3)\ =\ 29

Now, we need to consider the additional requests that occur from ``content-delivery-service``.
``asset-metadata`` can fail 5 ways, but we also need to consider it's failures in combination with 
``stats``, as ``stats`` can fail and have no impact on whether this call is made. Therefore, we'll
consider the way ``stats`` can fail with all possible outcomes (3 * 6).

.. math::
    1 + 4 + 6 + 6 + (5 + 4 + 3) + (5 + (6 \times 3)) = 49

Finally, we look at audio_assets, which is only called when the call to ``asset-metadata`` is successful,
again with all combination of how ``stats`` -- called before it with no impact on the request -- can fail
with it. We no longer consider all possible outcomes of ``asset-metadata``, but only consider the failures
because it must succeed for the ``audio-assets`` call to be made.

.. math::
    1 + 4 + 6 + 6 + (5 + 4 + 3) + (5 + (5 \times 3)) + (5 + (5 \times 3)) = 69

This is the number of tests executed with Filibuster with no reduction.

Dynamic Reduction
'''''''''''''''''
With dynamic reduction, we can remove the following tests:

* 4 tests of the ``content-delivery-service``: ``404``, ``403``, ``500``, ``504``, as injecting faults on its dependencies causes these errors to happen;
* 4 tests of the ``audible-download-service``: ``403``, ``404``, ``500``, ``503``, as injecting faults on its dependencies causes these errors to happen;
* 15 tests that are the combination of faults from ``stats``, which has no impact on the outcome, combined with the possible failures of ``asset-metadata``; and
* 15 tests that are the combination of faults from ``stats`` combined with the possible failures of ``audio-assets``.

This is 38 tests that do not need to be executed: :math:`4 + 4 + 15 + 15 = 38`. This results in the following.

.. math::
    69 - 38 = 31

This is the number of tests executed with Filibuster with dynamic reduction.

Expedia
-----------

Description
^^^^^^^^^^^
This architecture diagram is taken from the talk from Daniel and Nikos at 
`Automating Chaos Attacks at Expedia <https://www.youtube.com/watch?v=xrtbiyfRvb4>`_
at Chaos Conf 2020. Here is what we implemented.

.. image:: /_static/diagrams/expedia.jpg

Fault Analysis
^^^^^^^^^^^^^^
In this small example, Expedia retrieves reviews for a hotel where reviews are sorted by an ML algorithm. If
that service failed, the *API Gateway* fallbacks to retrieve reviews from another service where they are sorted
by time from most recent to least recent. They validated the fallback using resilience tests. This is a fake 
bug, but shows how they test error handling code for this particular part of their service.

Filibuster Analysis
^^^^^^^^^^^^^^^^^^^
Given that each service, *review-ml* and *review-time* can each fail four ways, we have to explore :math:`1 + (4 * 4) = 17`
tests. This is the number executed by Filibuster with both dynamic reduction and without reduction.

Mailchimp
-----------

Description
^^^^^^^^^^^
This architecture diagram is taken from the talk from Caroline Dickey `Think Big: Chaos Testing a Monolith
<https://www.youtube.com/watch?v=w_IeMAidgpI>`_ at Chaos Conf 2019. Here is what we implemented.

.. image:: /_static/diagrams/mailchimp.jpg

Fault Analysis
^^^^^^^^^^^^^^
Here's the list of faults identified from the Mailchimp talk that is relevant in our implementation.

1. Fault #1 - MySQL database instance becomes read-only: Mailchimp expected that when the database became read-only the application would degrade gracefully and alerting would fire. This was mostly true: a majority of the Mailchimp application had application code that gracefully handled this database error; however, one legacy component did not have proper error handling and exposed a database error to the user in the UI.
2. Fault #2 - ``requestmapper`` becomes unavailable. ``requestmapper``, a service for mapping pretty URLs for customer landing pages to internal URLs suddenly becomes unavailable in production.

The description of this bug in the talk is extremely vague; what appears to be happening is the following:

* ``app-server`` makes a request to ``requestmapper`` to get information about the URLs; then
* when ``requestmapper`` service is down, ``app-server`` should handle the error and continue handling the request.

The presenter said that changing the ``503 Service Unavailable`` response to a ``500 Internal Server Error``
fixed the bug, but did not explain why; our best guess is that the application server has specific error
handling for a ``500 Internal Server Error`` and no error handling for the ``503 Service Unavailable``.

We simulated the first fault by setting an environment variable ``DB_READ_ONLY=1``. If set, calls to write to the
DB always returns a ``403 Forbidden``. For the second fault, the current version of the code throws a ``500``
(which the load balancer can handle), but buggy implementation throws a ``503`` (which the load balancer supposedly cannot handle).

Filibuster Analysis
^^^^^^^^^^^^^^^^^^^
Let's look at what Filibuster has to consider when testing this application.

No Reduction
''''''''''''

First, we have to consider the ways things can fail:

* ``load-balancer`` can fail with 2 exceptions and 1 error code;
* ``requestmapper`` can fail with 2 exceptions and 1 error code;
* read to ``db-primary`` can fail with 2 exceptions and 1 error code,
   * only issued if ``requestmapper`` succeeds;
* write to ``db-primary`` can fail with 2 exceptions and 2 error codes,
   * only issued if ``db-primary`` call succeeds or fails with an error code;
* read to ``db-secondary`` can fail with 2 exceptions and 2 error codes,
   * only issued if ``db-primary`` read or ``db_primary`` write has failed; then
* write to ``db-secondary`` can fail with 2 exceptions and 2 error codes,
   * only issued if ``db-primary`` read or ``db-primary`` write has failed; and
   * ``db-secondary`` fails with an error code.

Let's start by considering the failures of just the ``load-balancer`` and the ``requestmapper``. In this case, 
we need to consider the ways that each service can fail along with the passing execution.

.. math::
    1 + 3 + 3 = 7

Next, we have to consider the failure of the ``db-primary`` read operation.

.. math::       
    1 + 3 + 3 + 4 = 11

Now, we have to consider what happens when the ``db-primary`` write operation fails. We have to keep in mind the ways that things can fail: if ``db-primary`` read fails with 2 of the 4 errors, it will continue to execute the write operation; otherwise, it will not. This results in the following: :math:`4 + 4 + (2 \times 4)`: ``db-primary`` failures (4), ``db-secondary`` failures (4) and finally the calls in the combination: :math:`(2 \times 4)`.

.. math::
    1 + 3 + 3 + (4 + 4 + (2 \times 4)) = 23

Next, we have to consider the ways that the ``db-secondary`` call can fail. Keep in mind that we have to consider that this call is only made if the ``db-primary`` read fails and db_primary write fails :math:`(4 + 4 + (2 * 4))` combined with the ways that the ``db-secondary`` read can fail (4). This gives us the following.

.. math::
    1 + 3 + 3 + (4 + 4 + (2 \times 4)) + ((4 + 4 + (2 + 2)) \times 4) = 71

Finally, we have to consider the subsequent ``db-secondary`` write call can fail, keeping in mind that it only occurs if the previous errors occur and the ``db_secondary`` read call fails with either 2 status codes; remember, this call itself can fail 4 ways as well. Ths extends the following formula with :math:`((4 + 4 + (2 + 2)) * 4) + (4 + 4 + (2 * 4))` to give us the following.

.. math::
    1 + 3 + 3 + (4 + 4 + (2 \times 4)) + ((4 + 4 + (2 + 2)) \times 4) + 
   ((4 + 4 + (2 + 2)) \times 4) + (4 + 4 + (2 \times 4)) = 135

This is the number that Filibuster runs without pruning.

Dynamic Reduction
'''''''''''''''''
With dynamic reduction, we can only reduce 1 execution: the execution where we inject a ``500 Internal Server Error``
returned by the ``app-server`` to the ``load-balancer``, as injecting any of the ``requestmapper`` failures, or
certain combinations of the ``db-primary`` and ``db-secondary`` failures cause this service to return this error already.

This results in a total of :math:`135 - 1 = 134`, the number that Filibuster runs with dynamic reduction.

Netflix
-----------

Description
^^^^^^^^^^^
The basis of the Netflix example comes from `a talk <https://www.youtube.com/watch?v=Q4nniyAarbs>`_ by Casey 
Rosenthal and `this talk <https://www.youtube.com/watch?v=qyzymLlj9ag>`_ from Nora Jones. These talks only show
us a subset of the services that Netflix uses and one example of fallback behavior (e.g., recommendations) so we
added additional fallback behavior that follows the same strategy and intuition, but isn't the actual fallback
behavior of Netflix, as that information is not publically available.

The diagram captures the microservices called when a client loads its homepage, which consists of multiple parts.

.. image:: /_static/diagrams/netflix.jpg

Fault Analysis
^^^^^^^^^^^^^^
The Netflix example contains three faults that can be activated using an environment variable ``NETFLIX_FAULTS=true``.
All three of these faults come from this talk from Nora Jones.

Here are the faults:

1. Call with no fallback: The ``api-server`` service tries to get the user profile from the ``user-profile`` service; however, if this service is unavailable the entire request is failed;
2. Retries to the same server: ``The api-server`` service communicates with the ``my-list`` service to get the user's list; if this service is unavailable, the request is retried against the same service; and
3. Misconfigured timeouts: The ``api-server`` service communicates with the ``user-profile`` service with a 1 second timeout; the ``user-profile`` service communicates with the telemetry service, which has a 20 second timeout; causing the ``user-profile`` service to fail if the ``telemetry`` service request takes over 1 second, but less than 5 -- a failure when there is no actual error.

For fault #3, ``CHECK_TIMEOUTS=true`` also needs to be used to verify timeouts execute correctly.


Filibuster Analysis
^^^^^^^^^^^^^^^^^^^
This is the analysis when the faults are not active.

No Reduction
''''''''''''
First, let us consider the ways each service can fail.

* ``api-gateway`` can fail 5 ways: 3 error codes, 2 exceptions;
* ``user-profile`` can fail 4 ways: 2 error codes, 2 exceptions;
* ``bookmarks`` can fail 4 ways: 2 error codes, 2 exceptions;
* ``telemetry`` can fail 3 ways: 1 error code, 2 exceptions;
* ``trending`` can fail 3 ways: 1 error code; 2 exceptions;
* ``my-list`` can fail 4 ways: 2 error codes, 2 exceptions;
* ``user-recommendations`` can fail 4 ways: 2 error codes, 2 exceptions;
* ``global-recommendations`` can fail 3 ways: 1 error code, 2 exceptions; and
* ``ratings`` can fail 4 ways: 2 error codes, 2 exceptions.

We start with the passing execution (1). We then we need to consider the ways that the call from the ``mobile-client``
to the ``api-gateway`` can fail.

.. math::
    1 + 5 = 6

Next, we consider failures between the ``api-gateway`` and its dependencies. First, the call to ``user-profile``.

.. math::
    1 + 5 + 4 = 10

Then, the call to ``bookmarks``, which is only made if the previous call succeeds.

.. math::
    1 + 5 + 4 + 4 = 14

Now, if ``bookmarks`` fails, we will make a call to ``telemetry``, which is allowed to fail, and then a call to ``trending``.
Considering just the call to ``telemetry`` first, this gives us.

.. math::
    1 + 5 + 4 + 4 + (3 \times 4) = 26

Next, the subsequent call to ``trending``. With this call, we have to consider the following:

* combinations of ``bookmarks`` with ``trending``: :math:`3 \times 4 = 12`
* combinations of ``bookmarks``, ``telemetry`` and ``trending`` together: :math:`3 \times 4 \times 3 = 36`

This gives us the following.

.. math::
    1 + 5 + 4 + 4 + (3 \times 4) + ((3 \times 4) + (3 \times 4 \times 3)) = 74

Next, we have to consider ``my_list``. With this call, we have to consider the following:

* combination of ``bookmarks``, ``telemetry`` and ``my-list``: :math:`4 \times 3 \times 4 = 48`
* combination of ``bookmarks`` and ``my-list``: :math:`4 \times 4 = 16`
* ``my-list`` failing in isolation: 4

This gives us the following.

.. math::
    &1 + 5 + 4 + 4 + (3 \times 4) + ((3 \times 4) + (3 \times 4 \times 3)) + (4 \times 3 \times 4) + (4 \times 4) + 4 \\
    &= 142

Next, ``user-recommendations``, where we have to consider the following:

* combination of ``bookmarks``, ``telemetry and ``user-recommendations``: :math:`4 \times 3 \times 4 = 48`
* combination of ``bookmarks`` and ``user-recommendations``: :math:`4 \times 4 = 16`
* failure of ``user-recommendations`` in isolation: :math:`4`

This gives us the following.

.. math::
    &1 + 5 + 4 + 4 + (3 \times 4) + ((3 \times 4) + (3 \times 4 \times 3)) + (4 \times 3 \times 4) + (4 \times 4) + 4 + \\
    &4 + (4 \times 3 \times 4) + (4 \times 4) \\
    &= 210

Next, ``global-recommendations`` which is called on failure of ``user-recommendations``:

Again:

* combination of ``global-recommendations`` with ``user-recommendations``: :math:`4 \times 3 = 12`
* combination of ``bookmarks``, ``telemetry``, ``user-recommendations`` and ``global-recommendations``: :math:`4 \times 3 \times 4 \times 3 = 144`
* combination of ``bookmarks``, ``user-recommendations``, and ``global-recommendations``: :math:`4 \times 3 \times 4 = 48`

This gives us the following.

.. math::
    &1 + 5 + 4 + 4 + (3 \times 4) + ((3 \times 4) + (3 \times 4 \times 3)) + (4 \times 3 \times 4) + (4 \times 4) + 4 + \\
    &4 + (4 \times 3 \times 4) + (4 \times 4) + \\
    &(4 \times 3) + (4 \times 3 \times 4 \times 3) + (4 \times 3 \times 4) \\
    &= 414

Next, the call to ``trending`` when ``global-recommendations`` fails.

* combination of ``bookmarks``, ``telemetry`` and the second ``telemetry`` call: 4 * 3 * 3 = 36

This yields the following.

.. math::
    &1 + 5 + 4 + 4 + (3 \times 4) + ((3 \times 4) + (3 \times 4 \times 3)) + (4 \times 3 \times 4) + (4 \times 4) + 4 +\\
    &4 + (4 \times 3 \times 4) + (4 \times 4) +\\
    &(4 \times 3) + (4 \times 3 \times 4 \times 3) + (4 \times 3 \times 4) +\\
    &(4 \times 3 \times 3) \\
    &= 450

Finally, the last call to ratings.

* combinations of ``bookmarks``, ``telemetry``, ``user_recommendations``, ``global_recommendations``, and ``ratings``: :math:`4 \times 3 \times 4 \times 3 \times 4 = 576`
* combination of ``bookmarks``, ``user_recommendations``, ``global_recommendations`` and ``ratings``: :math:`(4 \times 4 \times 3 \times 4 = 192)`
* combination of ``bookmarks``, ``user_recomendations`` and ``ratings``: :math:`(4 \times 4 \times 4) = 64`
* combination of ``bookmarks`` and ``ratings``: :math:`(4 \times 4) = 16`
* combination of ``bookmarks`` and ``ratings``: :math:`(4 \times 4) = 16`
* combination of ``user_recommendations``, ``global_recommendations``, ``ratings``: :math:`(4 \times 3 \times 4) = 48`
* combination of ``user_recommendations`` and ``ratings``: :math:`(4 \times 4) = 16`
* combination of ``bookmarks``, ``telemetry``, and ``ratings``: :math:`(4 \times 3 \times 4) = 48`
* combination of ``bookmarks``, ``telemetry``, ``user_recommendations``, ``ratings``: :math:`(4 \times 3 \times 4 \times 4) = 192`
* ratings failing in isolation (:math:`4`)

This results in the following.

.. math::
    &1 + 5 + 4 + 4 + (3 \times 4) + ((3 \times 4) + (3 \times 4 \times 3)) + (4 \times 3 \times 4) + (4 \times 4) + 4 + \\
    &4 + (4 \times 3 \times 4) + (4 \times 4) + \\
    &(4 \times 3) + (4 \times 3 \times 4 \times 3) + (4 \times 3 \times 4) + \\
    &(4 \times 3 \times 3) + \\
    &(4 \times 3 \times 4 \times 3 \times 4) + (4 \times 4 \times 3 \times 4) + (4 \times 4 \times 4) + (4 \times 4) + \\
    &(4 \times 3 \times 4) + (4 \times 4) + (4 \times 3 \times 4) + (4 \times 3 \times 4 \times 4) + 4 \\
    &= 1606

This is the exact number of test executions run by Filibuster with no dynamic reduction.

Dynamic Reduction
'''''''''''''''''
The structure of this application does not lend itself well to dynamic reduction: as, all 
of the calls are made from the top-level and therefore we have to explore all possible 
combinations of failures of almost all the requests.

In this example, we're only able to use dynamic reduction to eliminate injecting status 
code failures between the ``mobile-client`` and the ``app-server``: as, we can test this
behavior indirectly by injecting failures on the ``app-server``'s dependencies.

With Bugs
'''''''''
With bugs, a number of additional tests have to be run. We omit the analysis for brevity. 
Without dynamic reduction, it results in 4670 test executions; with 4721 test executions.
