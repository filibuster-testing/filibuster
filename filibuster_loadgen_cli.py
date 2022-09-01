import os
import json
import click
from os.path import abspath

from filibuster.logger import warning, error
from filibuster.server import start_filibuster_server_and_run_multi_threaded_test


@click.command()
@click.option('--functional-test', required=True, type=str, help='Functional test to run.')
@click.option('--analysis-file', default="default-analysis.json", type=str, help='Analysis file.')
@click.option('--counterexample-file', required=True, type=str, help='Counterexample file to reproduce.')
@click.option('--concurrency', required=True, type=int, help='Number of concurrent load generators.')
@click.option('--num-requests', required=True, type=int, help='Number of requests for each load generator.')
@click.option('--max-request-latency-for-failure',
              type=float,
              help='Maximum request latency before request is considered failure (seconds.)')
@click.option('--failure-percentage', required=True, type=int, help='Percentage of requests to fail (as integer.)')
@click.option('--before-script', type=str, help='Script to run before starting loadgen testing for initial setup.')
@click.option('--after-script', type=str, help='Script to run after loadgen testing for final assertions.')
@click.option('--setup-script', type=str, help='Script runs every iteration, prior to execution of the functional test.')
@click.option('--teardown-script', type=str, help='Script runs every iteration, after execution of the functional test.')
def loadgen(functional_test, analysis_file, counterexample_file, concurrency, num_requests, max_request_latency_for_failure, failure_percentage, before_script, after_script, setup_script, teardown_script):
    """Generate load for a given counterexample."""

    # TODO: also need to add some configuration for the pause between each request.

    # Resolve full path of analysis file.
    abs_analysis_file = abspath(os.path.dirname(os.path.realpath(__file__)) + "/" + analysis_file)

    print("counterexample_file: " + str(counterexample_file))

    # CSM 2022-03-09: Start temporary changes for proof of concept.

    # Read supplied counterexample file.
    f = open(counterexample_file)
    counterexample = json.load(f)
    f.close()

    # Add desired failure percentage into the counterexample file as metadata.
    counterexample['failure_percentage'] = failure_percentage

    # Write out new counterexample file that is supplied to Filibuster.
    #
    # This is a global configuration that applies to all faults in the file.  Anything more specific would
    # have to be written into the actual test execution specifically.
    #
    # TODO: add percentage failure to the metadata in the file.
    # TODO: both of these things should be done with an external tool, so we can remove the failure-percentage option from this one.
    #
    new_counterexample_file = "/tmp/counterexample.json"
    with open(new_counterexample_file, 'w') as counterexample_file_output:
        json.dump(counterexample, counterexample_file_output)

    if before_script is not None:
        before_script_exit_code = os.WEXITSTATUS(os.system(before_script))

        if before_script_exit_code != 0:
            error("Before script failed!  Please fix before continuing.")
            exit(1)

    # CSM 2022-03-09: End temporary changes for proof of concept.

    # Run a multi-threaded test.
    start_filibuster_server_and_run_multi_threaded_test(
        functional_test, abs_analysis_file, new_counterexample_file, concurrency, num_requests, max_request_latency_for_failure, setup_script, teardown_script)

    # CSM 2022-03-09: Start temporary changes for proof of concept.

    if after_script is not None:
        after_script_exit_code = os.WEXITSTATUS(os.system(after_script))

        if after_script_exit_code != 0:
            error("After script failed!  This could indicate an assertion failure.")
            exit(1)

    # CSM 2022-03-09: End temporary changes for proof of concept.

    # exit_code = os.WEXITSTATUS(os.system(functional_test))


if __name__ == '__main__':
    loadgen()
