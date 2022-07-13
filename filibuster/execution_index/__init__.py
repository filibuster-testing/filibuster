import json
import os


def execution_index_new():
    # Don't use an actual stack for the callstack, because
    # it's not JSON serializable -- we need to be able to
    # send this in a HTTP header.
    #
    callstack = []
    counters = {}
    return callstack, counters


def execution_index_push(service, execution_index):
    if os.environ.get("EI_DISABLE_PATH_INCLUSION", ""):
        (callstack, counters) = execution_index_new()
    else:
        (callstack, counters) = execution_index

    if os.environ.get("EI_DISABLE_INVOCATION_COUNT", ""):
        counters[service] = 1
    else:
        if service in counters:
            counters[service] = counters[service] + 1
        else:
            counters[service] = 1

    callstack.append((service, counters[service]))

    return callstack, counters


def execution_index_pop(execution_index):
    (callstack, counters) = execution_index

    # Remove last element from the callstack.
    #
    # Compared to the original algorithm that keeps an identifier
    # along with each call on the stack because return statements
    # or exceptions might cause it to return from multiple frames
    # that have to be popped simultaneously -- in our case,
    # we do not need this because we know that we will always return
    # from a call by our instrumentation.
    #

    if len(callstack) <= 0:
        # This indicates a double-pop, which is a problem.
        raise

    callstack = callstack[:-1]

    return callstack, counters


def execution_index_tostring(execution_index):
    (callstack, counters) = execution_index
    return json.dumps(callstack)


def execution_index_fromstring(serialized):
    return json.loads(serialized), {}
