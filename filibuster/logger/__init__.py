import os
import sys


class BColors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def error(string):
    print(BColors.FAIL + "[FILIBUSTER] [FAIL]: " + string + BColors.ENDC, file=sys.stderr, flush=True)


def warning(string):
    print(BColors.WARNING + "[FILIBUSTER] [WARNING]: " + string + BColors.ENDC, file=sys.stderr, flush=True)


def notice(string):
    print(BColors.OKGREEN + "[FILIBUSTER] [NOTICE]: " + string + BColors.ENDC, file=sys.stderr, flush=True)


def info(string):
    print(BColors.OKBLUE + "[FILIBUSTER] [INFO]: " + string + BColors.ENDC, file=sys.stderr, flush=True)


def debug(string):
    if os.environ.get("DEBUG", ""):
        print(BColors.OKCYAN + "[FILIBUSTER] [DEBUG]: " + string + BColors.ENDC, file=sys.stderr, flush=True)
