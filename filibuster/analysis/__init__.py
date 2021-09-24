import ast
import json
import os
import re

from filibuster.logger import info

services = []
instrumentation = {}


def add_java_grpc_exceptions():
    # Setup.
    instrumentation['java.grpc'] = {}
    instrumentation['java.grpc']['pattern'] = "(.*Service/.*)"
    instrumentation['java.grpc']['exceptions'] = []

    # Base exceptions.
    instrumentation['java.grpc']['exceptions'].append(
        {'name': 'io.grpc.StatusRuntimeException',
         'metadata': {
             'cause': '',
             'code': 'UNAVAILABLE'
         }
         }
    )

    instrumentation['java.grpc']['exceptions'].append(
        {'name': 'io.grpc.StatusRuntimeException',
         'metadata': {
             'cause': '',
             'code': 'DEADLINE_EXCEEDED'
         }
         }
    )

    # TODO: Extended exceptions.


def add_java_webclient_exceptions():
    # Setup.
    instrumentation['java.WebClient'] = {}
    instrumentation['java.WebClient']['pattern'] = "WebClient\\.(GET|PUT|POST|HEAD)"
    instrumentation['java.WebClient']['exceptions'] = []

    # Base exceptions.
    instrumentation['java.WebClient']['exceptions'].append(
        {'name': 'com.linecorp.armeria.client.UnprocessedRequestException',
         'metadata': {
             'cause': 'io.netty.channel.ConnectTimeoutException'
         }
         }
    )

    # TODO: Extended exceptions.


def add_python_requests_exceptions():
    # Setup.
    instrumentation['python.requests'] = {}
    instrumentation['python.requests']['pattern'] = "requests\\.(get|put|post|head)"
    instrumentation['python.requests']['exceptions'] = []

    # Base exceptions.
    instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.ConnectionError'})

    if os.environ.get('CHECK_TIMEOUTS', ''):
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.Timeout',
                                                                 'restrictions': 'timeout',
                                                                 'metadata': {
                                                                     'sleep': "@expr(metadata['timeout'])+0.001",
                                                                     'abort': False}})
    else:
        instrumentation['python.requests']['exceptions'].append(
            {'name': 'requests.exceptions.Timeout', 'restrictions': 'timeout'})

    if os.environ.get('TIMEOUT_REQUEST_OCCURS', ''):
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.Timeout',
                                                                 'restrictions': 'timeout',
                                                                 'metadata': {'abort': False}})

    # Extended exceptions.
    if os.environ.get('EXTENDED_EXCEPTIONS', ''):
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.HTTPError'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.ProxyError'})
        instrumentation['python.requests']['exceptions'].append(
            {'name': 'requests.exceptions.SSLError', 'restrictions': 'ssl'})
        instrumentation['python.requests']['exceptions'].append(
            {'name': 'requests.exceptions.ReadTimeout', 'restrictions': 'timeout'})
        instrumentation['python.requests']['exceptions'].append(
            {'name': 'requests.exceptions.ConnectTimeout', 'restrictions': 'timeout'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.URLRequired'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.TooManyRedirects'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.MissingSchema'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.InvalidSchema'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.InvalidURL'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.InvalidHeader'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.InvalidProxyURL'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.ChunkedEncodingError'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.ContentDecodingError'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.StreamConsumedError'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.RetryError'})
        instrumentation['python.requests']['exceptions'].append({'name': 'requests.exceptions.UnrewindableBodyError'})


def add_python_grpc_exceptions():
    # Setup.
    instrumentation['python.grpc'] = {}
    instrumentation['python.grpc']['pattern'] = "grpc\\.insecure\_channel"
    instrumentation['python.grpc']['exceptions'] = []

    # Base exceptions.
    instrumentation['python.grpc']['exceptions'].append(
        {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'UNAVAILABLE'}})
    instrumentation['python.grpc']['exceptions'].append(
        {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'DEADLINE_EXCEEDED'}})

    # Extended exceptions.
    if os.environ.get('EXTENDED_EXCEPTIONS', ''):
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'CANCELLED'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'UNKNOWN'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'INVALID_ARGUMENT'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'NOT_FOUND'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'ALREADY_EXISTS'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'PERMISSION_DENIED'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'RESOURCE_EXHAUSTED'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'FAILED_PRECONDITION'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'ABORTED'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'OUT_OF_RANGE'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'INTERNAL'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'DATA_LOSS'}})
        instrumentation['python.grpc']['exceptions'].append(
            {'name': 'grpc._channel._InactiveRpcError', 'metadata': {'code': 'UNAUTHENTICATED'}})


def java_header_to_status_code(constant):
    if constant == "FORBIDDEN":
        return '403'
    elif constant == "NOT_FOUND":
        return '404'
    elif constant == "SERVICE_UNAVAILABLE":
        return '503'
    elif constant == "INTERNAL_SERVER_ERROR":
        return '500'
    elif constant == "OK":
        return '200'
    else:
        print("Found constant with no match: " + constant)
        raise Exception("Analysis failed: unknown java header constant.")


def exception_to_status_code(exception):
    if exception == "Forbidden":
        return '403'
    elif exception == "NotFound":
        return '404'
    elif exception == "ServiceUnavailable":
        return '503'
    elif exception == "NotImplementedError":
        return '500'
    elif exception == "InternalServerError":
        return '500'
    else:
        print("Found exception with no match: " + exception)
        raise Exception("Analysis failed: unknown exception type.")


def analyze_java(service, filename):
    # Add generic HTTP 500 Internal Server Error.
    general_failure_type = {
        'return_value': {
            'status_code': '500'
        }
    }

    for services_and_errors in instrumentation['http']['errors']:
        if services_and_errors['service_name'] == service:
            if general_failure_type not in services_and_errors['types']:
                info("* identified HTTP error: " + str(general_failure_type))
                services_and_errors['types'].append(general_failure_type)

    # Get http specific errors.
    file = open(filename, "r")
    for line in file:
        z = re.match(r'.*HttpStatus.(\w*).*', line)
        if z is not None:
            for match in z.groups():
                if match:
                    status_code = java_header_to_status_code(match)
                    if status_code != "200":
                        # Add generic HTTP 500 Internal Server Error.
                        failure_type = {
                            'return_value': {
                                'status_code': java_header_to_status_code(match)
                            }
                        }

                        for services_and_errors in instrumentation['http']['errors']:
                            if services_and_errors['service_name'] == service:
                                if failure_type not in services_and_errors['types']:
                                    info("* identified HTTP error: " + str(failure_type))
                                    services_and_errors['types'].append(failure_type)

        z = re.match(r'.*[^Http]Status\.(\w*).*', line)
        if z is not None:
            for match in z.groups():
                if match:
                    # Just say exception -- this exception name will be determined by the client library.
                    failure_type = {'exception': {'metadata': {'code': str(match)}}}

                    for services_and_errors in instrumentation['grpc']['errors']:
                        if services_and_errors['service_name'] == service:
                            if failure_type not in services_and_errors['types']:
                                info("* identified GRPC error: " + str(failure_type))
                                services_and_errors['types'].append(failure_type)


def analyze_python(service, filename):
    # Get specific failures for this module.
    with open(filename, "r") as source:
        tree = ast.parse(source.read())
        analyzer = Analyzer()
        analyzer.set_service(service)
        analyzer.visit(tree)

    # Add generic HTTP 500 Internal Server Error.
    general_failure_type = {
        'return_value': {
            'status_code': '500'
        }
    }

    for services_and_errors in instrumentation['http']['errors']:
        if services_and_errors['service_name'] == service:
            if general_failure_type not in services_and_errors['types']:
                info("* identified HTTP error: " + str(general_failure_type))
                services_and_errors['types'].append(general_failure_type)

    # Get pb2 specific errors.
    file = open(filename, "r")
    for line in file:
        z = re.match(r'.*code_pb2.(\w*).*', line)
        if z is not None:
            for match in z.groups():
                if match:
                    # Just say exception -- this exception name will be determined by the client library.
                    failure_type = {'exception': {'metadata': {'code': str(match)}}}

                    for services_and_errors in instrumentation['grpc']['errors']:
                        if services_and_errors['service_name'] == service:
                            if failure_type not in services_and_errors['types']:
                                info("* identified GRPC error: " + str(failure_type))
                                services_and_errors['types'].append(failure_type)


class Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.service = None

    def init(self):
        pass

    def set_service(self, service):
        self.service = service

    def visit_Raise(self, node):
        exception = None

        if isinstance(node.exc, ast.Name):
            exception = node.exc.id
        elif isinstance(node.exc, ast.Call):
            call = node.exc
            if isinstance(call.func, ast.Name):
                exception = call.func.id

        if exception is None:
            raise Exception("Analysis failed: unknown raise.")
        else:
            for services_and_errors in instrumentation['http']['errors']:
                if services_and_errors['service_name'] == self.service:
                    new_type = {
                        'return_value': {
                            'status_code': exception_to_status_code(exception)
                        }
                    }

                    if 'types' in services_and_errors:
                        if new_type not in services_and_errors['types']:
                            info("* identified HTTP error: " + str(new_type))

                            services_and_errors['types'].append(new_type)
                    else:
                        info("* identified HTTP error: " + str(new_type))

                        services_and_errors['types'] = []
                        services_and_errors['types'].append(new_type)

        self.generic_visit(node)


def analyze_services_directory(output, directory):
    global services
    global instrumentation

    ##################################################################################################################
    # Add default exception types for client code.
    ##################################################################################################################

    # Add Python grpc callsite exceptions.
    add_python_grpc_exceptions()

    # Add Python requests callsite exceptions.
    add_python_requests_exceptions()

    # Add Java WebClient callsite exceptions.
    add_java_webclient_exceptions()

    # Add Java grpc callsite exceptions.
    add_java_grpc_exceptions()

    ##################################################################################################################
    # Fill out placeholder information for parsable file.
    ##################################################################################################################

    if 'http' not in instrumentation:
        instrumentation['http'] = {}
        instrumentation['http']['pattern'] = "(((requests\\.(get|put|post|head))|(WebClient\\.(GET|PUT|POST|HEAD))))"

    if 'grpc' not in instrumentation:
        instrumentation['grpc'] = {}
        instrumentation['grpc']['pattern'] = "((grpc\\.insecure\_channel)|(.*Service/.*))"

    if 'errors' not in instrumentation['http']:
        instrumentation['http']['errors'] = []

    if 'errors' not in instrumentation['grpc']:
        instrumentation['grpc']['errors'] = []

    ##################################################################################################################
    # Analyze each service.
    ##################################################################################################################

    # Find each service.
    info("About to analyze directory: " + directory)

    for filename in os.listdir(directory):
        qualified_filename = os.path.join(directory, filename)
        isdir = os.path.isdir(qualified_filename)
        info("* found service implementation: {}".format(qualified_filename))
        if isdir:
            services.append(filename)

    info("")
    info("Found services: " + str(services))
    info("")

    # Add placeholder structure for all services.
    for service in services:
        instrumentation['http']['errors'].append({'service_name': service, 'types': []})
        instrumentation['grpc']['errors'].append({'service_name': service, 'types': []})

    for service in services:
        service_directory = os.path.join(directory, service)
        info("Analyzing service {} at directory {}".format(service, service_directory))

        for root, dirs, files in os.walk(service_directory):
            path = root.split(os.sep)

            for file in files:
                filename = os.path.join("/".join(path), file)

                # Ensure we skip Filibuster instrumentation code.
                if "services/" + service + "/filibuster" not in filename and 'FilibusterServer.java' not in filename:

                    # Python file.
                    if re.match(r'.*.py$', filename) is not None and 'test_' not in filename:
                        info("* starting analysis of Python file: " + filename)
                        analyze_python(service, filename)

                    # Java file.
                    # TODO
                    if re.match(r'.*.java$', filename) is not None and 'Test' not in filename:
                        info("* starting analysis of Java file: " + filename)
                        analyze_java(service, filename)

        info("")

    with open(output, 'w') as outfile:
        info("Writing output file: " + output)
        json.dump(instrumentation, outfile, indent=2)
        info("Done.")
