from flask import Flask, jsonify, request

import re
import os
import sys
import copy
import time
import json

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


# Specific testing functions.


def run_test(functional_test, counterexample_file):
    global current_test_execution
    global test_executions_scheduled
    global requests_to_fail
    global current_test_execution_batch
    global test_executions_ran
    global counterexample

    iteration = 0

    if counterexample_file:
        counterexample = load_counterexample(counterexample_file)

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

    if counterexample:  # Schedule a test execution for the counterexample.
        counterexample_test_execution = TestExecution.from_json(counterexample['TestExecution'])
        test_executions_scheduled.push(counterexample_test_execution)
    else:  # Run initial execution only when we are running all tests (when there is no counterexample to debug).
        # Run initial execution.
        info("Running initial non-failing execution (test 1) " + str(functional_test))

        # Reset requests to fail.
        requests_to_fail = []

        # Run initial test, which should pass.
        run_test_with_fresh_state(functional_test, counterexample_file is not None)

        # Get log of requests that were made and return:
        # This execution will be the execution where everything passes and there
        # are no failures.
        initial_test_execution = TestExecution(server_state.service_request_log, [])

        # Add to list of ran executions.
        test_executions_attempted.append(initial_test_execution)
        initial_actual_test_execution = TestExecution(server_state.service_request_log, requests_to_fail,
                                                      completed=True)
        test_executions_ran.append(initial_actual_test_execution)

        info("[DONE] Running initial non-failing execution (test 1)")

        iteration = 1

    # Loop until list is exhausted.
    while test_executions_scheduled.size() > 0:
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
        current_test_execution = next_test_execution

        describe_test_execution(current_test_execution, str(iteration), False)

        if counterexample:
            # We have to run.
            run_test_with_fresh_state(functional_test, counterexample_file is not None)

            # Add to history list.
            current_test_execution = TestExecution(server_state.service_request_log,
                                                   requests_to_fail,
                                                   completed=True,
                                                   retcon=test_executions_ran)
            test_executions_attempted.append(next_test_execution)
            test_executions_ran.append(current_test_execution)
        else:
            if not os.environ.get("DISABLE_DYNAMIC_REDUCTION", ''):
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
                    run_test_with_fresh_state(functional_test, counterexample_file is not None)

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
                run_test_with_fresh_state(functional_test, counterexample_file is not None)

                # Add to history list.
                current_test_execution = TestExecution(server_state.service_request_log,
                                                       requests_to_fail,
                                                       completed=True,
                                                       retcon=test_executions_ran)
                test_executions_attempted.append(next_test_execution)
                test_executions_ran.append(current_test_execution)

        info("Test " + (str(iteration)) + " completed.")

    notice("Completed testing " + str(functional_test))
    info("")

    # Print test executions that actually ran.
    print_test_executions_actually_ran(test_executions_ran)

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
                                        print("KEY IS " + str(key))
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
                                warning(
                                    "Request does not have a target service; request is being made outside of the system.")

        append_quantity = 0

        for te in additional_test_executions:
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

def run_test_with_fresh_state(functional_test, counterexample_provided=False):
    # Reset state.
    global test_executions_ran
    global server_state
    server_state = ServerState()

    exit_code = os.WEXITSTATUS(os.system(functional_test))

    if exit_code:
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

            counterexample = {
                "functional_test": functional_test,
                "TestExecution": counterexample_test_execution.to_json()
            }
            with open(COUNTEREXAMPLE_PATH, 'w') as counterexample_file:
                json.dump(counterexample, counterexample_file)

            error("Test failed; counterexample file written: " + COUNTEREXAMPLE_PATH)
            exit(1)
        else:
            error("Counterexample reproduced.")
            exit(1)


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


@app.route("/fault-injected", methods=['GET'])
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

    return jsonify({"result": fault_injected})


# TODO: really not efficient, needs to be fixed with memoization
@app.route("/fault-injected/<service_name>", methods=['GET'])
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


@app.route("/health-check", methods=['GET'])
def health_check():
    return jsonify({"status": "OK"})


@app.route("/filibuster/new-test-execution/<service_name>", methods=['GET'])
def new_test_execution_check(service_name):
    global server_state
    new_test_execution = False
    if service_name not in server_state.seen_first_request_from_mapping:
        server_state.seen_first_request_from_mapping[service_name] = True
        new_test_execution = True
    return jsonify({"new-test-execution": new_test_execution})


@app.route("/filibuster/create", methods=['PUT'])
def create():
    try:
        global server_state
        global cumulative_test_generation_time_in_ms
        global instrumentation_data

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
        failure_request_metadata = should_fail_request_with(data, requests_to_fail)

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
            raise IndexError
        for key in data.keys():
            if key == 'generated_id':
                continue
            if data[key] is not None:
                server_state.service_request_log[idx][key] = data[key]

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


def start_filibuster_server(functional_test, analysis_file, counterexample_file):
    global instrumentation_data
    instrumentation_data = analysis_file

    start_filibuster_server_thread(app)

    wait_for_services_to_start([('filibuster', '127.0.0.1', 5005)])

    run_test(functional_test, counterexample_file)
