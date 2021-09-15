import click
from filibuster.server import start_filibuster_server


@click.command()
@click.option('--functional-test', required=True, type=str, help='Functional test to run.')
@click.option('--analysis-file', required=True, type=str, help='Analysis file.')
def test(functional_test, analysis_file):
    """Test a microservice application using Filibuster."""
    start_filibuster_server(functional_test, analysis_file)


if __name__ == '__main__':
    test()