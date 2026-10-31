# Adapter Framework for Equipment Monitoring and Control

The Lightweight Equipment Adapter Framework (LEAF) implements an **Adapter Architecture** designed to monitor and control various equipment types (e.g., bioreactors). The core principle of LEAF is to reduce the barrier to entry as much as possible to develop and deploy adapters for new equipment. The **EquipmentAdapters** are the functional equipment monitors composed of the rest of the **modules** (ProcessModules, PhaseModules, etc.) that perform specific tasks such as event monitoring, data processing, and output transmission.

## Quick Start

```bash
# Install LEAF
pip install leaf-framework

# Run with desktop GUI (auto-opens browser)
leaf
```

LEAF automatically shows a **desktop control panel** on desktop systems, making it easy to see if the application is running and where to access it.

## Password for the web interface

The web interface is open by default. When it runs where others can reach it (a Kubernetes pod with an ingress, a shared server), set `LEAF_UI_PASSWORD`: every page then asks for that password once, on a login form password managers can fill, and keeps the browser logged in for 30 days. Changing the password logs every browser out. It sends the password over the wire, so serve the interface over HTTPS.

## Updating

LEAF checks PyPI for a newer release one hour after it starts, and weekly from then on -- never at startup, so a restart simply re-arms the one-hour delay. When a newer version exists, an **update badge** appears next to the version number in the web interface header; clicking it offers to install the update and restart LEAF.

To check without waiting for the schedule, **click the version number** in the header. The result appears as a banner: green when this install is current, amber when a newer release exists, red when PyPI could not be reached.

Set `LEAF_DISABLE_UPDATE_CHECK=1` to switch the check off entirely. Installs running from a source checkout are told about the new version but never overwritten -- update those with `git pull`. To update by hand:

```bash
pip install --upgrade leaf-framework
```

## Documentation

The complete documentation can be found [here](https://leaf-framework.org).