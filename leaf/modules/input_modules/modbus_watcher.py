import threading
import time
from collections.abc import Callable
from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")

try:
    from pymodbus.client import ModbusTcpClient

    MODBUS_AVAILABLE = True
except ImportError:
    logger.warning("pymodbus library not available. ModbusWatcher will not function.")
    MODBUS_AVAILABLE = False
    ModbusTcpClient = None


class ModbusWatcher(ExternalEventWatcher):
    """
    Polls a Modbus TCP device at a fixed interval and dispatches measurement events.

    Each entry in `registers` may contain:
        name    (str):   Key used in the output payload.
        address (int):   Modbus holding register address. Accepts either 4xxxx notation
                         (e.g. 40301, offset subtracted automatically) or 0-based protocol
                         address (e.g. 300).
        count   (int):   Number of consecutive registers to read (default 1).
        scale   (float): Multiply the raw value by this factor (default 1.0).
                         Applied only when count == 1.

    Config example::

        external_input:
          plugin: modbus_watcher
          host: 192.168.1.12
          port: 502           # optional, default 502
          device_id: 1        # optional, default 1
          interval: 5         # seconds between polls, required
          registers:
            - name: temperature
              address: 40301
              scale: 0.01
            - name: humidity
              address: 40317
              scale: 0.01
            - name: presence
              address: 40803
            - name: last_ir_ts
              address: 42002
              count: 2
    """

    def __init__(
        self,
        host: str,
        interval: int,
        registers: list[dict],
        port: int = 502,
        device_id: int = 1,
        metadata_manager: MetadataManager | None = None,
        callbacks: list[Callable] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        super().__init__(metadata_manager=metadata_manager, callbacks=callbacks, error_holder=error_holder)
        self._host = host
        self._port = port
        self._device_id = device_id
        self._interval = interval
        self._registers = registers
        self._client: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not MODBUS_AVAILABLE:
            raise RuntimeError("pymodbus is not installed. Run: pip install pymodbus")

        super().start()

        self._client = ModbusTcpClient(self._host, port=self._port)
        if not self._client.connect():
            raise ConnectionError(f"Failed to connect to Modbus device at {self._host}:{self._port}")

        logger.info(f"ModbusWatcher connected to {self._host}:{self._port}, polling every {self._interval}s")
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        super().stop()
        if self._thread:
            self._thread.join(timeout=self._interval + 5)
        if self._client:
            self._client.close()
            self._client = None
        logger.info("ModbusWatcher stopped.")

    def _poll(self) -> None:
        while self._running:
            try:
                data = self._read_registers()
                self._emit(data)
            except Exception as e:
                logger.error(f"ModbusWatcher poll error: {e}")
                self._handle_exception(e)
            time.sleep(self._interval)

    def _read_registers(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for reg in self._registers:
            name = reg.get("name")
            address = reg.get("address")
            count = int(reg.get("count", 1))
            scale = float(reg.get("scale", 1.0))

            if not name or address is None:
                logger.warning(f"Skipping register entry with missing name or address: {reg}")
                continue

            raw_address = int(address)
            protocol_address = raw_address - 40001 if raw_address >= 40001 else raw_address
            result = self._client.read_holding_registers(
                address=protocol_address,
                count=count,
                device_id=self._device_id,
            )
            if result.isError():
                logger.warning(f"Modbus error reading register {address} ({name}): {result}")
                continue

            if count == 1:
                data[name] = result.registers[0] * scale
            else:
                data[name] = list(result.registers)

        return data

    def _emit(self, data: dict[str, Any]) -> None:
        if self._metadata_manager:
            self._dispatch_callback(self._metadata_manager.experiment.measurement, data)
        else:
            for callback in self._callbacks:
                try:
                    callback("measurement", data)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
                    self._handle_exception(e)
