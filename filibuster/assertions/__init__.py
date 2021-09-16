import requests

FILIBUSTER_HOST = "127.0.0.1"
FILIBUSTER_PORT = "5005"


def was_fault_injected():
    uri = "http://{}:{}/fault-injected".format(FILIBUSTER_HOST, FILIBUSTER_PORT)
    response = requests.get(uri)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        raise Exception("Cannot connect to the Filibuster server.")


def was_fault_injected_on(service_name):
    uri = "http://{}:{}/fault-injected/{}".format(FILIBUSTER_HOST, FILIBUSTER_PORT, service_name)
    response = requests.get(uri)

    if response.status_code == 200:
        response_json = response.json()
        return response_json['result']
    else:
        raise Exception("Cannot connect to the Filibuster server.")