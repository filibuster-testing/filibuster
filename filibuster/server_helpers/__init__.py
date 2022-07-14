import json
from random import uniform

from filibuster.logger import info, debug

def should_fail_request_with(request, requests_to_fail):
    return should_fail_request_with(request, requests_to_fail, 100)

def should_fail_request_with(request, requests_to_fail, failure_percentage):
    if failure_percentage is not None and failure_percentage != 100:
        # TODO: should we seed?
        random_number = uniform(0, 100)
        info("Failure Percentage: " + str(failure_percentage))
        info("Uniform random: " + str(random_number))
        if random_number > failure_percentage: # not <=
            return None

    debug("Request: \n" + str(request))
    debug("Requests to fail: \n" + str(requests_to_fail))
    for request_to_fail in requests_to_fail:
        if request['execution_index'] == request_to_fail['execution_index']:
            debug("Failing request.")
            return request_to_fail
    debug("Not failing request.")
    return None


def load_counterexample(path):
    try:
        f = open(path)
        counterexample = json.load(f)
        info("Counterexample loaded from file.")
        f.close()
    except IOError:
        raise Exception("No counterexample found at {}; aborting.".format(path))
    return counterexample
