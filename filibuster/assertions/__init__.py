import requests

from filibuster.logger import error

FILIBUSTER_HOST = "127.0.0.1"
FILIBUSTER_PORT = "5005"
TIMEOUT = 10


def was_fault_injected():
    uri = "http://{}:{}/filibuster/fault-injected".format(FILIBUSTER_HOST, FILIBUSTER_PORT)
    response = requests.get(uri, timeout=TIMEOUT)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        raise Exception("Filibuster endpoint returned: " + str(response.status_code) + " for was_fault_injected.")


def was_fault_injected_on_service(service_name):
    uri = "http://{}:{}/filibuster/fault-injected/service/{}".format(FILIBUSTER_HOST, FILIBUSTER_PORT, service_name)
    response = requests.get(uri, timeout=TIMEOUT)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        raise Exception("Filibuster endpoint returned: " + str(response.status_code) + " for was_fault_injected_on_service.")


def was_fault_injected_on_method(method_name):
    uri = "http://{}:{}/filibuster/fault-injected/method/{}".format(FILIBUSTER_HOST, FILIBUSTER_PORT, method_name)
    response = requests.get(uri, timeout=TIMEOUT)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        raise Exception("Filibuster endpoint returned: " + str(response.status_code) + " for was_fault_injected_on_method.")