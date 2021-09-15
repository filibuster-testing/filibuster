from json import dumps, loads

from filibuster.logger import debug


def vclock_new():
    clock = {}
    return clock


def vclock_increment(clock, actor):
    if actor in clock:
        clock[actor] = clock[actor] + 1
    else:
        clock[actor] = 1

    return clock


def vclock_tostring(clock):
    return dumps(clock)


def vclock_fromstring(serialized):
    loaded = loads(str(serialized))
    return loaded


# Check if clocks are equal.
def vclock_equals(clock1, clock2):
    # First, check that both clocks have the same keys.
    clock1_keys = clock1.keys()
    clock2_keys = clock2.keys()
    if clock1_keys == clock2_keys:
        return False

    # Verify that they have the same values for each key.
    for key in clock1:
        if clock1[key] != clock2[key]:
            return False

    return True


# Merge.
def vclock_merge(clock1, clock2):
    new_clock = vclock_new()

    for key in clock1:
        if key not in clock2:
            new_clock[key] = clock1[key]
        else:
            new_clock[key] = max(clock1[key], clock2[key])

    for key in clock2:
        if key not in clock1:
            new_clock[key] = clock2[key]

    return new_clock


# Does clock2 descend clock1?
def vclock_descends(clock1, clock2):
    debug("vclock compare entering")
    debug("clock1: " + str(clock1))
    debug("clock2: " + str(clock2))

    clock2_at_least_equal_to_clock1 = True

    # First, make sure that every entry in clock1 exists in clock2 and is leq.
    for key in clock1:
        # Does the key exist in clock2?
        if key not in clock2:
            clock2_at_least_equal_to_clock1 = False
            break
        else:
            # If it does, make sure it's leq then clock2.
            if not clock2[key] >= clock1[key]:
                clock2_at_least_equal_to_clock1 = False
                break

    debug("clock2_at_least_equal_to_clock1: " + str(clock2_at_least_equal_to_clock1))

    # Then, make sure at least one clock in clock2 is greater than the one in clock1.
    clock2_greater_in_single_clock = False

    for key in clock2:
        # If clock2 has a key clock1 doesn't have, then it is.
        if key not in clock1:
            clock2_greater_in_single_clock = True
            break
        # Otherwise, the lamport clock in clock2 should be greater than it in clock1
        else:
            if clock2[key] > clock1[key]:
                clock2_greater_in_single_clock = True
                break

    debug("clock2_greater_in_single_clock: " + str(clock2_greater_in_single_clock))

    # Both conditions have to be true.
    return clock2_greater_in_single_clock and clock2_at_least_equal_to_clock1
