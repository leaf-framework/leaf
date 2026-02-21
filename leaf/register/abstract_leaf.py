from abc import ABC, abstractmethod

from leaf.register.topic_utilities import topic_utilities


class AbstractLeaf(ABC):
    def __init__(self, process_mapping=None):
        self._process_mapping = {}
        if process_mapping is not None:
            for template, processes in process_mapping.items():
                if not isinstance(processes, list):
                    processes = [processes]
                [self.add_process(template, process) for process in processes]

    @abstractmethod
    def process(self, topic, data):
        topic_data = topic_utilities.parse_topic(topic)
        for template, functions in self._process_mapping.items():
            ret_vals = []
            if topic_utilities.is_instance(topic, template):
                for function in functions:
                    ret_vals.append(function(data, **topic_data.parts))
                return ret_vals
        return None

    def add_process(self, template, process):
        if not isinstance(template, str):
            template = template()
        if template not in self._process_mapping:
            self._process_mapping[template] = []
        self._process_mapping[template].append(process)
