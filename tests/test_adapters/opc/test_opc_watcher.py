# -*- coding: utf-8 -*-
"""Tests for the OPC UA watcher."""
import logging
import threading
import time
import unittest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import Mock, patch

import leaf_example
from influxobject import InfluxPoint
from leaf_example.adapter import Adapter
from leaf_register.metadata import MetadataManager

from leaf.adapters.core_adapters.discrete_experiment_adapter import DiscreteExperimentAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.opc_watcher import OPCWatcher, OPCUA_AVAILABLE
from leaf.modules.output_modules.keydb import KEYDB
from leaf.modules.output_modules.mqtt import MQTT

metadata_fn = {
      "adapter_id": "MBPOPC",
      "equipment_data": {
        "version": "1.0",
        "manufacturer": "BearTree",
        "device_type": "Bioreactor",
        "application": "OPC Data logger for the BearTree Bioreactor"
      },
      "requirements": {
        "interval": "int",
        "host": "str",
        "port": "int",
        "topics": [
          "temperature",
          "pressure"
        ]
      },
      "adapter_data": {}
    }

class MBPOPCInterpreter(AbstractInterpreter):
    def __init__(self, metadata_manager):
        super().__init__()
        self.metadata_manager = metadata_manager
        self.message_count = 0

    def metadata(self, data):
        metadata = super().metadata(data)
        metadata.update({
            "device_type": "opc_ua_device",
            "protocol": "opc_ua"
        })
        return metadata

    def measurement(self, data):
        if not data or not isinstance(data, dict):
            return False
            
        self.message_count += 1
        
        node = data.get('node', 'unknown')
        value = data.get('value')
        timestamp = data.get('timestamp')
        
        if value is None:
            return False
        
        influx_object = InfluxPoint()
        influx_object.measurement = "opc_ua_device"
        influx_object.time = timestamp if timestamp else datetime.now(timezone.utc)
        influx_object.set_entity_tag(f"node_{node}")
        influx_object.set_metric("value")
        influx_object.add_field("value", float(value))
        influx_object.add_field("message_count", self.message_count)
        
        return [influx_object]

    def simulate(self):
        return

class MBPOPCAdapter(DiscreteExperimentAdapter):
    """Test adapter for OPC UA device testing."""
    def __init__(
            self,
            instance_data,
            output,
            topics: Optional[set[str]] = [".*R1.*"],
            exclude_topics: Optional[list[str]] = [],
            host: str = 'localhost',
            port: int = 4840,
            reporting_interval=10,
            maximum_message_size: Optional[int] = 100,
            error_holder: Optional[ErrorHolder] = None,
            experiment_timeout: Optional[int] = None,
            external_watcher: Optional[OPCWatcher] = None
    ) -> None:
        if instance_data is None or instance_data == {}:
            raise ValueError("Instance data cannot be empty")

        metadata_manager = MetadataManager()
        watcher: OPCWatcher = OPCWatcher(metadata_manager=metadata_manager, topics=topics, port=port, host=host,
                                         exclude_topics=exclude_topics, interval=60)

        interpreter = MBPOPCInterpreter(metadata_manager=metadata_manager)

        super().__init__(instance_data=instance_data,
                         watcher=watcher,
                         output=output,
                         interpreter=interpreter,
                         maximum_message_size=maximum_message_size,
                         error_holder=error_holder,
                         metadata_manager=metadata_manager,
                         experiment_timeout=experiment_timeout)

        self._metadata_manager.add_equipment_data(metadata_fn)


@unittest.skipUnless(OPCUA_AVAILABLE, "OPC UA library not available")
class TestOpcWatcher(unittest.TestCase):
    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.error_holder = ErrorHolder("opc_test")
        self.interpreter = MBPOPCInterpreter(self.metadata_manager)
        
        # Add metadata
        self.metadata_manager.add_equipment_data(metadata_fn)
        #
        logging.info("OPC UA library is available for testing.")

    def test_opc_watcher_creation(self):
        """Test that OPCWatcher can be created with proper parameters."""
        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4840,
            topics={"temperature", "pressure"},
            exclude_topics=[],
            interval=1,
            error_holder=self.error_holder
        )
        
        self.assertEqual(watcher._host, "localhost")
        self.assertEqual(watcher._port, 4840)
        self.assertEqual(watcher._topics, {"temperature", "pressure"})
        self.assertEqual(watcher._exclude_topics, [])
        self.assertEqual(watcher._interval, 1)

    def test_interpreter_processes_opc_data(self):
        """Test that the interpreter processes OPC UA data correctly."""
        # Simulate OPC UA data
        opc_data = {
            'node': 'temperature_sensor_01',
            'value': 25.5,
            'timestamp': datetime.now(timezone.utc),
            'data': Mock()
        }
        
        result = self.interpreter.measurement(opc_data)
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], InfluxPoint)
        self.assertEqual(result[0].measurement, "opc_ua_device")
        self.assertEqual(self.interpreter.message_count, 1)

    def test_invalid_data_handled_gracefully(self):
        """Test graceful handling of invalid data."""
        # Test with None
        result = self.interpreter.measurement(None)
        self.assertFalse(result)
        
        # Test with empty dict
        result = self.interpreter.measurement({})
        self.assertFalse(result)
        
        # Test with missing value
        result = self.interpreter.measurement({'node': 'test'})
        self.assertFalse(result)

    @patch('leaf.modules.input_modules.opc_watcher.Client')
    def test_opc_watcher_start_unavailable(self, mock_client):
        """Test OPCWatcher start when OPC UA is unavailable."""
        # Temporarily set OPCUA_AVAILABLE to False
        with patch('leaf.modules.input_modules.opc_watcher.OPCUA_AVAILABLE', False):
            watcher = OPCWatcher(
                metadata_manager=self.metadata_manager,
                host="localhost",
                port=4840,
                topics=set(),
                exclude_topics=[],
                error_holder=self.error_holder
            )
            
            with self.assertRaises(Exception) as context:
                watcher.start()
            
            self.assertIn("OPC UA library is not available", str(context.exception))

    def test_metadata_processing(self):
        """Test metadata processing."""
        test_data = {"test": "data"}
        result = self.interpreter.metadata(test_data)
        
        self.assertIn("device_type", result)
        self.assertIn("protocol", result)
        self.assertEqual(result["device_type"], "opc_ua_device")
        self.assertEqual(result["protocol"], "opc_ua")


    def test_watcher_callback_mechanism(self):
        """Test that watcher can trigger callbacks properly."""
        callback_called = []
        
        def test_callback(func, data):
            callback_called.append(data)
            
        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost", 
            port=4840,
            topics={"temperature"},
            exclude_topics=[],
            interval=1,
            callbacks=[test_callback],
            error_holder=self.error_holder
        )
        
        # Simulate callback trigger
        test_data = {
            'node': 'temperature_sensor',
            'value': 23.5,
            'timestamp': datetime.now(timezone.utc),
            'data': Mock()
        }
        
        # Manually trigger the callback mechanism
        watcher._dispatch_callback(lambda x: x, test_data)
        
        # Verify callback was triggered
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0], test_data)

if __name__ == "__main__":
    unittest.main()