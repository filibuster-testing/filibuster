import os
import click
from os.path import abspath
from filibuster.server import start_filibuster_server_and_run_test

DEFAULT_ANALYSIS_FILE = "default-analysis.json"


# Adapted from: https://bit.ly/3xMXKnq
class Mutex(click.Option):
    def __init__(self, *args, **kwargs):
        self.not_required_if:list = kwargs.pop("not_required_if")

        assert self.not_required_if, "'not_required_if' parameter required"
        kwargs["help"] = (kwargs.get("help", "") + " Option is mutually exclusive with " + ", ".join(self.not_required_if) + ".").strip()
        super(Mutex, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        current_opt:bool = self.name in opts
        for mutex_opt in self.not_required_if:
            if mutex_opt in opts:
                if current_opt:
                    raise click.UsageError("Illegal usage: '" + str(self.name) + "' is mutually exclusive with " + str(mutex_opt) + ".")
                else:
                    self.prompt = None
        return super(Mutex, self).handle_parse_result(ctx, opts, args)


@click.command()
@click.option('--functional-test', cls=Mutex, not_required_if=["gradle-test"], type=str, help='Functional test file.')
@click.option('--gradle-test', cls=Mutex, not_required_if=["functional-test"], type=str, help='Gradle test name.')
@click.option('--java-debug', type=bool, is_flag=True, help='Pause for remote debug attach each test execution.')
@click.option('--java-logging', type=bool, is_flag=True, help='Enable debug output with Gradle.')
@click.option('--analysis-file', default="default-analysis.json", type=str, help='Analysis file.')
@click.option('--counterexample-file', type=str, help='Counterexample file to run.')
@click.option('--only-initial-execution', type=bool, is_flag=True, help='Only run a fault-free execution of the test.')
@click.option('--disable-dynamic-reduction', type=bool, is_flag=True, help='Disable dynamic reduction.')
@click.option('--forced-failure', type=int, help='Force failure at iteration X to generate counterexample file.')
def test(functional_test,
         gradle_test,
         java_debug,
         java_logging,
         analysis_file,
         counterexample_file,
         only_initial_execution,
         disable_dynamic_reduction,
         forced_failure):
    """Test a microservice application using Filibuster."""

    # Resolve full path of analysis file.
    if analysis_file == DEFAULT_ANALYSIS_FILE:
        abs_analysis_file = abspath(os.path.dirname(os.path.realpath(__file__)) + "/" + analysis_file)
    else:
        abs_analysis_file = analysis_file

    if java_logging:
        java_logging_opt = "-i"
    else:
        java_logging_opt = ""

    if java_debug:
        java_debug_opt = "--debug-jvm"
    else:
        java_debug_opt = ""

    if gradle_test is not None:
        # TODO: make conditional
        os.system("ps auxwww | grep 'org.gradle.launcher.daemon.bootstrap.GradleDaemon' | awk '{print $2}' | xargs kill -9")

        # TODO: make conditional
        os.system("ps auxwww | grep 'worker.org.gradle.process.internal.worker.GradleWorkerMain' | awk '{print $2}' | xargs kill -9")

        test_to_execute = "./gradlew --no-daemon {} test {} --tests '{}'".format(java_logging_opt, java_debug_opt, gradle_test)
    else:
        test_to_execute = functional_test

    start_filibuster_server_and_run_test(test_to_execute,
                                         abs_analysis_file,
                                         counterexample_file,
                                         only_initial_execution,
                                         disable_dynamic_reduction,
                                         forced_failure)


if __name__ == '__main__':
    test()
