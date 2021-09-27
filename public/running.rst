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