import traceback
import re
import hashlib

from filibuster.logger import info, debug

# We're making an assumption here that test files start with test_ (Pytest)
TEST_PREFIX = "test_"

# We're making an assumption here that test files start with test_ (Pytest)
INSTRUMENTATION_PREFIX = "filibuster/instrumentation"

def get_full_traceback_hash(service_name):
    raw_callsite = None

    for line in traceback.format_stack():
        if service_name in line and TEST_PREFIX not in line and INSTRUMENTATION_PREFIX not in line:
            raw_callsite = line
            break

    cs_search = re.compile("File \"(.*)\", line (.*), in")
    callsite = cs_search.search(raw_callsite)

    callsite_file = callsite.group(1)
    callsite_line = callsite.group(2)
    debug("=> callsite_file: " + callsite_file)
    debug("=> callsite_line: " + callsite_line)

    tracebacks = []
    for _traceback in traceback.format_stack():
        raw_quotes = _traceback.split("\"")
        revised_quotes = []
        # Filter the stacktrace only to the filibuster and app code.
        is_filibuster_stacktrace = False
        for quote in raw_quotes:
            # Analyze paths.
            if "/" in quote:
                # Remove information about which python version we are using.
                if "python" in quote:
                    quote = quote.split("python",1)[1] 
                    if "/" in quote and quote[0] != "/":
                        quote = quote.split("/",1)[1]
                # Remove absolute path information and keep things relative only to filibuster.
                elif "filibuster" in quote: 
                    quote = quote.split("filibuster",1)[1]
                    is_filibuster_stacktrace = True
            revised_quotes.append(quote)
        if is_filibuster_stacktrace:
            curr_traceback = "\"".join(revised_quotes)
            tracebacks.append(curr_traceback)

    full_traceback = "\n".join(tracebacks)
    full_traceback_hash = hashlib.md5(full_traceback.encode()).hexdigest()

    return callsite_file, callsite_line, full_traceback_hash