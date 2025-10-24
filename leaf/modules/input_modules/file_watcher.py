import csv
import errno
import fnmatch
import os
import sys
import time
from datetime import datetime
from typing import Callable
from typing import List
from typing import Optional
from typing import Union

from leaf_register.metadata import MetadataManager
from watchdog.events import FileSystemEvent
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

# Use PollingObserver on macOS when running in forked processes (e.g., pytest)
# to avoid CoreFoundation fork safety issues with FSEvents
if sys.platform == 'darwin' and 'pytest' in sys.modules:
    Observer = PollingObserver

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.error_handler.exceptions import InputError
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


def _read_csv(fp: str, encodings=["utf-8", "latin-1"], 
             delimiters=[";", ",", "\t", "|"]):
    if not isinstance(delimiters,list):
        delimiters = [delimiters]
    for encoding in encodings:
        for delim in delimiters:
            try:
                with open(fp, "r", encoding=encoding) as f:
                    reader = csv.reader(f, delimiter=delim)
                    data = list(reader)
                    if data and len(data[0]) > 1:
                        return data
            except (csv.Error, UnicodeDecodeError, FileNotFoundError):
                continue
    return None


def _read_txt(fp: str) -> str:
    with open(fp, "r", encoding="utf-8") as file:
        return file.read()

file_readers = {
    ".csv": lambda fp: _read_csv(fp, delimiters=[";", ",", "\t", "|"]),
    ".tsv": lambda fp: _read_csv(fp, delimiters="\t"),
    ".txt": _read_txt,
}


class FileWatcher(FileSystemEventHandler, EventWatcher):
    """
    Monitors a specific file for creation, modification, and deletion events.
    Utilises the `watchdog` library for event monitoring and triggers callbacks
    for each event type.
    """

    def __init__(
        self,
        paths: Union[str, List[str]],
        metadata_manager: MetadataManager,
        callbacks: Optional[List[Callable[[str, str], None]]] = None,
        error_holder: Optional[ErrorHolder] = None,
        return_data: Optional[bool] = True,
        filenames: Optional[Union[str, List[str]]] = None
    ) -> None:
        """
        Initialise FileWatcher.

        Args:
            paths (Union[str, List[str]]): One or more directories to monitor.
            metadata_manager (MetadataManager): Metadata manager for associated data.
            callbacks (Optional[List[Callable]]): Callbacks for file events.
            error_holder (Optional[ErrorHolder]): Optional error holder for capturing exceptions.
            return_data (Optional[bool]): Returns the data (content of file) is true else, return filename.

        Raises:
            AdapterBuildError: Raised if the provided file path is invalid.
        """
        super().__init__(
            metadata_manager=metadata_manager,
            callbacks=callbacks,
            error_holder=error_holder,
        )
        if paths is None:
            excp = AdapterBuildError("No directory provided")
            self._handle_exception(excp)
        self._paths = [paths] if isinstance(paths, str) else paths
        self._paths = [p if p != "" else "." for p in self._paths]
        if isinstance(filenames, str):
            self._filenames = [filenames]
        else:
            self._filenames = filenames
        self._return_data = return_data
        self._observing = False

        self._last_created: Optional[float] = None
        self._last_modified: Optional[float] = None
        self._debounce_delay: float = 0.75

        self._term_map = {
            self.on_created: metadata_manager.experiment.start,
            self.on_modified: metadata_manager.experiment.measurement,
            self.on_deleted: metadata_manager.experiment.stop,
        }

    def start(self) -> None:
        """
        Begin observing the file path for events.
        Ensures a single observer instance is active.
        """
        if self._observing:
            logger.warning("FileWatcher is already running.")
            return
        else:
            logger.info("Starting FileWatcher...")

        try:
            self._observer = Observer()
            for path in self._paths:
                logger.debug(f"Watching path: {path}")
                self._observer.schedule(self, path, recursive=False)
            if not self._observer.is_alive():
                logger.debug("Starting observer thread...")
                self._observer.start()
            super().start()
            self._observing = True
            self._last_created = None
            self._last_modified = None
            logger.info("FileWatcher started.")
        except OSError as e:
            self._handle_exception(self._create_input_error(e))
        except Exception as ex:
            self._handle_exception(InputError(f"Error starting observer: {ex}"))

    def stop(self) -> None:
        """
        Stop observing the file for events.
        Terminates the observer thread safely.
        """
        if not self._observing:
            logger.warning("FileWatcher is not running.")
            return
        logger.info("Stopping FileWatcher...")

        self._observer.stop()
        self._observer.join()
        super().stop()
        self._observing = False
        logger.info("FileWatcher stopped.")

    def on_created(self, event: FileSystemEvent) -> None:
        """
        Handle file creation events and trigger start callbacks.

        Args:
            event (FileSystemEvent): Event object indicating a file creation.
        """
        logger.debug(f"Received file creation event: {event}")
        data = {}
        try:
            fp = self._get_filepath(event)
            if fp is None:
                return
            self._last_created = time.time()
            if self._return_data:
                data = self._read_file_by_extension(fp)
            else:
                data = fp
        except Exception as e:
            self._file_event_exception(e, "creation")
        self._dispatch_callback(self._term_map[self.on_created], data)

    def on_modified(self, event: FileSystemEvent) -> None:
        """
        Handle file modification events and trigger measurement callbacks.

        Args:
            event (FileSystemEvent): Event object indicating a file modification.
        """
        logger.debug(f"Received file modification event: {event}")
        try:
            fp = self._get_filepath(event)
            if fp is None or not self._is_last_modified():
                logger.debug("Modification event ignored due to debounce delay or file not found.")
                return
            if self._return_data:
                logger.debug("Reading file content...")
                data = self._read_file_by_extension(fp)
            else:
                logger.debug("Returning file path instead of content...")
                data = fp
        except Exception as e:
            self._file_event_exception(e, "modification")
        self._dispatch_callback(self._term_map[self.on_modified], data)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """
        Handle file deletion events and trigger stop callbacks.

        Args:
            event (FileSystemEvent): Event object indicating a file deletion.
        """
        logger.debug(f"Received file deletion event: {event}")
        fp = self._get_filepath(event,file_exists=False)
        if fp is None:
            return

        if self._return_data:
            data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            data = fp
        self._dispatch_callback(self._term_map[self.on_deleted], 
                                data)

    def _get_filepath(self, event: FileSystemEvent,
                      file_exists = True) -> Optional[str]:
        """
        Retrieve the full file path for the event if it matches the watched file.

        Args:
            event (FileSystemEvent): Event object containing file information.

        Returns:
            Optional[str]: Full file path if it matches the watched file, otherwise None.
        """
        if not os.path.isfile(event.src_path) and file_exists:
            return None

        filename = os.path.basename(event.src_path)
        if self._filenames:
            for pattern in self._filenames:
                if pattern.startswith("."):
                    if filename.endswith(pattern):
                        return event.src_path
                elif fnmatch.fnmatch(filename, pattern):
                    return event.src_path
            return None
        return event.src_path

    def _is_last_modified(self) -> bool:
        """
        Determine if the file modification is outside the debounce delay.

        Returns:
            bool: True if the modification event is outside the debounce period, False otherwise.
        """
        current_time = time.time()
        if self._last_created and (current_time - self._last_created) <= self._debounce_delay:
            return False
        if self._last_modified is None or (current_time - self._last_modified) > self._debounce_delay:
            self._last_modified = current_time
            return True
        return False

    def _read_file_by_extension(self, fp: str):
        ext = os.path.splitext(fp)[1].lower()
        reader = file_readers.get(ext)

        if reader:
            return reader(fp)

        try:
            with open(fp, "r", encoding="utf-8") as file:
                return file.read()
        except Exception as e:
            msg = f"Failed to read file '{fp}' as plain text: {e}"
            self._handle_exception(InputError(msg))
            return None

    def _file_event_exception(self, error: Exception, event_type: str) -> None:
        """
        Log and handle exceptions during file events.

        Args:
            error (Exception): Exception encountered during event handling.
            event_type (str): Type of event that triggered the exception.
        """
        if isinstance(error, FileNotFoundError):
            message = f"File not found during {event_type} event"
        elif isinstance(error, PermissionError):
            message = f"Permission denied when accessing file during {event_type} event"
        elif isinstance(error, IOError):
            message = f"I/O error during {event_type} event: {error}"
        elif isinstance(error, UnicodeDecodeError):
            message = f"Encoding error while reading file during {event_type} event: {error}"
        else:
            message = f"Error during {event_type} event: {error}"
        self._handle_exception(InputError(message))



    def _create_input_error(self, e: OSError) -> InputError:
        """
        Map OS errors to custom InputError messages.

        Args:
            e (OSError): Operating system error encountered.

        Returns:
            InputError: Custom error based on the OS error code.
        """
        if e.errno == errno.EACCES:
            return InputError("Permission denied: Unable to access one or more watch paths")
        elif e.errno == errno.ENOSPC:
            return InputError("Inotify watch limit reached. Cannot add more watches")
        elif e.errno == errno.ENOENT:
            return InputError("One or more watch paths do not exist")
        return InputError(f"Unexpected OS error: {e}")