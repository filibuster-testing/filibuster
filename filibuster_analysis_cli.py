import click

from filibuster.analysis import analyze_services_directory
from filibuster.logger import info


@click.command()
@click.option('--output-file', required=True, type=str,
              help='File to write the instrumentation output to.')
@click.option('--services-directory', required=True, type=str,
              help='Directory containing service implementations, '
                   'one directory for each service named for the '
                   'service, containing the implementation.')
def analyze(output_file, services_directory):
    """Generate an analysis file for an application for use with Filibuster."""

    analyze_services_directory(output_file, services_directory)


if __name__ == '__main__':
    analyze()
