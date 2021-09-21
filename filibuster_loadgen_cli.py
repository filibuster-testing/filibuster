import os
import click
from os.path import abspath
from filibuster.server import start_filibuster_server_and_run_multi_threaded_test


@click.command()
@click.option('--functional-test', required=True, type=str, help='Functional test to run.')
@click.option('--analysis-file', default="default-analysis.json", type=str, help='Analysis file.')
@click.option('--counterexample-file', required=True, type=str, help='Counterexample file to reproduce.')
@click.option('--concurrency', required=True, type=int, help='Number of concurrent load generators.')
@click.option('--num-requests', required=True, type=int, help='Number of requests for each load generator.')
@click.option('--max-request-latency-for-failure', type=float, help='Maximum request latency before request is considered failure (seconds.)')
def loadgen(functional_test, analysis_file, counterexample_file, concurrency, num_requests, max_request_latency_for_failure):
    """Test a microservice application using Filibuster."""

    # Resolve full path of analysis file.
    abs_analysis_file = abspath(os.path.dirname(os.path.realpath(__file__)) + "/" + analysis_file)

    # Run a multi-threaded test.
    start_filibuster_server_and_run_multi_threaded_test(
        functional_test, abs_analysis_file, counterexample_file, concurrency, num_requests, max_request_latency_for_failure)


if __name__ == '__main__':
    loadgen()
