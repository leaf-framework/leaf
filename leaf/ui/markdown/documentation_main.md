###### LEAF System Overview

**LEAF (Laboratory Equipment Adapter Framework)** is a powerful system for monitoring laboratory equipment and transmitting data to various cloud destinations.

###### Quick Start Guide

###### Step 1: Configure Your Setup
1. Navigate to the **Configuration** tab
2. Edit the YAML configuration to define your equipment and outputs
3. Save and restart the application

###### Step 2: Install Adapters
1. Go to the **Adapters** tab
2. Browse available adapters in the marketplace
3. Install adapters for your specific equipment

###### Step 3: Monitor Operations
1. Check the **Logs** tab for system activity
2. Monitor equipment status and data flow
3. Debug any issues using the live log feed

###### Configuration Structure

###### Equipment Instances
Define your laboratory equipment with specific adapters:
```yaml
EQUIPMENT_INSTANCES:
  - equipment:
      adapter: HelloWorld
      data:
        instance_id: my_bioreactor_01
        organisation: university_lab
      requirements:
        interval: 30  # seconds
```

###### Output Destinations
Configure where data should be sent:
```yaml
OUTPUTS:
  - plugin: MQTT
    broker: localhost
    port: 1883
    fallback: FILE

  - plugin: FILE
    filename: fallback.json
```

Every output receives all data, except one that another output names as its `fallback`;
that one only takes over while the other fails. Two outputs of the same plugin each need a `name`,
which `fallback` can then refer to.

```yaml
OUTPUTS:
  - plugin: MQTT
    name: lab
    broker: mqtt.lab
    fallback: buffer
  - plugin: MQTT
    name: cloud
    broker: mqtt.cloud
  - plugin: FILE
    name: share
    filename: /mnt/share/leaf.json
  - plugin: FILE
    name: buffer
    filename: buffer.json
```

###### Available Adapters

See the **Adapters** tab for a full list of available adapters and plugins.

###### Use Cases

- **Bioreactor Monitoring**: Track pH, temperature, dissolved oxygen
- **Analytical Instruments**: Connect HPLC, spectrophotometers
- **Environmental Monitoring**: Temperature, humidity sensors
- **Process Control**: Automated laboratory workflows
