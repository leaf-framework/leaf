from leaf.adapters.equipment_adapter import AbstractInterpreter


class MockInterpreter(AbstractInterpreter):
    def __init__(self, error_holder=None):
        super().__init__(error_holder=error_holder)

    def metadata(self, data):
        return data

    def measurement(self, data: list[str]):
        return data

    def simulate(self):
        return super().simulate()
