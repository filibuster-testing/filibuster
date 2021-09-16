import json

from filibuster.logger import info, debug


def should_fail_request_with(request, requests_to_fail):
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
        info(
            "Counterexample found. Running the following counterexample: {}.".format(counterexample['functional_test']))
        f.close()
    except IOError:
        raise Exception("No counterexample found at {}; aborting.".format(path))
    return counterexample
