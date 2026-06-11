import csv
import errno
import fnmatch
import os
import time
from collections.abc import Callable
from datetime import datetime
from threading import Timer

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, InputError
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


def _read_csv(fp: str, encodings=None, delimiters=None):
    if encodings is None:
        encodings = ["utf-8", "latin-1"]
    if delimiters is None:
        delimiters = [";", ",", "\t", "|"]
    elif not isinstance(delimiters, list):
        delimiters = [delimiters]
    last_error = None
    for encoding in encodings:
        for delim in delimiters:
            try:
                with open(fp, encoding=encoding) as f:
                    reader = csv.reader(f, delimiter=delim)
                    data = list(reader)
                    if data and len(data[0]) > 1:
                        return data
            except (csv.Error, UnicodeDecodeError, FileNotFoundError) as e:
                last_error = e
                continue
    # If we get here, all attempts failed
    if last_error:
        raise last_error
    return None


def _read_txt(fp: str) -> str:
    with open(fp, encoding="utf-8") as file:
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
        paths: str | list[str],
        metadata_manager: MetadataManager,
        callbacks: list[Callable[[str, str], None]] | None = None,
        error_holder: ErrorHolder | None = None,
        return_data: bool | None = True,
        filenames: str | list[str] | None = None,
        debounce_delay: float = 0.75,
        trailing_delay: float = 10.0,
        use_polling: bool = True,
        polling_interval: float = 1.0,
        skip_existing: bool = False,
        recursive: bool = False,
    ) -> None:
        """
        Initialise FileWatcher.

        Args:
            paths (Union[str, List[str]]): One or more directories to monitor.
            metadata_manager (MetadataManager): Metadata manager for associated data.
            callbacks (Optional[List[Callable]]): Callbacks for file events.
            error_holder (Optional[ErrorHolder]): Optional error holder for capturing exceptions.
            return_data (Optional[bool]): Returns the data (content of file) is true else, return filename.
            debounce_delay (float): Delay in seconds to debounce file modification events. Defaults to 0.75.
            trailing_delay (float): Delay in seconds before processing a debounced event if no new events occur.
                Defaults to 10.0. This ensures the last modification is eventually processed even if debounced.
            use_polling (bool): Use PollingObserver for cross-platform compatibility. Defaults to True.
                PollingObserver works reliably on all platforms (Windows, macOS, Linux, Raspberry Pi)
                and with network drives, but uses slightly more CPU than native observers.
            polling_interval (float): Interval in seconds between filesystem polls. Defaults to 1.0.
                Only used when use_polling is True. Lower values = faster detection but more CPU usage.
            skip_existing (bool): Skip files that already exist in the watched directories on startup.
                Defaults to False. When False, existing files matching the filename patterns will be
                processed as if they were newly created.

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
        self._use_polling = use_polling
        self._polling_interval = polling_interval
        self._skip_existing = skip_existing
        self._recursive = recursive

        self._last_created: dict = {}  # Track creation time per file path
        self._last_modified: dict = {}  # Track modification time per file path
        self._debounce_delay: float = debounce_delay
        self._trailing_delay: float = trailing_delay
        self._pending_timers: dict = {}  # Track pending trailing timers per file path

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
            if self._use_polling:
                self._observer = PollingObserver(timeout=self._polling_interval)
                logger.debug(f"Using PollingObserver with {self._polling_interval}s interval")
            else:
                self._observer = Observer()
                logger.debug("Using native filesystem observer")
            for path in self._paths:
                logger.debug(f"Watching path: {path}")
                self._observer.schedule(self, path, recursive=self._recursive)
            if not self._observer.is_alive():
                logger.debug("Starting observer thread...")
                self._observer.start()
            super().start()
            self._observing = True
            self._last_created = {}
            self._last_modified = {}
            self._pending_timers = {}
            logger.info("FileWatcher started.")
            if not self._skip_existing:
                self._process_existing_files()
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

        # Cancel all pending trailing timers
        for fp, timer in list(self._pending_timers.items()):
            timer.cancel()
        self._pending_timers.clear()

        self._observer.stop()
        self._observer.join()
        super().stop()
        self._observing = False
        logger.info("FileWatcher stopped.")

    def _process_existing_files(self) -> None:
        """
        Process files that already exist in the watched directories.
        Files matching the filename patterns will be processed as if they were newly created.
        """
        logger.info("Processing existing files in watched directories...")
        for path in self._paths:
            if not os.path.isdir(path):
                logger.warning(f"Path {path} is not a directory, skipping.")
                continue
            for filename in os.listdir(path):
                logger.debug(f"Processing existing file: {path}/{filename}")
                fp = os.path.join(path, filename)
                if not os.path.isfile(fp):
                    logger.debug(f"File {fp} is not a file, skipping.")
                    continue
                if not self._matches_filename_pattern(filename):
                    logger.debug(f"File {fp} does not match filename pattern, skipping.")
                    continue
                logger.debug(f"Processing existing file: {fp}")
                try:
                    self._last_created[fp] = time.time()
                    if self._return_data:
                        data = self._read_file_by_extension(fp)
                    else:
                        data = fp
                    logger.debug(
                        f"Dispatching creation callback for existing file: {fp} to callbacks {self._callbacks}"
                    )
                    self._dispatch_callback(self._term_map[self.on_modified], data)
                except Exception as e:
                    try:
                        self._file_event_exception(e, "existing file processing")
                    except InputError:
                        raise
        logger.info("Finished processing existing files.")

    def _matches_filename_pattern(self, filename: str) -> bool:
        """
        Check if a filename matches the configured filename patterns.

        Args:
            filename (str): The filename to check.

        Returns:
            bool: True if the filename matches a pattern or no patterns are set.
        """
        if not self._filenames:
            return True
        for pattern in self._filenames:
            if pattern.startswith("."):
                if filename.endswith(pattern):
                    return True
            elif fnmatch.fnmatch(filename, pattern):
                return True
        return False

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
            self._last_created[fp] = time.time()
            if self._return_data:
                data = self._read_file_by_extension(fp)
            else:
                data = fp
        except Exception as e:
            try:
                self._file_event_exception(e, "creation")
            except InputError:
                raise
            return
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
            if fp is None:
                if not event.is_directory:
                    logger.warning(f"File not found or not accessible. Skipping event {event}.")
                else:
                    # TODO to discuss, should we ever return a directory?
                    # if not self._return_data:
                    # Return path?
                    # data = event.src_path
                    logger.debug("Modification event is for a directory. Ignored.")
                return
            if not self._is_last_modified(fp):
                logger.debug(f"Modification event ({event}) ignored due to debounce delay.")
                self._schedule_trailing_modification(fp)
                return
            # Event passed debounce - cancel any pending trailing timer
            self._cancel_trailing_timer(fp)
            if self._return_data:
                logger.debug("Reading file content...")
                data = self._read_file_by_extension(fp)
            else:
                logger.debug("Returning file path instead of content...")
                data = fp
        except Exception as e:
            try:
                self._file_event_exception(e, "modification")
            except InputError:
                raise
            return
        self._dispatch_callback(self._term_map[self.on_modified], data)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """
        Handle file deletion events and trigger stop callbacks.

        Args:
            event (FileSystemEvent): Event object indicating a file deletion.
        """
        logger.debug(f"Received file deletion event: {event}")
        fp = self._get_filepath(event, file_exists=False)
        if fp is None:
            return

        if self._return_data:
            data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            data = fp
        self._dispatch_callback(self._term_map[self.on_deleted], data)

    def _get_filepath(self, event: FileSystemEvent, file_exists=True) -> str | None:
        """
        Retrieve the full file path for the event if it matches the watched file.

        Args:
            event (FileSystemEvent): Event object containing file information.

        Returns:
            Optional[str]: Full file path if it matches the watched file, otherwise None.
        """
        if event.is_directory:
            return None

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

    def _is_last_modified(self, fp: str) -> bool:
        """
        Determine if the file modification is outside the debounce delay for a specific file.

        Args:
            fp (str): The file path to check.

        Returns:
            bool: True if the modification event is outside the debounce period, False otherwise.
        """
        current_time = time.time()
        # Check if this file was recently created
        # Use a longer debounce window (1.5 seconds) for newly created files to account for
        # PollingObserver detecting file changes across multiple poll cycles
        creation_debounce = max(self._debounce_delay, 1.5)
        if fp in self._last_created:
            time_since_creation = current_time - self._last_created[fp]
            if time_since_creation <= creation_debounce:
                logger.debug(
                    f"File {fp}: ignoring modification (within {creation_debounce}s debounce window after creation)"
                )
                return False
        # Check if this file was recently modified
        if fp not in self._last_modified or (current_time - self._last_modified[fp]) > self._debounce_delay:
            self._last_modified[fp] = current_time
            return True
        return False

    def _cancel_trailing_timer(self, fp: str) -> None:
        """
        Cancel any pending trailing timer for a file.

        Args:
            fp (str): The file path to cancel the timer for.
        """
        if fp in self._pending_timers:
            self._pending_timers[fp].cancel()
            del self._pending_timers[fp]
            logger.debug(f"Cancelled trailing timer for {fp}")

    def _schedule_trailing_modification(self, fp: str) -> None:
        """
        Schedule a trailing modification callback for a debounced file.
        If a timer already exists for this file, it is cancelled and rescheduled.

        Args:
            fp (str): The file path to schedule the trailing callback for.
        """
        # Cancel existing timer if any
        self._cancel_trailing_timer(fp)

        def trailing_callback():
            if not self._observing:
                return
            # Remove from pending timers
            if fp in self._pending_timers:
                del self._pending_timers[fp]
            logger.debug(f"Trailing timer fired for {fp}")
            # Process the file
            try:
                if not os.path.isfile(fp):
                    logger.debug(f"File {fp} no longer exists, skipping trailing callback")
                    return
                # Update last_modified to allow this through
                self._last_modified[fp] = time.time()
                if self._return_data:
                    data = self._read_file_by_extension(fp)
                else:
                    data = fp
                self._dispatch_callback(self._term_map[self.on_modified], data)
            except Exception as e:
                try:
                    self._file_event_exception(e, "trailing modification")
                except InputError:
                    pass

        timer = Timer(self._trailing_delay, trailing_callback)
        timer.daemon = True
        self._pending_timers[fp] = timer
        timer.start()
        logger.debug(f"Scheduled trailing timer for {fp} in {self._trailing_delay}s")

    def _read_file_by_extension(self, fp: str):
        ext = os.path.splitext(fp)[1].lower()
        reader = file_readers.get(ext)

        if reader:
            return reader(fp)

        try:
            with open(fp, encoding="utf-8") as file:
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
