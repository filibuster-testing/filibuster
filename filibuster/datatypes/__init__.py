import json


class TestExecution:
    @staticmethod
    def filter_request_for_log(request):
        log_keys_to_keep = ['generated_id',
                            'args',
                            'kwargs',
                            'module',
                            'method',
                            'callsite_line',
                            'callsite_file',
                            'metadata',
                            'source_service_name',
                            'full_traceback',
                            'vclock',
                            'origin_vclock',
                            'execution_index']

        new_request = {}
        for key in request:
            if key in log_keys_to_keep:
                new_request[key] = request[key]
        return new_request

    @staticmethod
    def filter_request_for_failures(request):
        failure_keys_to_keep = ['execution_index',
                                'forced_exception',
                                'failure_metadata',
                                'args']

        new_request = {}
        for key in request:
            if key in failure_keys_to_keep:
                new_request[key] = request[key]
        return new_request

    @staticmethod
    def from_json(json_test_execution):
        loaded_json = json.loads(json_test_execution)
        te = TestExecution(loaded_json['log'], loaded_json['failures'])
        te.response_log = loaded_json['response_log']
        return te

    @staticmethod
    def same_call_as_request_log_call(le, rle):
        return (le['module'] == rle['module']) and \
               (le['method'] == rle['method']) and \
               (le['args'] == rle['args']) and \
               (le['kwargs'] == rle['kwargs']) and \
               (le['full_traceback'] == rle['full_traceback']) and \
               (le['execution_index'] == rle['execution_index'])

    def __init__(self, log, failures, **kwargs):
        # Raw log and failures.
        self._log = log
        self._failures = failures

        # Prune log into a generic log that can be compared.
        self.log = []
        for l_entry in log:
            self.log.append(TestExecution.filter_request_for_log(l_entry))

        # Prune failures into a generic log that can be compared.
        self.failures = []
        for f in failures:
            self.failures.append(TestExecution.filter_request_for_failures(f))

        # If this test execution contains actual responses...
        self.response_log = None

        if 'completed' in kwargs and kwargs['completed'] is True:
            self.response_log = []

            for l_entry in log:
                target_service_name = l_entry.get('target_service_name', None)

                if 'retcon' in kwargs:
                    retcon_set = kwargs['retcon']

                    if target_service_name is None:
                        for te in retcon_set:
                            for l2 in te.response_log:
                                # Is this the same call?
                                if TestExecution.same_call_as_request_log_call(l_entry, l2):
                                    # If we hit this URL in the past and found the dynamic binding for this service:
                                    # it's probably the same for this execution, so retcon the target_service_name.
                                    target_service_name = l2['target_service_name']
                                    break
                            if target_service_name is not None:
                                break

                # Assume if we haven't been able to post-populate this, it's going to a non-Filibuster instrumented
                # service.
                if target_service_name is None:
                    target_service_name = 'external'

                # Did we actually make this request or generate the error with fault injection?
                fault_injection = False
                failure_l_entry = None

                for f in failures:
                    if f['execution_index'] == l_entry['execution_index']:
                        fault_injection = True
                        failure_l_entry = f

                # Construct log line.
                response_log_entry = {
                    'callsite_line': l_entry.get('callsite_line'),
                    'callsite_file': l_entry.get('callsite_file'),

                    'execution_index': l_entry.get('execution_index'),
                    'full_traceback': l_entry.get('full_traceback', None),

                    'module': l_entry.get('module'),
                    'method': l_entry.get('method'),
                    'args': l_entry.get('args'),
                    'kwargs': l_entry.get('kwargs'),
                    'metadata': l_entry.get('metadata', None),

                    'vclock': l_entry.get('vclock'),
                    'origin_vclock': l_entry.get('origin_vclock'),

                    'source_service_name': l_entry.get('source_service_name'),
                    'target_service_name': str(target_service_name),

                    'generated_id': l_entry['generated_id'],

                    'return_value': l_entry.get('return_value', None),
                    'exception': l_entry.get('exception', None),
                    'fault_injection': fault_injection,
                }

                if fault_injection:
                    response_log_entry['failure_metadata'] = failure_l_entry.get('failure_metadata')
                    response_log_entry['forced_exception'] = failure_l_entry.get('forced_exception')

                self.response_log.append(response_log_entry)

    def __eq__(self, other):
        if not isinstance(other, TestExecution):
            # don't attempt to compare against unrelated types
            return NotImplemented

        return self.log == other.log and self.failures == other.failures

    def __hash__(self):
        # necessary for instances to behave sanely in dicts and sets.
        return hash((self.log, self.failures))

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)


class ServerState:
    def __init__(self):
        self.service_request_log = []
        self.seen_first_request_from_mapping = {}
        self.generated_id_incr = -1
