_GLOBAL_CONTEXT = {}

def set_value(key, value):
    global _GLOBAL_CONTEXT
    _GLOBAL_CONTEXT[key] = value

def get_value(key):
    global _GLOBAL_CONTEXT
    if key in _GLOBAL_CONTEXT:
        return _GLOBAL_CONTEXT[key]
    else:
        return None