from filibuster.logger import info, debug


def print_requests(test_execution):
    for entry in test_execution.log:
        info("gen_id: {} ".format(str(entry['generated_id'])))
        info("  source_service_name: " + str(entry['source_service_name']))
        info("  module: " + str(entry['module']))
        info("  method: " + str(entry['method']))
        info("  args: " + str(entry['args']))
        info("  kwargs: " + str(entry['kwargs']))
        info("  vclock: " + str(entry['vclock']))
        info("  origin_vclock: " + str(entry['origin_vclock']))
        info("  execution_index: " + str(entry['execution_index']))

        for failure in test_execution.failures:
            if failure['execution_index'] == entry['execution_index']:
                if 'forced_exception' in failure and failure['forced_exception'] is not None:
                    info("* Failed with exception: " + str(failure['forced_exception']))
                else:
                    info("* Failed with metadata: " + str(list(failure['failure_metadata'].items())))

        info("")


def print_log_for_test_execution(test_execution):
    debug("")
    debug("Log: ")
    for le in test_execution.log:
        debug("{}".format(le))
    if len(test_execution.log) == 0:
        debug("None.")


def print_unique_response_paths(test_executions_ran):
    i = 0
    info("Unique response paths:")
    info("")
    for test_execution in test_executions_ran:
        i = i + 1
        info("=====================================================================================")
        j = 0
        info("Path: " + str(i))
        for p in test_execution.response_log:
            info(" {}: {} => {}; args: {}, kwargs: {}, vclock: {}, origin-vclock: {}".format(
                str(j),
                str(p['source_service_name']),
                str(p['target_service_name']),
                str(p['args']),
                str(p['kwargs']),
                str(p['vclock']),
                str(p['origin_vclock'])))
            j = j + 1
        info("")
    info("")


def print_test_executions_actually_pruned(test_executions_pruned, pruned=None):
    info("")
    info("Test executions actually pruned:")

    test_number = 0
    for test_execution in test_executions_pruned:
        test_number = test_number + 1
        if pruned is not None:
            describe_test_execution(test_execution, test_number, pruned=(test_number in pruned))
        else:
            describe_test_execution(test_execution, test_number, pruned=False)

    if len(test_executions_pruned) == 0:
        info("None.")

    info("")


def print_test_executions_actually_ran(test_executions_ran, pruned=None):
    info("Test executions actually ran:")

    test_number = 0
    for test_execution in test_executions_ran:
        test_number = test_number + 1
        if pruned is not None:
            describe_test_execution(test_execution, test_number, pruned=(test_number in pruned))
        else:
            describe_test_execution(test_execution, test_number, pruned=False)
    info("")


def describe_test_execution(test_execution, test_number, pruned):
    info("")
    info("=====================================================================================")
    if test_number is not None:
        if pruned:
            info("Test number: " + str(test_number) + " (pruned) ")
        else:
            info("Test number: " + str(test_number))
    else:
        info("Test")

    info("")

    # Print the log for the test execution.
    print_log_for_test_execution(test_execution)

    # Print the requests.
    print_requests(test_execution)

    info("")
    info("Failures for this execution:")
    for failure in test_execution.failures:
        execution_index = failure['execution_index']

        if 'forced_exception' in failure and failure['forced_exception'] is not None:
            info(str(execution_index) + ": " + str(failure['forced_exception']))
        else:
            info(str(execution_index) + ": " + str(list(failure['failure_metadata'].items())))
    if len(test_execution.failures) == 0:
        info("None.")

    info("=====================================================================================")
