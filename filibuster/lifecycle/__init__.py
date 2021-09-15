import os
import time
import requests
import threading
import subprocess

from filibuster.logger import debug, notice

TIMEOUT_ITERS = 100
SLEEP = 1


def services():
    value = os.getenv("SERVICES")
    value = value.replace('"', '').replace('\'', '')
    services = value.split()
    return services


def num_services_running(services):
    num_running = len(services)
    for service in services:
        if not service_running(service):
            debug("! service " + service + " not yet running!")
            num_running -= 1
    return num_running


def wait_for_num_services_running(services, num_running, waiting_message):
    timeout = TIMEOUT_ITERS
    while num_services_running(services) != num_running:
        debug("Filibuster server waiting for {} to {}.".format(services, waiting_message))
        debug("=> num_running: " + str(num_running))
        debug("=> num_services_running(services): " + str(num_services_running(services)))
        time.sleep(SLEEP)
        timeout -= 1
        if timeout == 0:
            debug("Filibuster server timed out waiting for {} to {}.".format(services, waiting_message))
            exit(1)


def wait_for_services_to_stop(services):
    wait_for_num_services_running(services, 0, "stop")


def wait_for_services_to_start(services):
    wait_for_num_services_running(services, len(services), "start")


def service_running(service):
    name = service[0]
    host = service[1]
    port = service[2]
    base_uri = "http://{}:{}".format(host, str(port))

    # Jaeger will pass the health check only because health-check reroutes to /search.
    debug("checking service's health-check: " + name)
    try:
        response = requests.get(
            "{}/health-check".format(base_uri, timeout=60))
        if response.status_code == 200:
            return True
        else:
            return False
    except requests.exceptions.ConnectionError:
        debug("! connection error")
        return False
    except requests.exceptions.Timeout:
        debug("! timeout")
        return False


def start_filibuster_server_thread(app):
    class Server(threading.Thread):
        def __init__(self):
            threading.Thread.__init__(self)

        def run(self):
            app.run(port=5005, host="0.0.0.0")

    server_thread = Server()
    server_thread.setDaemon(True)
    server_thread.start()