import threading
import traceback

from leaf.error_handler.exceptions import LEAFError


class ErrorHolder:
    """
    A simplified error manager that stores errors once
    and lets you retrieve (and clear) all of them at once.
    """

    def __init__(self, adapter_id: str | None = None):
        """
        Initialize the ErrorHolder instance.

        Args:
            adapter_id (Optional[str]): Optional identifier
                                        for the adapter.
        """
        self._errors: list[dict] = []
        self.lock = threading.Lock()
        self._adapter_id = adapter_id

    def add_error(self, exc: LEAFError) -> None:
        """
        Add an error entry with its traceback.

        Args:
            exc (LEAFError): The exception to add.
        """
        if not isinstance(exc, LEAFError):
            raise TypeError("ErrorHolder only accepts LEAFError exceptions.")
        with self.lock:
            tb = traceback.format_exc()
            error_entry = {"error": exc, "traceback": tb}
            self._errors.append(error_entry)

    def get_unseen_errors(self) -> list[tuple[LEAFError, str]]:
        """
        Retrieve all stored errors and clear the list.

        Returns:
            List[Tuple[Exception, str]]:
                A list of (exception, traceback) tuples.
        """
        with self.lock:
            all_errors = [(err["error"], err["traceback"]) for err in self._errors]
            self._errors.clear()
            return all_errors
