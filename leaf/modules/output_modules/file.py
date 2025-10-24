import json
import os
import random
from typing import Any
from typing import Optional
from typing import Union
from leaf.modules.output_modules.output_module import OutputModule
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel


class FILE(OutputModule):
    def __init__(self, filename: str, fallback: Optional[OutputModule] = None, 
                 error_holder: Optional[ErrorHolder] = None) -> None:
        super().__init__(fallback=fallback, error_holder=error_holder)
        self.filename = filename

    def _handle_file_error(self, error) -> None:
        """
        Handles file-related exceptions consistently
        with a structured error message.
        """
        if isinstance(error, FileNotFoundError):
            message = f"File not found '{self.filename}'"
            severity = SeverityLevel.WARNING
        elif isinstance(error, PermissionError):
            message = f"Permission denied when accessing '{self.filename}'"
            severity = SeverityLevel.CRITICAL
        elif isinstance(error, (TypeError, ValueError)):
            message = f"JSON serialization error - data not JSON-serializable: {error}"
            severity = SeverityLevel.WARNING
        elif isinstance(error, OSError):
            message = f"I/O error in file '{self.filename}': {error}"
            severity = SeverityLevel.ERROR
        elif isinstance(error, json.JSONDecodeError):
            message = f"JSON decode error when reading '{self.filename}' "
            severity = SeverityLevel.WARNING
        else:
            message = f"Unexpected error in file '{self.filename}': {error}"
            severity = SeverityLevel.WARNING

        self._handle_exception(ClientUnreachableError(message,
                                                      output_module=self,
                                                      severity=severity))

    def transmit(self, topic: str, data: Optional[Union[str, dict]] = None) -> bool:
        """
        Transmit data to the file associated with a specific topic.
        Appends a single line with the topic and data in compact JSON format.
        """
        try:
            if data is None:
                return True

            # Create a single-line JSON entry
            line = json.dumps({topic: [data]}, separators=(',', ':'))

            # Append to file (no reading required)
            with open(self.filename, 'a') as f:
                f.write(line + '\n')

            # Reset global failure counter on successful transmission
            OutputModule.reset_failure_count()
            return True

        except (TypeError, ValueError) as e:
            # Handle JSON serialization errors (non-serializable data)
            self._handle_file_error(e)
            return self.fallback(topic, data)
        except (OSError, IOError) as e:
            # Handle file I/O errors
            self._handle_file_error(e)
            return self.fallback(topic, data)

    def retrieve(self, topic: str) -> list:
        """
        Retrieve all data associated with a specific topic by streaming line-by-line.
        Returns a list of all data entries for the topic.
        """
        try:
            if not os.path.exists(self.filename):
                return []

            results = []
            with open(self.filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Check if this line contains the topic
                        if topic in entry:
                            # Extend results with all data from this line
                            data = entry[topic]
                            if isinstance(data, list):
                                results.extend(data)
                            else:
                                results.append(data)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue

            return results if results else None

        except (OSError, IOError) as e:
            self._handle_file_error(e)
            return None
    
    def pop(self, key: str = None) -> tuple[str, Any] | None:
        """
        Retrieve and remove the first occurrence of a topic from the file.
        If a specific key is provided, removes the first line with that topic.
        If no key is provided, removes the first line in the file.

        Args:
            key (Optional[str]): The topic to retrieve and remove.
                                If None, removes the first line.

        Returns:
            Optional[tuple[str, Any]]: A tuple of (topic, data_list),
                                    or None if the file is empty or key not found.
        """
        try:
            if not os.path.exists(self.filename):
                return None

            lines = []
            found_line = None
            found_topic = None
            found_data = None

            # Read all lines and find the first matching one
            with open(self.filename, 'r') as f:
                for line in f:
                    line_content = line.strip()
                    if not line_content:
                        continue

                    try:
                        entry = json.loads(line_content)

                        # If no key specified, take the first valid line
                        if key is None and found_line is None:
                            found_topic = list(entry.keys())[0]
                            found_data = entry[found_topic]
                            found_line = line
                            continue  # Skip adding to lines (removes it)

                        # If key specified, find matching topic
                        if key is not None and key in entry and found_line is None:
                            found_topic = key
                            found_data = entry[key]
                            found_line = line
                            continue  # Skip adding to lines (removes it)

                        # Keep all other lines
                        lines.append(line)
                    except json.JSONDecodeError:
                        # Keep malformed lines
                        lines.append(line)

            if found_line is None:
                return None

            # Rewrite file without the removed line
            with open(self.filename, 'w') as f:
                f.writelines(lines)

            return found_topic, found_data

        except (OSError, IOError) as e:
            self._handle_file_error(e)
            return None
    
    def is_connected(self) -> bool:
        """
        Check if the FILE module is always connected.

        Returns:
            bool: Always returns True.
        """
        return True
    
    def connect(self) -> None:
        """
        Connect method for FILE module (no-op as files are always accessible).
        """
        pass
        
    def disconnect(self) -> None:
        """
        Disconnect method for FILE module (no-op as files are always accessible).
        """
        pass

