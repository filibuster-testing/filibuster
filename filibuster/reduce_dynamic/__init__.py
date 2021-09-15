import hashlib

from filibuster.debugging import describe_test_execution
from filibuster.execution_index import execution_index_new, execution_index_tostring
from filibuster.logger import error, debug, info, warning, notice
from filibuster.vclock import vclock_new


def print_causal_descendents(causal_descendents):
    info("")
    info("Causal descendents (request -> [requests]): ")
    for c in causal_descendents:
        info("")
        info("{}: {}".format(str(c), len(causal_descendents[c])))
        for ei in causal_descendents[c]:
            info("   {}".format(str(ei)))
    if len(causal_descendents) == 0:
        info("None.")


def derive_causal_descendents_from_execution(test_execution):
    causal_descendents = {execution_index_tostring(execution_index_new()): []}

    for entry in test_execution.log:
        # Print out the request.
        debug(str(entry['generated_id']) + ": " + str(entry['args']) + " " + str(entry['kwargs']))
        
        for failure in test_execution.failures:
            if failure['execution_index'] == entry['execution_index']:
                if 'forced_exception' in failure and failure['forced_exception'] is not None:
                    debug("* Failed with exception: " + str(failure['forced_exception']))
                else:
                    debug("* Failed with metadata: " + str(list(failure['failure_metadata'].items())))

        # Find all causal descendents of this request.
        for rle in test_execution.log:
            if 'vclock' not in entry:
                error("vclock not found in response_log_entry: " + str(entry))

            if 'vclock' not in rle:
                error("vclock not found in rle: " + str(rle))

            # This won't be an equality check *when* we do this before executing the request, because we'll have to
            # look at requests_to_fail to see if we are gonna throw an exception.
            # (and callsite, too?  not sure, think about it more.)
            if rle['origin_vclock'] == entry['vclock']:
                rle_execution_index = rle['execution_index']
                entry_execution_index = entry['execution_index']

                if entry_execution_index not in causal_descendents:
                    causal_descendents[entry_execution_index] = []

                causal_descendents[entry_execution_index].append(rle_execution_index)

        if entry['origin_vclock'] == vclock_new():
            entry_execution_index = entry['execution_index']
            causal_descendents[execution_index_tostring(execution_index_new())].append(entry_execution_index)

    return causal_descendents


# Given a test execution with what I'm about to do, make sure that what I've done previously matches that.
def outcomes_match(current_test_execution, previously_ran_completed_request):
    scheduled_request = None

    # Find the same request in the previous execution.
    for l_entry in current_test_execution.log:
        if previously_ran_completed_request['execution_index'] == l_entry['execution_index']:
            scheduled_request = l_entry

    failure = None

    # Find out if we're failing this in the current execution.
    if scheduled_request is not None:
        for f in current_test_execution.failures:
            if f['execution_index'] == scheduled_request['execution_index']:
                failure = f

    # If we are going to fail this request, did it fail in the previous execution the same way?
    if failure is not None:

        # Are we failing with exception?
        if 'forced_exception' in failure and failure['forced_exception'] is not None:
            # If so, we have to meet two conditions:
            # a.) either we've failed it indirectly by failing one of it's dependencies; or
            # b.) we must have failed it directly by forcing the exception.
            # Either way, it had to previously fail.
            if ('forced_exception' in previously_ran_completed_request and previously_ran_completed_request['forced_exception'] is not None) or \
                    ('exception' in previously_ran_completed_request and previously_ran_completed_request['exception'] is not None):

                # If we injected an exception last time, and we're injecting an exception this time:
                #  then, we need to ensure the exception matches exactly.
                if ('forced_exception' in previously_ran_completed_request and previously_ran_completed_request['forced_exception'] is not None) and \
                        ('forced_exception' in failure and failure['forced_exception'] is not None):

                    # Check for exact match here since we're comparing the 'forced_exception' field.
                    return previously_ran_completed_request['forced_exception'] == failure['forced_exception']

                # Otherwise, a fault on a dependency might have caused this service to get an exception:
                else:
                    if 'exception' in previously_ran_completed_request and previously_ran_completed_request['exception'] is not None:
                        # TODO: probably broken if more is reported then sent?
                        return is_subset_match(previously_ran_completed_request['exception'], failure['forced_exception'])
                    else:
                        print("")
                        print("previously_ran_completed_request['exception']")
                        print(str(sorted(previously_ran_completed_request['exception'].items())))
                        print("")
                        print("failure['failure_metadata']['return_value']")
                        print(str(sorted(failure['forced_exception'].items())))
                        print("")

                        return False
            else:
                # Scheduled test is not set to fail.
                return False
        elif 'failure_metadata' in failure and failure['failure_metadata'] is not None:
            # If we are modifying a return value.
            if 'return_value' in previously_ran_completed_request and previously_ran_completed_request['return_value'] is not None and \
               'return_value' in failure['failure_metadata'] and failure['failure_metadata']['return_value'] is not None:
                # TODO: probably broken if more is reported then sent?
                subset_match = is_subset_match(previously_ran_completed_request['return_value'], failure['failure_metadata']['return_value'])
                # direct_match = str(previously_ran_completed_request['return_value']['status_code']) == str(failure['failure_metadata']['return_value']['status_code'])
                warning("subset_match: " + str(subset_match))
                # warning("direct_match: " + str(direct_match))

                if subset_match:
                    return True
                else:
                    warning("We shouldn't be here because this means we matched on EI but the requests were different.")

                    print("")
                    print("subset_match: " + str(subset_match))
                    print("")
                    print("previously_ran_completed_request['return_value']")
                    print(str(sorted(previously_ran_completed_request['return_value'].items())))
                    print("")
                    print("failure['failure_metadata']['return_value']")
                    print(str(sorted(failure['failure_metadata']['return_value'].items())))
                    print("")

                return subset_match
            elif 'exception' in previously_ran_completed_request and previously_ran_completed_request['exception'] is not None and \
                 'exception' in failure['failure_metadata'] and failure['failure_metadata']['exception']:
                # TODO: probably broken if more is reported then sent?
                subset_match = is_subset_match(previously_ran_completed_request['exception'], failure['failure_metadata']['exception'])

                if subset_match is False:
                    print("")
                    print("subset_match: " + str(subset_match))
                    print("")
                    print("previously_ran_completed_request['exception']")
                    print(str(sorted(previously_ran_completed_request['exception'].items())))
                    print("")
                    print("failure['failure_metadata']['exception']")
                    print(str(sorted(failure['failure_metadata']['exception'].items())))
                    print("")

                return subset_match
            else:
                # TODO: add notice, same as L109.
                return False

    # We're not going to fail it this time.
    else:
        # If we injected a failure before, and this time we aren't, then we know it can't be a match.
        if 'fault_injection' in previously_ran_completed_request and previously_ran_completed_request['fault_injection'] is True:
            return False
        else:
            # Since the scheduled request is always going to be a subset of the previous request -- the previous
            # request is purely additive: contains the fault injection boolean, return value, text, status code and
            # exception information, just verify that the scheduled request is a subset of the previous request.
            #
            # This will always be true when we didn't inject a failure before (verified above) and are not
            # injecting a failure now (also, verified above.)
            #
            # TODO: probably broken if more is reported then sent?
            subset_match = is_subset_match(previously_ran_completed_request, scheduled_request)

            if subset_match:
                return True
            else:
                warning("We shouldn't be here because this means we matched on EI but the requests were different.")
                print("")
                print("subset_match: " + str(subset_match))
                print("")
                print("SCHEDULED REQUEST ******")
                print(str(sorted(scheduled_request.items())))
                print("")
                print("FAILURE ****************")
                print(str(failure))
                print("")
                print("PREVIOUSLY RAN *********")
                print(str(sorted(previously_ran_completed_request.items())))
                print("")

                describe_test_execution(current_test_execution, None, False)

                return False

# Is B is a subset of A?
def is_subset_match(A, B):
    return all(A.get(key, None) == val for key, val in B.items())

def should_prune(test_execution, test_executions_ran):
    # Derive causal descendents for the current request and print.
    causal_descendents = derive_causal_descendents_from_execution(test_execution)
    # print_causal_descendents(causal_descendents)
    # info("")

    all_causal_found = True

    for c in causal_descendents:
        # info("Need to find {} requests in a single trace with the same outcome.".format(len(causal_descendents[c])))

        i = 0

        found = False

        for te in test_executions_ran:
            i = i + 1
            all_found = True

            for d in causal_descendents[c]:
                looking_for_execution_index = d
                found_execution_index = False

                for l_entry in te.response_log:

                    # Request is in this previous test execution.
                    if l_entry['execution_index'] == looking_for_execution_index:
                        if outcomes_match(test_execution, l_entry):
                            found_execution_index = True
                        else:
                            # info("-> ! found match for execution index, but outcomes didn't match")
                            pass

                if not found_execution_index:
                    all_found = False

            # info("-> all_found for previous execution {} is: {}".format(str(i), str(all_found)))

            if all_found:
                found = True
                break

        if not found:
            all_causal_found = False

    # info("")
    # info("All causal found: {}".format(all_causal_found))

    return all_causal_found
