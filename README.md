# BLE Central Node

Python host application for the DA14706 BLE Energy Monitor sensor node.  
Connects over Bluetooth LE, receives live power/environmental measurements, and controls the relay.

## Requirements

- Python 3.9+
- [bleak](https://github.com/hbldh/bleak) BLE library

```
pip install bleak
```

## Configuration

Open `central_node.py` and update the two constants at the top if needed:

| Constant | Default | Description |
|---|---|---|
| `ADDRESS` | `48:23:35:F4:00:07` | BLE MAC address of the sensor node |
| `RECONNECT_DELAY` | `5` | Seconds to wait before a reconnect attempt |

The sensor node advertises as **BLE_Relay_Ctrl**. To find its MAC address, scan with nRF Connect or run a bleak scan:

```python
import asyncio
from bleak import BleakScanner
asyncio.run(BleakScanner.discover())
```

## Usage

```
python central_node.py
```

The script connects to the sensor node and starts printing one measurement line per second:

```
Vrms=238.07 V  Irms=4.383 A  P=1032.74 W  f=50.00 Hz  T=26.75 °C  H=39.00%  Relay=OFF
```

Press **Ctrl+C** to exit.

### Relay control

While the script is running, type a command and press Enter:

| Command | Action |
|---|---|
| `on` | Turn relay ON |
| `off` | Turn relay OFF |
| `toggle` or `t` | Toggle relay state |

Commands typed while the device is temporarily disconnected are queued and sent on the next successful reconnect.

## Automatic reconnection

If the BLE connection drops, the script waits `RECONNECT_DELAY` seconds and reconnects automatically. Notification subscriptions are re-established on each new connection.

## Measurement packet format

The sensor node sends a 15-byte little-endian notification on the measurement characteristic once per second.

| Field | Type | Unit | Example raw | Decoded |
|---|---|---|---|---|
| `v_rms` | int16 | centivolts | 23807 | 238.07 V |
| `i_rms` | int16 | milliamps | 4383 | 4.383 A |
| `p_w` | int32 | centiwatts | 103274 | 1032.74 W |
| `freq` | int16 | centi-Hz | 5000 | 50.00 Hz (placeholder) |
| `temp` | int16 | centi-°C | 2675 | 26.75 °C |
| `humid` | uint16 | centi-%RH | 3900 | 39.00 % |
| `relay_state` | uint8 | — | 0 / 1 | OFF / ON |

Struct format string: `"<hhihhHB"`

## BLE service / characteristic UUIDs

| Role | UUID |
|---|---|
| Custom service | `00000000-1111-2222-2222-333333333333` |
| Relay control (R/W/Notify) | `11111111-0000-0000-0000-111111111111` |
| Measurements (Notify) | `22222222-0000-0000-0000-222222222222` |

### Relay characteristic write values

| Value | Effect |
|---|---|
| `0x01` | ON |
| `0x00` | OFF |
| `0xFF` | TOGGLE |
