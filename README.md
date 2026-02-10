# Adapter Framework for Equipment Monitoring and Control

The Lab Equipment Adapter Framework (LEAF) implements an **Adapter Architecture** designed to monitor and control various equipment types (e.g., bioreactors). The core principle of LEAF is to reduce the barrier to entry as much as possible to develop and deploy adapters for new equipment. The **EquipmentAdapters** are the functional equipment monitors composed of the rest of the **modules** (ProcessModules, PhaseModules, etc.) that perform specific tasks such as event monitoring, data processing, and output transmission.

## Quick Start

```bash
# Install LEAF
pip install leaf-framework

# Run with desktop GUI (auto-opens browser)
leaf
```

LEAF automatically shows a **desktop control panel** on desktop systems, making it easy to see if the application is running and where to access it.

## Documentation

The complete documentation can be found [here](http://leaf.systemsbiology.nl).