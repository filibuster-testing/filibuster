import requests

from filibuster.logger import error

FILIBUSTER_HOST = "127.0.0.1"
FILIBUSTER_PORT = "5005"
TIMEOUT = 10


def was_fault_injected():
    uri = "http://{}:{}/fault-injected".format(FILIBUSTER_HOST, FILIBUSTER_PORT)
    response = requests.get(uri, timeout=TIMEOUT)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        error("Returning false from was_fault_injected, could not contact Filibuster server.")
        return False


def was_fault_injected_on(service_name):
    uri = "http://{}:{}/fault-injected/{}".format(FILIBUSTER_HOST, FILIBUSTER_PORT, service_name)
    response = requests.get(uri, timeout=TIMEOUT)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        error("Returning false from was_fault_injected_on, could not contact Filibuster server.")
        return False
