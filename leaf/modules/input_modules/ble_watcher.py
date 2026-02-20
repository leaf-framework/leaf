import asyncio
import logging
import threading
from collections.abc import Callable

from bleak import BleakScanner

# Suppress verbose bleak DEBUG logging
logging.getLogger("bleak").setLevel(logging.WARNING)
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")

# Reconnection settings for BLE scanner recovery (e.g., after sleep/wake)
FIRST_RECONNECT_DELAY = 1
RECONNECT_RATE = 2
MAX_RECONNECT_DELAY = 60
MAX_RECONNECT_COUNT = 12


class BLEEventWatcher(EventWatcher):
    """
    BLE advertisement scanner that passively receives broadcast data from BLE devices.

    This watcher continuously scans for BLE advertisements and triggers callbacks
    when matching devices are detected. It supports filtering by device address,
    device name, manufacturer ID, and service UUID.

    Unlike GATT-based connections, this watcher does not connect to devices but
    instead listens to their advertising packets, making it suitable for sensors
    that broadcast data (beacons, environmental sensors, etc.).
    """

    def __init__(
        self,
        metadata_manager: MetadataManager | None = None,
        device_addresses: list[str] | str | None = None,
        device_name_filter: str | None = None,
        manufacturer_id: int | None = None,
        service_uuid: str | None = None,
        callbacks: list[Callable] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the BLE advertisement watcher.

        Args:
            metadata_manager: Used for adapter and experiment metadata.
            device_addresses: Single address or list of BLE MAC addresses to filter.
                              None means all devices are accepted.
            device_name_filter: Filter devices by name (case-insensitive substring match).
            manufacturer_id: Filter by manufacturer ID in advertisement data.
            service_uuid: Filter by service UUID in advertisement data.
            callbacks: List of callback functions for received data.
            error_holder: Error holder for tracking errors.
            max_reconnect_count: Maximum reconnection attempts after scanner failure.
                                 Use -1 for unlimited retries. Default is 12.
        """
        super().__init__(
            metadata_manager=metadata_manager,
            callbacks=callbacks,
            error_holder=error_holder,
        )

        # Normalize device addresses to a set for fast lookup
        if device_addresses is None:
            self._device_addresses: set[str] | None = None
        elif isinstance(device_addresses, str):
            self._device_addresses = {device_addresses.upper()}
        else:
            self._device_addresses = {addr.upper() for addr in device_addresses}

        self._device_name_filter = device_name_filter
        self._manufacturer_id = manufacturer_id
        self._service_uuid = service_uuid

        self._scanner: BleakScanner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the BLE advertisement scanner in a background thread."""
        super().start()

        if self._thread and self._thread.is_alive():
            logger.warning("BLE advertisement watcher already running")
            return

        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        logger.info("BLE advertisement watcher started")

    def stop(self) -> None:
        """Stop the BLE advertisement scanner."""
        super().stop()

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._stop_scanner(), self._loop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        logger.info("BLE advertisement watcher stopped")

    def _run_event_loop(self) -> None:
        """Run the asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._scan_loop())
        except Exception as e:
            logger.error(f"Event loop error: {e}")
            self._handle_exception(e)
        finally:
            self._loop.close()
            self._loop = None

    async def _scan_loop(self) -> None:
        """Main scanning loop with automatic reconnection on failure."""
        reconnect_delay = FIRST_RECONNECT_DELAY

        while self._running:
            logger.info("Starting BLE advertisement scanner...")
            self._scanner = BleakScanner(detection_callback=self._detection_callback)

            try:
                await self._scanner.start()
                logger.info("BLE scanner started, listening for advertisements...")

                # Reset reconnect state on successful start
                self._reconnect_count = 0
                reconnect_delay = FIRST_RECONNECT_DELAY

                # Keep scanning while running
                while self._running:
                    await asyncio.sleep(0.1)

                # Clean exit requested
                break

            except Exception as e:
                logger.error(f"Scanner error: {e}")
                self._handle_exception(e)
                await self._stop_scanner()

                # Check if we should attempt reconnection
                if not self._running:
                    break

                self._reconnect_count += 1
                if self._max_reconnect_count >= 0 and self._reconnect_count > self._max_reconnect_count:
                    logger.error(
                        f"Max reconnection attempts ({self._max_reconnect_count}) reached. "
                        "BLE scanner will not restart automatically."
                    )
                    break

                if self._max_reconnect_count < 0:
                    logger.info(f"BLE scanner will retry in {reconnect_delay}s (attempt {self._reconnect_count})")
                else:
                    logger.info(
                        f"BLE scanner will retry in {reconnect_delay}s "
                        f"(attempt {self._reconnect_count}/{self._max_reconnect_count})"
                    )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * RECONNECT_RATE, MAX_RECONNECT_DELAY)

        await self._stop_scanner()

    async def _stop_scanner(self) -> None:
        """Stop the scanner gracefully."""
        if self._scanner:
            try:
                await self._scanner.stop()
                logger.debug("BLE scanner stopped")
            except Exception as e:
                logger.error(f"Error stopping scanner: {e}")
            self._scanner = None

    def _detection_callback(self, device: BLEDevice, advertisement_data: AdvertisementData) -> None:
        """
        Callback for each detected BLE advertisement.

        Args:
            device: The detected BLE device.
            advertisement_data: The advertisement data from the device.
        """
        # Filter by device address if specified
        if self._device_addresses is not None:
            if device.address.upper() not in self._device_addresses:
                return

        # Filter by device name if specified
        if self._device_name_filter is not None:
            device_name = device.name or advertisement_data.local_name or ""
            if self._device_name_filter.lower() not in device_name.lower():
                return

        # Filter by manufacturer ID if specified
        if self._manufacturer_id is not None:
            if self._manufacturer_id not in advertisement_data.manufacturer_data:
                return

        # Filter by service UUID if specified
        if self._service_uuid is not None:
            service_uuids_lower = [uuid.lower() for uuid in advertisement_data.service_uuids]
            if self._service_uuid.lower() not in service_uuids_lower:
                return

        # Build event data
        event_data = {
            "device_address": device.address,
            "device_name": device.name or advertisement_data.local_name,
            "rssi": advertisement_data.rssi,
            "manufacturer_data": dict(advertisement_data.manufacturer_data),
            "service_data": dict(advertisement_data.service_data),
            "service_uuids": list(advertisement_data.service_uuids),
            "tx_power": advertisement_data.tx_power,
        }

        logger.debug(
            f"Advertisement from {device.address} ({device.name}): "
            f"RSSI={advertisement_data.rssi}, "
            f"manufacturer_data={advertisement_data.manufacturer_data}"
        )

        # Dispatch to callbacks using the measurement event
        if self._metadata_manager:
            self._dispatch_callback(self._metadata_manager.experiment.measurement, event_data)
        else:
            # Fallback: call callbacks directly with "measurement" event
            for callback in self._callbacks:
                try:
                    callback("measurement", event_data)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
                    self._handle_exception(e)

    def is_connected(self) -> bool:
        """
        Check if the BLE scanner is running.

        Returns:
            bool: True if the scanner is active, False otherwise.
        """
        return self._scanner is not None and self._running

    def get_device_addresses(self) -> set[str] | None:
        """
        Get the configured device address filter.

        Returns:
            Set of device addresses being filtered, or None if no filter is set.
        """
        return self._device_addresses

    def add_device_address(self, address: str) -> None:
        """
        Add a device address to the filter list.

        Args:
            address: BLE MAC address to add.
        """
        if self._device_addresses is None:
            self._device_addresses = set()
        self._device_addresses.add(address.upper())

    def remove_device_address(self, address: str) -> None:
        """
        Remove a device address from the filter list.

        Args:
            address: BLE MAC address to remove.
        """
        if self._device_addresses:
            self._device_addresses.discard(address.upper())
