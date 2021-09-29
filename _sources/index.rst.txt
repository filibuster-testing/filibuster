.. |br| raw:: html

      <br>

.. image:: /_static/images/filibuster-header.png
  :alt: Filibuster: Service-level Fault Injection Testing

|br|

Overview
--------

Filibuster is the prototype implementation of Service-level Fault Injection Testing (`ACM SoCC '21 <https://acmsocc.org/2021/accepted-papers.html>`_) written in Python.

Service-level Fault Injection Testing is a technique for identifying resilience issues in microservice-based applications in development, before code ships to production.  Filibuster has been designed to be easy to use, lightweight, and able to be integrated into a continuous integration environment, like GitHub Actions or Amazon's CodeBuild CI/CD environment.

Filibuster open-source and available on `GitHub <https://github.com/filibuster-testing>`_.

Roadmap
^^^^^^^

Filibuster currently supports Python services implemented in Flask that communicate using either gRPC or HTTP.  Java support for `Armeria <https://armeria.dev/>`_ web services that communicate using gRPC or HTTP has been completed and is currently being tested.

Table of Contents
-----------------

Depending on your role, we recommend different sections of our documentation.

* For *general readers*, interested in learning how Filibuster can be used on a microservice application to improve resilience, we recommend the Tutorial.
* For *application developers*, looking to use Filibuster on their application to identify resilience issues, we recommend the Tutorial.
* For *infrastructure engineers*, looking to extend Filibuster to support different programming languages and remote procedure call frameworks, we recommend you review the sections on Extending Filibuster and Writing Instrumentation.

.. toctree::
   :maxdepth: 2
   :caption: Using Filibuster

   tutorial
   tools

.. toctree::
   :maxdepth: 2
   :caption: Filibuster Corpus

   running
   cinema-examples
   industry-examples

.. toctree::
   :maxdepth: 2
   :caption: Extending Filibuster

   instrumentation-overview
   instrumentation-flask
   instrumentation-requests


.. toctree::
   :maxdepth: 2
   :caption: Writing Instrumentation: GRPC

   instrumentation-grpc-overview
   instrumentation-grpc-client
   instrumentation-grpc-server
   instrumentation-grpc-client-fi
   instrumentation-grpc-client-analysis

.. toctree::
   :maxdepth: 2
   :caption: Filibuster Server API

   instrumentation-formats
   instrumentation-server-create
   instrumentation-server-update
   instrumentation-server-new-test-execution

