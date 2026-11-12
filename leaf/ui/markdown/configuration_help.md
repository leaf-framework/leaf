#### Equipment Instances
Define your laboratory equipment:
```yaml
EQUIPMENT_INSTANCES:
  - equipment:
      adapter: HelloWorld
      data:
        instance_id: my_device
        organisation: university_lab
      requirements:
        interval: 30
```

#### Outputs
Configure data destinations:
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

#### Available Adapters
- **HelloWorld**: Demo adapter for testing
- Install more from the Adapters tab

#### Pro Tips
- Use proper YAML indentation (2 spaces)
- Check logs for validation errors
- Test configurations incrementally
- Use fallback chains for reliability
