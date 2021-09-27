import os
import click
from os.path import abspath
from filibuster.server import start_filibuster_server_and_run_test


@click.command()
@click.option('--coverage', type=bool, is_flag=True, help="Compute coverage for Python applications.")
def coverage(coverage):
    """Compute coverage for an application."""

    coverage_command = abspath(os.path.dirname(os.path.realpath(__file__)) + "/bin/aggregate-python-coverage.sh")
    os.system(coverage_command)


if __name__ == '__main__':
    coverage()
