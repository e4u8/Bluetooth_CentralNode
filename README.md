# Bluetooth Central Node

A minimal Python BLE central node that connects to a **Renesas DA14706** peripheral and listens for notifications on a relay control characteristic.

This is the companion host-side project to [ble_relay_ctrl](../ble_relay_ctrl), which runs on the DA14706 and exposes the BLE relay service.

## How it works

The script connects to the DA14706 by its Bluetooth address, subscribes to a custom GATT characteristic, and prints raw notification bytes for 30 seconds before disconnecting.

| Parameter | Value |
|-----------|-------|
| Target device address | `48:23:35:F4:00:07` |
| Characteristic UUID | `11111111-0000-0000-0000-111111111111` |
| Listen duration | 30 seconds |

## Requirements

- Python 3.7+
- [Bleak](https://github.com/hbldh/bleak) — cross-platform BLE library

```bash
pip install bleak
```

## Usage

```bash
python central_node.py
```

Update `ADDRESS` in [central_node.py](central_node.py) if your DA14706 has a different Bluetooth address.

## Related projects

- **ble_relay_ctrl** — firmware running on the Renesas DA14706 that exposes the BLE relay control service this script subscribes to.
