Running
=======

The following make targets are applicable for all examples.

Local
------------------

These targets enable local development with Filibuster.

.. list-table:: 
   :widths: 25 25
   :header-rows: 1

   * - Make Target
     - Description
   * - ``local-start``
     - start all services in local
   * - ``local-stop``
     - stop all services in local
   * - ``local-functional``
     - start all services, run all functional tests, and stop all services if and only if all tests pass
   * - ``local-functional-via-filibuster-server``
     - start all services with Filibuster, run all functional tests, and stop all services if and only if all tests pass
   * - ``local-functional-with-fault-injection``
     - start all services, run all functional tests with Filibuster, and stop all services if and only if all tests pass
   * - ``local-functional-with-fault-injection-bypass-start-stop``
     - same as ``local-functional-with-fault-injection``; assumes that services do not need to be restarted in between test executions
   * - ``local-functional-with-fault-injection-bypass-start-stop-no-pruning``
     - same as ``local-functional-with-fault-injection`` but disables dynamic reduction algorithm; assumes that services do not need to be restarted in between test executions

Docker
-------------------

The Docker make targets are the same as the local make targets, with the exception that services are
built in Docker containers and run using Docker Compose when testing.

.. list-table:: 
   :widths: 25 25
   :header-rows: 1

   * - Make Target
     - Description
   * - ``docker-start``
     - start all services in Docker
   * - ``docker-stop``
     - stop all services in Docker
   * - ``docker-functional``
     - start all services, run all functional tests, and stop all services if and only if all tests pass
   * - ``docker-functional-via-filibuster-server``
     - start all services with Filibuster, run all functional tests, and stop all services if and only if all tests pass
   * - ``docker-functional-with-fault-injection``
     - start all services, run all functional tests with Filibuster, and stop all services if and only if all tests pass
   * - ``docker-functional-with-fault-injection-bypass-start-stop``
     - same as ``docker-functional-with-fault-injection``; assumes that services do not need to be restarted in between test executions
   * - ``docker-functional-with-fault-injection-bypass-start-stop-no-pruning``
     - same as ``docker-functional-with-fault-injection`` but disables dynamic reduction algorithm; assumes that services do not need to be restarted in between test executions

Minikube
---------------------

The Minikube make targets are the same as the local make targets, with the exception that services are 
built in Docker containers and run using Minikube when testing.

.. list-table:: 
   :widths: 25 25
   :header-rows: 1

   * - Make Target
     - Description
   * - ``minikube-start``
     - start all services in Minikube
   * - ``minikube-stop``
     - stop all services in Minikube
   * - ``minikube-functional``
     - start all services, run all functional tests, and stop all services if and only if all tests pass
   * - ``minikube-functional-via-filibuster-server``
     - start all services with Filibuster, run all functional tests, and stop all services if and only if all tests pass
   * - ``minikube-functional-with-fault-injection``
     - start all services, run all functional tests with Filibuster, and stop all services if and only if all tests pass
   * - ``minikube-functional-with-fault-injection-bypass-start-stop``
     - same as ``minikube-functional-with-fault-injection``; assumes that services do not need to be restarted in between test executions
   * - ``minikube-functional-with-fault-injection-bypass-start-stop-no-pruning``
     - same as ``minikube-functional-with-fault-injection`` but disables dynamic reduction algorithm; assumes that services do not need to be restarted in between test executions

EKS
----------------

The EKS make targets are the same as the local make targets, with the exception that services are built 
in Docker containers, pushed to ECR, and run using EKS when testing.

All targets assume that the top-level ``start-eks`` has been used to start an EKS cluster; ``stop-eks`` can
be used to terminate the cluster.

.. list-table:: 
   :widths: 25 25
   :header-rows: 1

   * - Make Target
     - Description
   * - ``eks-start``
     - start all services in EKS
   * - ``eks-stop``
     - stop all services in EKS
   * - ``eks-functional``
     - start all services, run all functional tests, and stop all services if and only if all tests pass
   * - ``eks-functional-via-filibuster-server``
     - start all services with Filibuster, run all functional tests, and stop all services if and only if all tests pass
   * - ``eks-functional-with-fault-injection``
     - start all services, run all functional tests with Filibuster, and stop all services if and only if all tests pass
   * - ``eks-functional-with-fault-injection-bypass-start-stop``
     - same as ``eks-functional-with-fault-injection``; assumes that services do not need to be restarted in between test executions
   * - ``eks-functional-with-fault-injection-bypass-start-stop-no-pruning``
     - same as ``eks-functional-with-fault-injection`` but disables dynamic reduction algorithm; assumes that services do not need to be restarted in between test executions

Additional Options
----------------------------------

.. list-table:: 
   :widths: 25 25
   :header-rows: 1

   * - Environment Variable
     - Description
   * - ``EXTENDED_EXCEPTIONS=true``
     - try all possible exceptions from the ``requests`` library
   * - ``TIMEOUT_REQUEST_OCCURS=true``
     - when testing timeouts, test a timeout variation where the dependent requests are still issued, but the call still returns timeout simulating an omission of the response, rather than omission of the request
   * - ``PRETTY_EXECUTION_INDEXES=true``
     - uses possibly less precise, more readable execution indexes for a single test for debugging
   * - ``CHECK_TIMEOUTS=true``
     - sleep incoming requests until their specified timeout + 1 and then process request; return timeout exception at the caller regardless. *Note: it's not possible to run to just the timeout in Python due to timer precision, as this won't trigger timeout behavior.*