import os
import click
from os.path import abspath
from filibuster.server import start_filibuster_server_and_run_test


@click.command()
@click.option('--functional-test', required=True, type=str, help='Functional test to run.')
@click.option('--analysis-file', default="default-analysis.json", type=str, help='Analysis file.')
@click.option('--counterexample-file', type=str, help='Counterexample file to run.')
def test(functional_test, analysis_file, counterexample_file):
    """Test a microservice application using Filibuster."""

    # Resolve full path of analysis file.
    abs_analysis_file = abspath(os.path.dirname(os.path.realpath(__file__)) + "/" + analysis_file)

    start_filibuster_server_and_run_test(functional_test, abs_analysis_file, counterexample_file)


if __name__ == '__main__':
    test()