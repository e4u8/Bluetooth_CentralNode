# Central Node — BLE Energy Monitor

Python-based Central Node for the DA14706 wireless energy monitor thesis project.
Connects to the MCU over Bluetooth Low Energy, receives sensor measurements at 1 Hz,
controls a relay, and logs data to disk.

---

## Requirements

Python 3.8 or higher.

```bash
pip install bleak PyQt5 matplotlib numpy
```

---

## Hardware

| Device | Role |
|---|---|
| Renesas DA14706 (DA1470x Dev Kit) | BLE peripheral — sensor node |
| LEM HLSR 10P | AC current sensor (ADC CH0) |
| BEL DPC12 transformer | AC voltage sensor (ADC CH1) |
| I²C temp/humidity sensor | MikroBUS 1 |
| Soldered 333024 relay | MikroBUS 2 GPIO |
| Windows laptop | Central Node (this script) |

**MCU BLE address:** `48:23:35:F4:00:07`

---

## BLE Service

| Characteristic | UUID | Direction | Size | Purpose |
|---|---|---|---|---|
| Relay | `11111111-0000-0000-0000-111111111111` | R/W/Notify | 1 byte | Relay control + state |
| Measurements | `22222222-0000-0000-0000-222222222222` | Notify | 15 bytes | Sensor data @ 1 Hz |

### Measurement Packet Layout

Packed struct, little-endian, 15 bytes total:

| Field | Type | Scale | Example | Physical value |
|---|---|---|---|---|
| v_rms | int16 | ÷100 | 23045 | 230.45 V |
| i_rms | int16 | ÷1000 | 1500 | 1.500 A |
| p_w | int32 | ÷100 | 12345 | 123.45 W |
| freq | int16 | ÷100 | 5000 | 50.00 Hz |
| temp | int16 | ÷100 | 2150 | 21.50 °C |
| humid | uint16 | ÷100 | 6000 | 60.00 % |
| relay_state | uint8 | — | 1 | ON |

### Derived Quantities (computed on CN side)

| Quantity | Formula |
|---|---|
| Apparent power S | V × I |
| Reactive power Q | √(S² − P²) |
| Power factor PF | P / S |

### Noise Suppression

Small ADC noise with no load is clamped to zero before any computation:

| Signal | Threshold |
|---|---|
| Vrms | ≤ 0.55 V → set to 0 |
| Irms | ≤ 0.356 A → set to 0 |

When either is zeroed, active power P is also forced to zero.

---

## Running

```bash
python central_node.py
```

Opens a dark dashboard window with:
- Live numeric tiles for all measurements (Vrms, Irms, P, S, Q, PF, freq, temp, humidity)
- Relay indicator (ON/OFF) with ON, OFF, and TOGGLE buttons
- Start Logging / Stop Logging buttons
- Show Plots button — opens a separate window with live Vrms, Irms, and P charts
- Status bar showing connection state and logging state

The script connects automatically on launch and reconnects after 5 s if the MCU disconnects.
Close the window to exit.

---

## Log Files

Logging is **off by default.** Click **Start Logging** to begin.

**Location:** `Desktop/sensor_node1/`

**Filename format:** `sensor_node1-DD.MM.YY.txt` (e.g. `sensor_node1-23.06.26.txt`)

A new file is created each day. If the file for today already exists, new rows are appended.

**Format:** CSV with header row.

```
timestamp,v_rms_V,i_rms_A,p_W,s_VA,q_VAr,pf,freq_Hz,temp_C,humid_pct,relay_state
2026-06-23 20:15:01,230.45,1.500,310.20,345.68,156.32,0.897,50.00,21.50,60.00,OFF
2026-06-23 20:15:02,230.48,1.501,310.35,345.89,156.18,0.897,50.00,21.51,60.00,OFF
```

The CSV format can be opened directly in Excel or imported into Python with pandas.

---

## Project Structure

```
Bluetooth_CentralNode/
├── central_node.py   # GUI dashboard (BLE worker + live plots + logging)
└── README.md         # This file
```

---

## Planned Extensions

- [ ] Colour feedback on tiles when values go outside normal range
- [ ] ZCD-based frequency measurement on MCU side (freq field currently placeholder 0)
- [ ] Parametric configuration from CN (sampling frequency, window size)
