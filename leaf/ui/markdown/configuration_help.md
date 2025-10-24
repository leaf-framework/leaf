#### Equipment Instances
Define your laboratory equipment:
```yaml
EQUIPMENT_INSTANCES:
  - equipment:
      adapter: HelloWorld
      data:
        instance_id: my_device
        institute: university_lab
      requirements:
        interval: 30
```

#### Outputs
Configure data destinations:
```yaml
OUTPUTS:
  - plugin: KEYDB
    host: localhost
    port: 6379
    fallback: FILE
```

#### Available Adapters
- **HelloWorld**: Demo adapter for testing
- Install more from the Adapters tab

#### Pro Tips
- Use proper YAML indentation (2 spaces)
- Check logs for validation errors
- Test configurations incrementally
- Use fallback chains for reliability
