import json

from typing import Optional, Any

import redis
from redis.typing import ResponseT

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel
from leaf.modules.output_modules.output_module import OutputModule
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="output_module.log")


class KEYDB(OutputModule):
    """
    An output module for interacting with a KeyDB (Redis-compatible)
    server. This class provides methods to connect to KeyDB, transmit
    data, retrieve data, and handle errors consistently. If connection
    or transmission fails, a fallback module can be used if provided.
    """

    def __init__(
        self,
        host: str,
        port: int = 6379,
        db: int = 0,
        fallback: Optional[OutputModule] = None,
        error_holder: Optional[ErrorHolder] = None,
    ) -> None:
        """
        Initialize the KEYDB adapter with KeyDB connection details and
        optional fallback.

        Args:
            host (str): The KeyDB server hostname or IP address.
            port (int): The port for KeyDB connection (default is 6379).
            db (int): The database number to connect to (default is 0).
            fallback (Optional[OutputModule]): Fallback module to use
                     if KeyDB operations fail.
            error_holder (Optional[ErrorHolder]): Optional error holder
                         for tracking errors.
        """
        super().__init__(fallback=fallback, error_holder=error_holder)
        self.host: str = host
        self.port: int = port
        self.db: int = db
        self._client: Optional[redis.StrictRedis] = None
        self.connect()

    def _handle_redis_error(self, exception: redis.RedisError) -> None:
        """
        Handle Redis-related errors by logging
        them and invoking the error handler.

        Args:
            exception (redis.RedisError): The Redis exception that occurred.
        """
        if isinstance(exception, redis.AuthenticationError):
            message = f"Authentication failed for KeyDB at {self.host}:{self.port}"
            severity = SeverityLevel.CRITICAL
        elif isinstance(exception, redis.ConnectionError):
            if "Network is unreachable" in str(exception):
                message = f"Network unreachable for KeyDB at {self.host}:{self.port}"
                severity = SeverityLevel.ERROR
            elif "Connection refused" in str(exception):
                message = f"Connection refused for KeyDB at {self.host}:{self.port}"
                severity = SeverityLevel.WARNING
            else:
                message = f"Failed to connect to KeyDB at {self.host}:{self.port}: {str(exception)}"
                severity = SeverityLevel.CRITICAL
        elif isinstance(exception, redis.TimeoutError):
            message = f"Connection to KeyDB at {self.host}:{self.port} timed out."
            severity = SeverityLevel.ERROR
        else:
            message = f"Redis error for KeyDB: {str(exception)}"
            severity = SeverityLevel.WARNING

        self._handle_exception(
            ClientUnreachableError(message, output_module=self, severity=severity)
        )

    def connect(self) -> None:
        """
        Establish a connection to the KeyDB server.

        Logs success or handles connection errors by
        invoking the error handler.
        """
        try:
            self._client = redis.StrictRedis(host=self.host, port=self.port, db=self.db)
            logger.info(f"Connected to KeyDB server at {self.host}:{self.port}, DB: {self.db}")
        except redis.RedisError as e:
            self._handle_redis_error(e)

    def transmit(self, topic: str, data: Optional[Any] = None) -> bool:
        """
        Transmit data to the KeyDB server by appending it to the existing
        value for the given key. The value for each key is always stored
        as a list, even if it contains only one element.

        Args:
            topic (str): The key name under which the data will be stored.
            data (Optional[Any]): The data to append to the list in KeyDB.

        Returns:
            bool: True if the data was successfully transmitted,
                False if a fallback was used.
        """
        if data is None:
            logger.warning("No data provided to transmit.")
            return False
        elif isinstance(data, (dict, list, tuple, int, float, bool)):
            data = json.dumps(data)
        elif isinstance(data, str):
            try:
                # Validate JSON, then normalize as JSON string
                parsed = json.loads(data)
                data = json.dumps(parsed)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON string: {data}")
                return False
        else:
            logger.error(f"Unsupported data type: {type(data).__name__}")
            return False

        if self._client is None:
            return self.fallback(topic, data)

        try:
            self._client.lpush(topic, data)
            logger.info(f"Pushed data to key '{topic}' in KeyDB {self._client} with {self._client.llen(topic)} rows.")
            # Reset global failure counter on successful transmission
            OutputModule.reset_failure_count()
            return True
        except redis.RedisError as e:
            self._handle_redis_error(e)
            return self.fallback(topic, data)

    def is_connected(self) -> bool:
        """
        Check if the connection to KeyDB is established.

        Returns:
            bool: True if connected, False otherwise.
        """
        # TODO Have a thread running to check for content and if present process it to the registered MQTT output module if alive
        topics = self._client.keys()
        if topics:
            logger.info(f"Found existing keys in KeyDB: {topics}")
            for topic in topics:
                topic = topic.decode("utf-8")
                self.pop(topic)
        else:
            logger.debug("No existing keys found in KeyDB.")
        return self._client is not None

    def disconnect(self) -> None:
        """
        Disconnect from the KeyDB server by
        setting the client to None.

        Logs the disconnection status.
        """
        if self._client is not None:
            self._client = None
            logger.info("Disconnected from KeyDB.")
        else:
            logger.info("Already disconnected from KeyDB.")

    def pop(self, key: Optional[str] = None) -> Optional[tuple[str, Any]]:
        """
        Retrieve and remove a record from KeyDB.
        If a specific key is provided, retrieve and remove all values under
        that key. If no key is provided, retrieve and remove one element from
        a random key's list. The key is removed when the last element is taken.

        Args:
            key (Optional[str]): The key of the record to retrieve and remove.
                                If None, a random record is retrieved and removed.

        Returns:
            Optional[tuple[str, Any]]: A tuple of the key and the retrieved value,
                                    or None if the key does not exist or the
                                    database is empty.
        """
        if self._client is None:
            logger.warning("Attempted to pop from a disconnected KeyDB client.")
            return None

        try:
            if key is not None:
                result = self._client.lpop(key)
                if result:
                    # Content is already popped
                    # If the list is empty after popping, delete the key
                    if self._client.llen(key) == 0:
                        self._client.delete(key)
                    return key, json.loads(result.decode("utf-8"))
                return None

            random_key: ResponseT = self._client.randomkey()
            if not random_key:
                logger.info("No keys available in KeyDB.")
                return None
            if isinstance(random_key, bytes):
                # Decode bytes to string if necessary
                random_key = random_key.decode("utf-8")

            logger.info(f"Popping from key '{random_key}' in KeyDB.")
            result = self._client.lpop(random_key)

            if not result:
                return None

            result = json.loads(result.decode("utf-8"))
            if result:
                # Check if the list is empty after popping
                if self._client.llen(random_key) == 0:
                    logger.info(f"Key '{random_key}' is empty after popping.")
                    self._client.delete(random_key)
                logger.info(f"Popped key '{random_key}' from KeyDB.")
                return random_key, result
            # if isinstance(result, list):
            #     popped_value = result.pop(0)
            #     if result:
            #         self._client.set(random_key, json.dumps(result))
            #     else:
            #         self._client.delete(random_key)
            #     return random_key, popped_value

            logger.error(
                f"Unexpected value type for key '{random_key}'. Deleting key."
            )
            self._client.delete(random_key)
            return None
        except redis.RedisError as e:
            self._handle_redis_error(e)
            return None
