import math

from _queue import Empty
from multiprocessing import Process, Queue

from flask import Flask, jsonify, request

import re
import os
import sys
import copy
import time
import json

from timeit import default_timer as timer

from filibuster.datatypes import TestExecution, ServerState

from filibuster.debugging import print_test_executions_actually_ran, print_test_executions_actually_pruned, \
    describe_test_execution

from filibuster.reduce_dynamic import should_prune as reduce_dynamic_should_prune

from filibuster.lifecycle import start_filibuster_server_thread

from filibuster.lifecycle import wait_for_services_to_start

from filibuster.stack import Stack

from filibuster.logger import error, warning, notice, info, debug

from filibuster.server_helpers import should_fail_request_with, load_counterexample

app = Flask(__name__)

COUNTEREXAMPLE_PATH = "counterexample.json"

if os.environ.get('ONLY_INITIAL_EXECUTION', ''):
    MAX_NUM_TESTS = 1
else:
    if os.environ.get("NUM_TESTS", ""):
        MAX_NUM_TESTS = int(os.environ.get("NUM_TESTS", ""))
    else:
        MAX_NUM_TESTS = -1

if os.environ.get('PRINT_RESPONSES', ''):
    PRINT_RESPONSES = True
else:
    PRINT_RESPONSES = False

if os.environ.get('DETAILED_FLASK_LOGGING', ''):
    pass
else:
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

# Global state.

server_state = ServerState()
requests_to_fail = []
current_test_execution: TestExecution = None
current_test_execution_batch = []
test_executions_ran = []
test_executions_scheduled = Stack()
cumulative_dynamic_pruning_time_in_ms = 0
cumulative_test_generation_time_in_ms = 0
mean_dynamic_pruning_time_in_ms = []
instrumentation_data = None
counterexample = None
failure_percentage = None
iteration_complete = False
iteration_exit_code = 0
server_only_mode = False
should_terminate_immediately = False
teardown_completed = False


def run_test(functional_test, only_initial_execution, disable_dynamic_reduction, forced_failure, should_suppress_combinations, setup_script, teardown_script):
    global current_test_execution
    global test_executions_scheduled
    global requests_to_fail
    global current_test_execution_batch
    global test_executions_ran
    global counterexample
    global suppress_combinations
    global server_only_mode
    global teardown_completed

    suppress_combinations = should_suppress_combinations

    iteration = 1

    test_start_time = time.time()

    notice("Running test " + str(functional_test))

    # Keep track of the tests that we have run.
    test_executions_ran = []

    # Keep track of test executions we've tried to run.
    test_executions_attempted = []

    # Keep track of executions pruned.
    test_executions_pruned = []

    # Keep track of the tests that we need to run.
    test_executions_scheduled = Stack()

    # server only?
    if functional_test is None:
        server_only_mode = True

    if counterexample:  # Schedule a test execution for the counterexample.
        counterexample_test_execution = TestExecution.from_json(counterexample['TestExecution'])
        test_executions_scheduled.push(counterexample_test_execution)
    else:  # Run initial execution only when we are running all tests (when there is no counterexample to debug).
        # Run initial execution.
        info("Running the initial non-failing execution (test 1) " + str(functional_test))

        # Reset requests to fail.
        requests_to_fail = []

        teardown_completed = False

        # Run initial test, which should pass.
        run_test_with_fresh_state(setup_script, teardown_script, functional_test, iteration, counterexample is not None, False, forced_failure)

        # Get log of requests that were made and return:
        # This execution will be the execution where everything passes and there
        # are no failures.
        initial_test_execution = TestExecution(server_state.service_request_log, [])
        next_test_execution = initial_test_execution

        # Add to list of ran executions.
        test_executions_attempted.append(initial_test_execution)
        initial_actual_test_execution = TestExecution(server_state.service_request_log, requests_to_fail, completed=True)
        test_executions_ran.append(initial_actual_test_execution)

        info("[DONE] Running initial non-failing execution (test 1)")

        # Barrier to know when all of the AfterEach statements are done.
        wait_for_teardown_completed()

    # Loop until list is exhausted.
    if not only_initial_execution:
        while test_executions_scheduled.size() > 0:
            teardown_completed = False

            if os.environ.get("PAUSE_BETWEEN", ""):
                input("Press Enter to start next test...")

            iteration = iteration + 1

            # Quit early if we want to bound the number of tests.
            if MAX_NUM_TESTS != -1 and iteration > MAX_NUM_TESTS:
                break

            # Get next test.
            next_test_execution = test_executions_scheduled.pop()

            info("Running test " + (str(iteration)))
            info("Total tests pruned so far: " + str(len(test_executions_pruned)))
            info("Total tests remaining: " + str(test_executions_scheduled.size()))

            # Reset requests to fail.
            requests_to_fail = next_test_execution.failures

            # Set current test execution.
            notice("Setting current test execution.")
            current_test_execution = next_test_execution
            notice("Set current test execution to next execution.")

            describe_test_execution(current_test_execution, str(iteration), False)

            if counterexample:
                # We have to run.
                run_test_with_fresh_state(setup_script, teardown_script, functional_test, iteration, True, False)

                # Add to history list.
                current_test_execution = TestExecution(server_state.service_request_log,
                                                       requests_to_fail,
                                                       completed=True,
                                                       retcon=test_executions_ran)
                test_executions_attempted.append(next_test_execution)
                test_executions_ran.append(current_test_execution)
            else:
                if not disable_dynamic_reduction:
                    global cumulative_dynamic_pruning_time_in_ms
                    global mean_dynamic_pruning_time_in_ms
                    global cumulative_test_generation_time_in_ms

                    reduction_start_time = time.time_ns()
                    dynamic_full_history_reduce = reduce_dynamic_should_prune(current_test_execution, test_executions_ran)
                    reduction_end_time = time.time_ns()

                    dynamic_pruning_time_in_ms = (reduction_end_time - reduction_start_time) / (10 ** 6)
                    num_tests_compared_to = len(test_executions_ran)
                    cumulative_dynamic_pruning_time_in_ms += dynamic_pruning_time_in_ms
                    if num_tests_compared_to:
                        mean_dynamic_pruning_time_in_ms.append(dynamic_pruning_time_in_ms / num_tests_compared_to)

                    if not dynamic_full_history_reduce:
                        # Run the test.
                        run_test_with_fresh_state(setup_script, teardown_script, functional_test, iteration, counterexample is not None, False, forced_failure)

                        # Add to history list.
                        current_test_execution = TestExecution(server_state.service_request_log,
                                                               requests_to_fail,
                                                               completed=True,
                                                               retcon=test_executions_ran)
                        test_executions_attempted.append(next_test_execution)
                        test_executions_ran.append(current_test_execution)
                    else:
                        test_executions_pruned.append(current_test_execution)
                else:
                    # Run the test.
                    run_test_with_fresh_state(setup_script, teardown_script, functional_test, iteration, counterexample is not None, False, forced_failure)

                    # Add to history list.
                    current_test_execution = TestExecution(server_state.service_request_log,
                                                           requests_to_fail,
                                                           completed=True,
                                                           retcon=test_executions_ran)
                    test_executions_attempted.append(next_test_execution)
                    test_executions_ran.append(current_test_execution)

            # Barrier to know when all of the AfterEach statements are done.
            wait_for_teardown_completed()

            # Done as part of previous step, before unblocking thread.
            # current_test_execution = None
            info("Test " + (str(iteration)) + " completed.")

    current_test_execution = None
    notice("Completed testing " + str(functional_test))
    info("")

    # Print test executions that actually ran.
    # print_test_executions_actually_ran(test_executions_ran)

    # Compute elapsed time.
    test_end_time = time.time()
    elapsed = test_end_time - test_start_time

    # Print test executions that actually pruned.
    print_test_executions_actually_pruned(test_executions_pruned)

    # Print out statistics.
    info("")
    info("Number of tests attempted: " + str(len(test_executions_attempted)))
    info("Number of test executions ran: " + str(len(test_executions_ran)))
    info("Test executions pruned with only dynamic pruning: " + str(len(test_executions_pruned)))
    info("Total tests: " + str(len(test_executions_ran) + len(test_executions_pruned)))
    info("")
    info("Time elapsed: " + str(elapsed) + " seconds.")


def should_schedule(test_execution, additional_test_executions):
    global test_executions_scheduled
    global current_test_execution_batch
    global test_executions_ran

    # Only schedule an execution iff:
    # a.) We haven't scheduled it yet during this iteration.
    # b.) We haven't scheduled it in a previous execution.
    # c.) We aren't currently executing it in the current batch of tests.
    # d.) We haven't already ran it.
    return test_execution not in additional_test_executions \
        and not test_executions_scheduled.contains(test_execution) \
        and test_execution not in current_test_execution_batch \
        and test_execution not in test_executions_ran


def generate_additional_test_executions(generated_id, execution_index, instrumentation_type, analysis_file):
    # If there is a counterexample, run only the test that failed for quick debugging.
    global counterexample

    if counterexample:
        return

    global current_test_execution
    global test_executions_scheduled
    global current_test_execution_batch
    global requests_to_fail
    global suppress_combinations

    # List of additional test executions.
    additional_test_executions = []

    # Get information about the current execution.
    log = server_state.service_request_log
    failures = requests_to_fail

    # Get the request
    req = None
    for req_ in server_state.service_request_log:
        if str(generated_id) == str(req_['generated_id']):
            req = req_
            break
    if req is None:
        raise Exception("Something went fucking wrong!")

    # If this is as far as we reached so far...
    if req == server_state.service_request_log[-1]:
        # Is this request already failed?
        already_failed = False

        # If so, skip looking for an alternative failure.
        for failure in failures:
            if str(failure['execution_index']) == str(req['execution_index']):
                already_failed = True
                break

        # Iterate list of faults.
        instrumentation = read_analysis_file(analysis_file)

        for module in instrumentation:
            pattern = instrumentation[module]['pattern']
            matcher = re.compile(pattern)
            callsite = "{}.{}".format(req['module'], req['method'])
            matching = matcher.match(callsite)

            # warning("module: " + module)
            # warning("matching: " + str(matching))

            if matching is not None:
                # Exception testing.
                if instrumentation_type == 'invocation':
                    if 'exceptions' in instrumentation[module]:
                        for exception in instrumentation[module]['exceptions']:
                            debug("Checking if we need to inject exception: " + str(exception['name']))

                            if 'restrictions' in exception:
                                restriction = exception['restrictions']

                                if not (restriction in req['metadata'] and req['metadata'][restriction] is not None):
                                    continue

                            if not already_failed:
                                # For this execution, we need to fail everything we did before to get here
                                # but, we also need to fail this additional one req as well.
                                # (also, add the exception so we know what to throw later.)
                                new_req = copy.deepcopy(req)
                                new_req['forced_exception'] = {}
                                new_req['forced_exception']['name'] = exception['name']

                                if 'metadata' in exception:
                                    new_req['forced_exception']['metadata'] = {}

                                    for key in exception['metadata']:
                                        # TODO: we have to do this programmatically, we need to parse the expression.
                                        if exception['metadata'][key] == "@expr(metadata['timeout']-1)":
                                            new_req['forced_exception']['metadata'][key] = (
                                                        req['metadata']['timeout'] - 1)
                                        # TODO: we have to do this programmatically, we need to parse the expression.
                                        elif exception['metadata'][key] == "@expr(metadata['timeout']+1)":
                                            new_req['forced_exception']['metadata'][key] = (
                                                        req['metadata']['timeout'] + 1)
                                        # TODO: we have to do this programmatically, we need to parse the expression.
                                        elif exception['metadata'][key] == "@expr(metadata['timeout'])":
                                            new_req['forced_exception']['metadata'][key] = (req['metadata']['timeout'])
                                        else:
                                            new_req['forced_exception']['metadata'][key] = exception['metadata'][key]
                                else:
                                    new_req['forced_exception']['metadata'] = {}

                                new_failures = copy.deepcopy(failures)
                                new_failures.append(TestExecution.filter_request_for_failures(new_req))
                                new_failures = sorted(new_failures, key=lambda k: k['execution_index'])

                                new_execution = TestExecution(log, new_failures)
                                if should_schedule(new_execution, additional_test_executions):
                                    if new_execution not in additional_test_executions:
                                        debug("Adding req failure for request: " + str(req['execution_index']))
                                        debug("=> exception: " + str(exception))
                                        additional_test_executions.append(new_execution)

                # Error testing.
                if instrumentation_type == 'request_received':
                    if 'errors' in instrumentation[module]:
                        for error in instrumentation[module]['errors']:
                            if 'target_service_name' in req and req['target_service_name'] is not None:
                                target_service_name = req['target_service_name']

                                service_pattern = error['service_name']
                                service_matcher = re.compile(service_pattern)
                                service_matching = service_matcher.match(target_service_name)

                                if service_matching is not None:
                                    for type in error['types']:
                                        # warning("Checking if we need to inject error: " + str(type))
                                        # warning("already_failed: " + str(already_failed))

                                        if not already_failed:
                                            # For this execution, we need to fail everything we did before to get here
                                            # but, we also need to fail this additional one request as well.
                                            # (also, add the exception so we know what to throw later.)
                                            new_req = copy.deepcopy(req)
                                            new_req['failure_metadata'] = {}
                                            for key in type:
                                                new_req['failure_metadata'][key] = type[key]
                                            new_failures = copy.deepcopy(failures)
                                            new_failures.append(TestExecution.filter_request_for_failures(new_req))
                                            new_failures = sorted(new_failures, key=lambda k: k['execution_index'])

                                            new_execution = TestExecution(log, new_failures)
                                            if should_schedule(new_execution, additional_test_executions):
                                                if new_execution not in additional_test_executions:
                                                    debug("Adding req failure for request: " + str(
                                                        req['execution_index']))
                                                    debug("=> failure description: " + str(type))
                                                    additional_test_executions.append(new_execution)
                            else:
                                warning("Request does not have a target service, it's made outside of the system.")

        append_quantity = 0

        for te in additional_test_executions:
            if suppress_combinations is True:
                if len(te.failures) == 1:
                    test_executions_scheduled.push(te)
                    append_quantity = append_quantity + 1
                else:
                    pass
            else:
                test_executions_scheduled.push(te)
                append_quantity = append_quantity + 1
        # warning("Added " + str(append_quantity) + " tests.")
    else:
        warning("Ignoring, path we discovered is a root of a path we already discovered.")

    return True


def read_analysis_file(analysis_file):
    with open(analysis_file, "r") as f:
        return json.load(f)


# Test functions

def run_test_with_fresh_state(setup_script, teardown_script, functional_test, iteration, counterexample_provided=False, loadgen=False, forced_failure=None):
    # Reset state.
    global test_executions_ran
    global server_state
    global iteration_complete
    global iteration_exit_code
    global server_only_mode

    server_state = ServerState()

    if setup_script is not None:
        setup_script_exit_code = os.WEXITSTATUS(os.system(setup_script))

        if setup_script_exit_code != 0:
            error("Setup script failed!  Please fix before continuing.")
            exit(1)

    # Run initial test, which should pass.
    exit_code = 0

    if functional_test is None:
        notice("Waiting for external test to complete.")

        if wait_until(lambda: check_iteration_complete(), 100):
            iteration_complete = False
            exit_code = iteration_exit_code
        else:
            error("Something didn't go right!")
            exit_code = 1
    else:
        exit_code = os.WEXITSTATUS(os.system(functional_test))

    if teardown_script is not None:
        teardown_script_exit_code = os.WEXITSTATUS(os.system(teardown_script))

        if teardown_script_exit_code != 0:
            error("Teardown script failed!  Please fix before continuing.")
            exit(1)

    if not loadgen:
        if server_only_mode:
            # Do nothing right now, just assume a pass.
            print("Not stopping server, it was a server only mode failure.")
            pass
        elif exit_code or str(forced_failure) == str(iteration):
            print("Handling non-server only mode failure.")

            # Allow replay of failed test
            if not current_test_execution:  # Errored on initial test. This shouldn't happen.
                raise Exception(
                    "Failed on initial test execution of {}; not injecting faults.".format(functional_test))

            if not counterexample_provided:
                # Rewrite test execution as a completed test before going to JSON.
                counterexample_test_execution = TestExecution(server_state.service_request_log,
                                                              requests_to_fail,
                                                              completed=True,
                                                              retcon=test_executions_ran)

                counterexample_json = {
                    "functional_test": functional_test,
                    "TestExecution": counterexample_test_execution.to_json()
                }
                with open(COUNTEREXAMPLE_PATH, 'w') as counterexample_file_output:
                    json.dump(counterexample_json, counterexample_file_output)

                error("Test failed; counterexample file written: " + COUNTEREXAMPLE_PATH)
                exit(1)
            else:
                error("Counterexample reproduced.")
                exit(1)
    else:
        # info("Test execution returned: " + str(exit_code))
        return exit_code


# Filibuster server Flask functions

@app.route("/", methods=['GET'])
def hello():
    return jsonify({
        "uri": "/",
        "subresource_uris": {
            "create": "filibuster/create",
            "update": "filibuster/update"
        }
    })


@app.route("/filibuster/complete-iteration/<iteration>/exception/<exception>", methods=['POST'])
def complete_iteration(iteration, exception):
    global iteration_complete
    global iteration_exit_code

    iteration_complete = True

    if exception == "0":
        exception_p = False
        iteration_exit_code = 0
    else:
        exception_p = True
        iteration_exit_code = 1

    print("Exception: " + str(exception))
    print("Exception_p: " + str(exception_p))
    print("Iteration complete: " + str(iteration))

    return jsonify({})


# Is the current iteration an actual test?
@app.route("/filibuster/has-next-iteration/<iteration>/<caller>", methods=['GET'])
def has_next_iteration(iteration, caller):
    global current_test_execution
    global test_executions_scheduled

    if current_test_execution is not None:
        # print("current set, returning true")
        print("has_next_iteration called: " + str(iteration) + " for caller " + str(caller))
        return jsonify({"has-next-iteration": True})

    elif current_test_execution is None and test_executions_scheduled.size() > 0:
        # Wait until current test execution is set.
        # print("current not yet set, waiting.")
        wait_until_current_test_execution()
        # print("current now set, returning true")
        print("has_next_iteration called: " + str(iteration) + " for caller " + str(caller))
        return jsonify({"has-next-iteration": True})

    else:
        # print("returning false")
        return jsonify({"has-next-iteration": False})


@app.route("/filibuster/fault-injected", methods=['GET'])
def faults_injected_index():
    global counterexample
    global current_test_execution

    fault_injected = False

    if counterexample:
        if len(current_test_execution.failures) > 0:
            fault_injected = True
    else:
        if current_test_execution:
            if len(current_test_execution.failures) > 0:
                fault_injected = True

    print("wasFaultInjected() called and is returning: " + str(fault_injected))
    return jsonify({"result": fault_injected})


# TODO: really not efficient, needs to be fixed with memoization
@app.route("/filibuster/fault-injected/service/<service_name>", methods=['GET'])
def faults_injected_by_service(service_name):
    global counterexample
    global test_executions_ran
    global current_test_execution

    found = False

    if counterexample:
        # If using a counterexample, it should contain a log that maps
        # execution indexes to their target services.
        #
        for item in current_test_execution.failures:
            for le in current_test_execution.response_log:
                if le['execution_index'] == item['execution_index']:
                    if le['target_service_name'] == service_name:
                        found = True
                        break
    else:
        # This work is duplicated here, unfortunately. *After* the test finishes,
        # we compute this information for every single call made in the test
        # from all of the previously run tests.
        #
        # When we choose to inject faults, we don't know the service that we are injecting
        # the fault on, so we have to go find another execution where we do know.
        #
        # From there, we know.
        #
        if current_test_execution:  # on initial, fault-free execution, this value isn't set.
            for item in current_test_execution.failures:
                for te in test_executions_ran:
                    for le in te.response_log:
                        if le['execution_index'] == item['execution_index']:
                            if le['target_service_name'] == service_name:
                                found = True
                                break

    return jsonify({"result": found})


# TODO: really not efficient, needs to be fixed with memoization
@app.route("/filibuster/fault-injected/method/<part1>/<part2>", methods=['GET'])
def faults_injected_by_method_two_part(part1, part2):
    global counterexample
    global test_executions_ran
    global current_test_execution

    method_name = None

    if part2 is None:
        method_name = part1
    else:
        method_name = part1 + "/" + part2

    if method_name is None:
        print("HELLO")
        return jsonify({"result": False})

    found = False

    if counterexample:
        # If using a counterexample, it should contain a log that maps
        # execution indexes to their target services.
        #
        for item in current_test_execution.failures:
            for le in current_test_execution.response_log:
                if le['execution_index'] == item['execution_index']:
                    if le['method'] == method_name:
                        found = True
                        break
    else:
        # This work is duplicated here, unfortunately. *After* the test finishes,
        # we compute this information for every single call made in the test
        # from all of the previously run tests.
        #
        # When we choose to inject faults, we don't know the service that we are injecting
        # the fault on, so we have to go find another execution where we do know.
        #
        # From there, we know.
        #
        if current_test_execution:  # on initial, fault-free execution, this value isn't set.
            for item in current_test_execution.failures:
                for te in test_executions_ran:
                    for le in te.response_log:
                        if le['execution_index'] == item['execution_index']:
                            if le['method'] == method_name:
                                found = True
                                break

    print("here, returning: " + str(found))
    return jsonify({"result": found})


@app.route("/health-check", methods=['GET'])
def health_check():
    return jsonify({"status": "OK"})


@app.route("/terminate", methods=['GET'])
def terminate():
    global should_terminate_immediately
    should_terminate_immediately = True
    notice("Terminating server process.")
    return jsonify({})


@app.route("/teardowns-completed/<iteration>", methods=['GET'])
def teardowns_completed(iteration):
    global teardown_completed
    global current_test_execution

    # This blocks java as soon as beforeEach registers the final afterEach, but needs
    # to be set immediately and not asynchronously otherwise beforeEach will run before
    # we have swapped the test execution.
    if current_test_execution is not None:
        notice("Nulling current test execution because teardown is completed.")
    current_test_execution = None

    teardown_completed = True
    # notice("Teardown completed for iteration: " + str(iteration))
    return jsonify({})


@app.route("/filibuster/new-test-execution/<service_name>", methods=['GET'])
def new_test_execution_check(service_name):
    global server_state
    new_test_execution = False
    if service_name not in server_state.seen_first_request_from_mapping:
        server_state.seen_first_request_from_mapping[service_name] = True
        new_test_execution = True

    if PRINT_RESPONSES:
        print("")
        print("** NEW TEST EXECUTION RETURNING WITH PAYLOAD *****************")
        print(json.dumps({"new-test-execution": new_test_execution}, indent=2))
        print("**************************************************************")
        print("")

    return jsonify({"new-test-execution": new_test_execution})


@app.route("/filibuster/create", methods=['PUT'])
def create():
    try:
        global server_state
        global cumulative_test_generation_time_in_ms
        global instrumentation_data
        global failure_percentage

        data = request.get_json()

        if PRINT_RESPONSES:
            print("")
            print("** CREATE CALLED WITH PAYLOAD *****************")
            print(json.dumps(data, indent=2))
            print("***********************************************")
            print("")

        # Update state to reflect the call.
        server_state.generated_id_incr += 1
        data['generated_id'] = server_state.generated_id_incr
        server_state.service_request_log.append(data)

        global requests_to_fail
        failure_request_metadata = should_fail_request_with(data, requests_to_fail, failure_percentage)

        payload = {
            'generated_id': server_state.generated_id_incr,
        }
        if 'execution_index' in data:
            payload['execution_index'] = data['execution_index']

        if failure_request_metadata is not None:
            for key in failure_request_metadata:
                payload[key] = failure_request_metadata[key]

        if 'instrumentation_type' in data and data['instrumentation_type'] == 'invocation':
            gen_id = server_state.service_request_log[-1]['generated_id']
            execution_index = data['execution_index']

            # This is the initial execution.
            if current_test_execution is None:
                execution_start_time = time.time_ns()
                generate_additional_test_executions(gen_id, execution_index, data['instrumentation_type'],
                                                    instrumentation_data)
                execution_end_time = time.time_ns()

                test_generation_time_in_ms = (execution_end_time - execution_start_time) / (10 ** 6)
                cumulative_test_generation_time_in_ms += test_generation_time_in_ms
            else:
                generated_id_found = False

                # If the request was already known, we don't want to FI in it, because
                # we already did when it was originally executed.
                #
                for l in current_test_execution.log:
                    if l == TestExecution.filter_request_for_log(server_state.service_request_log[-1]):
                        generated_id_found = True

                if not generated_id_found:
                    generation_start_time = time.time_ns()
                    generate_additional_test_executions(gen_id, execution_index, data['instrumentation_type'],
                                                        instrumentation_data)
                    generation_end_time = time.time_ns()

                    test_generation_time_in_ms = (generation_end_time - generation_start_time) / (10 ** 6)
                    cumulative_test_generation_time_in_ms += test_generation_time_in_ms

        if PRINT_RESPONSES:
            print("")
            print("** CREATE RETURNING PAYLOAD *******************")
            print(json.dumps(payload, indent=2))
            print("***********************************************")
            print("")

        return jsonify(payload)
    except Exception as e:
        error("Exception when calling CREATE: ")
        print(e, file=sys.stderr)


@app.route("/filibuster/update", methods=['POST'])
def update():
    try:
        global server_state
        global current_test_execution
        global instrumentation_data

        data = request.get_json()

        if PRINT_RESPONSES:
            print("")
            print("** UPDATE CALLED WITH PAYLOAD *****************")
            print(json.dumps(data, indent=2))
            print("***********************************************")
            print("")

        idx = data['generated_id']

        if isinstance(idx, str):
            idx = int(idx)
        if idx < 0 or len(server_state.service_request_log) <= idx:
            # print(server_state.service_request_log)
            # print(str(idx))
            # print(str(idx < 0))
            # print(str(len(server_state.service_request_log)))
            # print(str(len(server_state.service_request_log) <= idx))
            # print("INDEX ERROR ******")
            return jsonify({}) # TODO: This can't be here long term.
            # raise IndexError
        for key in data.keys():
            if key == 'generated_id':
                continue
            if data[key] is not None:
                server_state.service_request_log[idx][key] = data[key]
        # print("HERE1 ******")

        # For each request that we make, we receive *2* updates:
        #
        # 1.) From the remote service, if under instrumentation through Flask. (request_received)
        # 2.) When the call is completed. (invocation_complete)
        #
        if 'instrumentation_type' in data and data['instrumentation_type'] == 'request_received':
            gen_id = data['generated_id']
            execution_index = data['execution_index']

            # This is the initial execution.
            if current_test_execution is None:
                generate_additional_test_executions(gen_id, execution_index, data['instrumentation_type'],
                                                    instrumentation_data)
            else:
                # Request comes in, do we know about it from the log?
                req = None

                # Get the request out of the current log by the id.
                for l in server_state.service_request_log:
                    if str(gen_id) == str(l['generated_id']):
                        req = TestExecution.filter_request_for_log(l)

                if req is None:
                    error("There was a huge problem in Filibuster.  This should never happen!!!!")

                # See if it exists in the current_request_log (the currently executing test.)
                found_in_execution_log = False

                for entry in current_test_execution.log:
                    if entry == req:
                        debug("We've already seen this request before; ignoring.")
                        found_in_execution_log = True
                        break

                if not found_in_execution_log:
                    generate_additional_test_executions(gen_id, execution_index, data['instrumentation_type'],
                                                        instrumentation_data)

        if PRINT_RESPONSES:
            print("")
            print("** UPDATE RETURNING EMPTY PAYLOAD *******************")
            print("*****************************************************")
            print("")

        return jsonify({})
    except Exception as e:
        error("Exception when calling UPDATE: ")
        print(e, file=sys.stderr)


def start_thread(queue, setup_script, teardown_script, functional_test, counterexample_file, num_requests):
    for x in range(num_requests):
        start = timer()
        exit_code = run_test_with_fresh_state(setup_script, teardown_script, functional_test, 0, counterexample_file is not None, True)
        end = timer()
        duration = end - start
        queue.put((exit_code, start, end, duration))


def start_filibuster_server_and_run_multi_threaded_test(functional_test, analysis_file, counterexample_file, concurrency, num_requests, max_request_latency_for_failure, setup_script, teardown_script):
    start_filibuster_server(analysis_file)

    global counterexample
    global requests_to_fail
    global current_test_execution
    global failure_percentage

    if counterexample_file:
        counterexample = load_counterexample(counterexample_file)
        current_test_execution = TestExecution.from_json(counterexample['TestExecution'])
        requests_to_fail = current_test_execution.failures
        if 'failure_percentage' in counterexample:
            failure_percentage = counterexample['failure_percentage']
            debug("failure_percentage: " + str(failure_percentage))

    processes = []
    queue = Queue()

    # Start each worker.
    for x in range(concurrency):
        p = Process(target=start_thread, args=(queue, setup_script, teardown_script, functional_test, counterexample_file, num_requests))
        p.start()
        processes.append(p)

    # Join all of them.
    for x in processes:
        p.join()

    # Wait until all have fully terminated.
    # Why is this necessary? (it is, otherwise, we don't dequeue everything.)
    #
    some_alive = True

    while some_alive:
        some_alive = False
        for x in processes:
            if x.is_alive():
                some_alive = True

    # Flush the queue and build statistics.
    flushed = False

    num_success = 0
    num_failure = 0
    num_exceeded_duration = 0
    exceeded_durations = []
    all_durations = []
    num_dequeued = 0

    while not flushed:
        try:
            (exit_code, start, end, duration) = queue.get_nowait()

            num_dequeued = num_dequeued + 1
            all_durations.append(duration)

            if exit_code:
                num_failure = num_failure + 1
            else:
                if max_request_latency_for_failure is not None and duration >= max_request_latency_for_failure:
                    num_failure = num_failure + 1
                    num_exceeded_duration = num_exceeded_duration + 1
                    exceeded_durations.append(duration)
                else:
                    num_success = num_success + 1
        except Empty:
            flushed = True
            break

    num_total_requests = num_requests * concurrency

    info("--------------- Loadgen Statistics ---------------")
    info("Requests issued (dequeued): \t\t" + str(num_total_requests) + "(" + str(num_dequeued) + ")")
    info("")
    info("Requests successful: \t\t\t" + str(num_success))
    info("Requests failed: \t\t\t\t" + str(num_failure))
    info("Requests failed (duration violation): \t" + str(num_exceeded_duration))
    info("")
    info("Max Request Latency (seconds): \t\t" + str(max_request_latency_for_failure))
    info("")
    info("Request durations (seconds):")
    info("* P0:  " + str(my_percentile(all_durations, 0)))
    info("* P50: " + str(my_percentile(all_durations, 50)))
    info("* P90: " + str(my_percentile(all_durations, 90)))
    info("* P95: " + str(my_percentile(all_durations, 95)))
    info("* P99: " + str(my_percentile(all_durations, 99)))
    info("")
    info("Failure rate: \t\t\t\t" + str((num_failure/num_total_requests) * 100) + "%")
    info("--------------- Loadgen Statistics ---------------")


def start_filibuster_server_and_run_test(functional_test, analysis_file, counterexample_file, only_initial_execution, disable_dynamic_reduction, forced_failure, should_suppress_combinations, setup_script, teardown_script):
    # if functional_test is None:
    #     print("Waiting to kill Filibuster processes (THIS IS WAY HACK BECAUSE SERVER WONT DIE)....")
    #     os.system("lsof -n | grep LISTEN | grep avt-profile-2 | awk '{print $2}' | xargs kill -9")

    start_filibuster_server(analysis_file)

    global counterexample

    if counterexample_file:
        counterexample = load_counterexample(counterexample_file)

    run_test(functional_test, only_initial_execution, disable_dynamic_reduction, forced_failure, should_suppress_combinations, setup_script, teardown_script)

    if server_only_mode:
        wait_indefinitely_until_shutdown()


def start_filibuster_server(analysis_file):
    global instrumentation_data
    instrumentation_data = analysis_file

    start_filibuster_server_thread(app)

    wait_for_services_to_start([('filibuster', '127.0.0.1', 5005)])


def my_percentile(data, percentile):
    n = len(data)
    p = n * percentile / 100
    if p.is_integer():
        return sorted(data)[int(p)]
    else:
        return sorted(data)[int(math.ceil(p)) - 1]


def wait_until(somepredicate, timeout, period=0.25, *args, **kwargs):
    # notice("Waiting until condition met.")
    mustend = time.time() + timeout
    while time.time() < mustend:
        if somepredicate(*args, **kwargs): return True
        time.sleep(period)
    return False


def check_iteration_complete():
    global iteration_complete
    return iteration_complete


def wait_indefinitely_until_shutdown(period=0.25):
    global should_terminate_immediately
    notice("Waiting indefinitely for shutdown.")

    while True:
        if should_terminate_immediately:
            notice("Should terminate immediately set to true!")
            exit(0)

        time.sleep(period)


def wait_for_teardown_completed(period=0.25):
    global teardown_completed
    global current_test_execution
    global server_only_mode

    notice("Waiting for teardown completed: BLOCKED PYTHON WAITING FOR AFTEREACH.")

    if server_only_mode:
        while True:
            if teardown_completed:
                notice("Teardown completed.  Marking teardown_completed.")
                # This unblocks python.
                teardown_completed = False
                break

            time.sleep(period)


def wait_until_current_test_execution(period=0.25):
    global current_test_execution
    notice("Waiting for current test execution.")

    if server_only_mode:
        while True:
            if current_test_execution is not None:
                notice("Current test execution populated: UNBLOCKED JAVA.")
                break

            time.sleep(period)
