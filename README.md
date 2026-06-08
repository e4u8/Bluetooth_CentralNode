# Bluetooth Central Node

A Python BLE central node that connects to a **Renesas DA14706** peripheral, subscribes to relay state notifications, and sends relay control commands over a custom GATT characteristic.

This is the companion host-side project to [ble_relay_ctrl](../ble_relay_ctrl), which runs on the DA14706 and exposes the BLE relay service.

## How it works

The script connects to the DA14706 by its Bluetooth address, subscribes to relay state notifications, then sends a sequence of control commands (ON → OFF → TOGGLE) with a 2-second pause between each.

| Parameter | Value |
|-----------|-------|
| Target device address | `48:23:35:F4:00:07` |
| Characteristic UUID | `11111111-0000-0000-0000-111111111111` |

### Command bytes

| Command | Byte |
|---------|------|
| ON | `0x01` |
| OFF | `0x00` |
| TOGGLE | `0xFF` |

### Notification format

Incoming notifications decode the first byte: `0x01` → `Relay state: ON`, anything else → `Relay state: OFF`.

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

- **ble_relay_ctrl** — firmware running on the Renesas DA14706 that exposes the BLE relay control service this script communicates with.
