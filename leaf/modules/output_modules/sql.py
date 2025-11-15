import json
import logging
import sqlite3
from typing import Any
from typing import Optional
from typing import Union
from leaf.modules.output_modules.output_module import OutputModule
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="output_module.log")

class SQL(OutputModule):
    def __init__(self,
                 filename: str = "leaf_messages.db",
                 fallback: Optional[OutputModule] = None,
                 error_holder: Optional[ErrorHolder] = None) -> None:
        super().__init__(fallback=fallback, error_holder=error_holder)
        self.database = filename
        self._connection = None
        self._initialize_database()

    def _initialize_database(self) -> None:
        """
        Initialize the SQLite database and create the messages table if it doesn't exist.
        Table schema: id (primary key), topic (indexed), data (JSON), timestamp
        """
        try:
            logger.info(f"Initializing database '{self.database}'")
            conn = sqlite3.connect(self.database)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    data TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Create index on topic for fast lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_topic ON messages(topic)
            ''')
            conn.commit()
            conn.close()
            logger.info(f"Database '{self.database}' initialized successfully")
        except sqlite3.Error as e:
            self._handle_db_error(e)

    def _handle_db_error(self, error) -> None:
        """
        Handles database-related exceptions consistently with a structured error message.
        """
        if isinstance(error, sqlite3.OperationalError):
            message = f"SQLite operational error in '{self.database}': {error}"
            severity = SeverityLevel.ERROR
        elif isinstance(error, sqlite3.IntegrityError):
            message = f"SQLite integrity error in '{self.database}': {error}"
            severity = SeverityLevel.WARNING
        elif isinstance(error, sqlite3.DatabaseError):
            message = f"SQLite database error in '{self.database}': {error}"
            severity = SeverityLevel.CRITICAL
        else:
            message = f"Unexpected database error in '{self.database}': {error}"
            severity = SeverityLevel.WARNING

        self._handle_exception(ClientUnreachableError(message,
                                                      output_module=self,
                                                      severity=severity))

    def transmit(self, topic: str, data: Optional[Union[str, dict]] = None) -> bool:
        """
        Transmit data to the database associated with a specific topic.
        Each call inserts a new row with the topic and data.
        """
        try:
            if data is None:
                return True

            # Serialize data to JSON string
            data_json = json.dumps(data)

            # Insert into database
            conn = sqlite3.connect(self.database)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO messages (topic, data) VALUES (?, ?)',
                (topic, data_json)
            )
            conn.commit()
            conn.close()

            # Reset global failure counter on successful transmission
            OutputModule.reset_failure_count()

            # If debug, count number of messages in database
            if logger.isEnabledFor(logging.DEBUG):  # DEBUG level
                conn = sqlite3.connect(self.database)
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM messages')
                count = cursor.fetchone()[0]
                conn.close()
                logger.debug(f"Message stored. Total messages in database: {count}")
            return True

        except (sqlite3.Error, json.JSONDecodeError) as e:
            self._handle_db_error(e)
            return self.fallback(topic, data)

    def retrieve(self, topic: str) -> tuple[str, Any] | None:
        """
        Retrieve and remove the first message for a specific topic.
        Returns a tuple of (topic, data), or None if no messages exist.
        This method pops one message at a time to enable iterative processing.
        """
        try:
            conn = sqlite3.connect(self.database)
            cursor = conn.cursor()

            # Get first message with specific topic
            cursor.execute(
                'SELECT id, topic, data FROM messages WHERE topic = ? ORDER BY id LIMIT 1',
                (topic,)
            )

            row = cursor.fetchone()

            if row is None:
                conn.close()
                return None

            message_id, msg_topic, data_json = row

            # Delete the message
            cursor.execute('DELETE FROM messages WHERE id = ?', (message_id,))
            conn.commit()
            conn.close()

            # Deserialize the data
            try:
                data = json.loads(data_json)
                return msg_topic, data
            except json.JSONDecodeError:
                return msg_topic, data_json

        except sqlite3.Error as e:
            self._handle_db_error(e)
            return None

    def pop(self, key: str = None) -> tuple[str, Any] | None:
        """
        Retrieve and remove the first message from the database.
        If a specific key (topic) is provided, removes the first message with that topic.
        If no key is provided, removes the first message in the database.

        Args:
            key (Optional[str]): The topic to retrieve and remove.
                                If None, removes the first message.

        Returns:
            Optional[tuple[str, Any]]: A tuple of (topic, data),
                                    or None if the database is empty or key not found.
        """
        try:
            conn = sqlite3.connect(self.database)
            cursor = conn.cursor()

            if key is not None:
                # Get first message with specific topic
                cursor.execute(
                    'SELECT id, topic, data FROM messages WHERE topic = ? ORDER BY id LIMIT 1',
                    (key,)
                )
            else:
                # Get first message overall
                cursor.execute(
                    'SELECT id, topic, data FROM messages ORDER BY id LIMIT 1'
                )

            row = cursor.fetchone()

            if row is None:
                conn.close()
                return None

            message_id, topic, data_json = row

            # Delete the message
            cursor.execute('DELETE FROM messages WHERE id = ?', (message_id,))
            conn.commit()
            conn.close()

            # Deserialize the data
            try:
                data = json.loads(data_json)
                return topic, data
            except json.JSONDecodeError:
                return topic, data_json

        except sqlite3.Error as e:
            self._handle_db_error(e)
            return None

    def is_connected(self) -> bool:
        """
        Check if the SQL module is connected.
        For SQLite, always returns True as it's file-based.

        Returns:
            bool: Always returns True.
        """
        return True

    def connect(self) -> None:
        """
        Connect method for SQL module.
        SQLite connections are created per-operation, so this is a no-op.
        """
        pass

    def disconnect(self) -> None:
        """
        Disconnect method for SQL module.
        SQLite connections are closed after each operation, so this is a no-op.
        """
        pass