import asyncio
import struct
import sys
import traceback
import os
from datetime import datetime
from pathlib import Path
from bleak import BleakClient, BleakError

ADDRESS    = "48:23:35:F4:00:07"
RELAY_UUID = "11111111-0000-0000-0000-111111111111"
MEAS_UUID  = "22222222-0000-0000-0000-222222222222"

RECONNECT_DELAY = 5   # seconds between reconnect attempts

# Packed layout (little-endian, 15 bytes total):
#   v_rms  int16  centivolts       23045 = 230.45 V
#   i_rms  int16  milliamps         1500 =   1.500 A
#   p_w    int32  centiwatts       12345 = 123.45 W
#   freq   int16  centi-Hz          5000 =  50.00 Hz  (placeholder)
#   temp   int16  centi-°C          2150 =  21.50 °C
#   humid  uint16 centi-%RH         6000 =  60.00 %
#   relay  uint8  0=OFF 1=ON
MEAS_FMT = "<hhihhHB"
MEAS_LEN = struct.calcsize(MEAS_FMT)   # 15


# ── Logger ────────────────────────────────────────────────────────────────────
#
# Usage from GUI in the future:
#   logger.start()   ← call this when the user presses "Start Logging"
#   logger.stop()    ← call this when the user presses "Stop Logging"
#   logger.is_active ← bind to a status label / LED indicator
#
# The log file is created on start() and closed on stop().
# A new file is created each time start() is called, using the current date.
# If the file for today already exists, new rows are appended to it.
#
class Logger:
    FOLDER_NAME = "sensor_node1"

    def __init__(self):
        self._file   = None
        self.is_active = False

    def _log_path(self) -> Path:
        desktop  = Path.home() / "Desktop"
        folder   = desktop / self.FOLDER_NAME
        folder.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%d.%m.%y")          # e.g. 10.06.26
        filename = f"sensor_node1-{date_str}.txt"
        return folder / filename

    def start(self):
        if self.is_active:
            return
        path = self._log_path()
        file_exists = path.exists()
        self._file  = open(path, "a", encoding="utf-8")         # append mode
        if not file_exists:
            # Write header on first creation
            self._file.write(
                "timestamp,v_rms_V,i_rms_A,p_W,s_VA,q_VAr,pf,"
                "freq_Hz,temp_C,humid_pct,relay_state\n"
            )
            self._file.flush()
        self.is_active = True
        print(f"[Logger] Logging started → {path}")

    def stop(self):
        if not self.is_active:
            return
        self._file.close()
        self._file     = None
        self.is_active = False
        print("[Logger] Logging stopped.")

    def write(self, row: dict):
        """Write one measurement row. Called once per BLE notification."""
        if not self.is_active or self._file is None:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._file.write(
            f"{ts},"
            f"{row['v_rms']:.2f},"
            f"{row['i_rms']:.3f},"
            f"{row['p_w']:.2f},"
            f"{row['s_va']:.2f},"
            f"{row['q_var']:.2f},"
            f"{row['pf']:.3f},"
            f"{row['freq']:.2f},"
            f"{row['temp']:.2f},"
            f"{row['humid']:.2f},"
            f"{'ON' if row['relay'] else 'OFF'}\n"
        )
        self._file.flush()   # ensure data reaches disk even if script is killed


# ── Global logger instance ────────────────────────────────────────────────────
logger = Logger()


# ── Derived quantities ────────────────────────────────────────────────────────
def compute_derived(v_rms: float, i_rms: float, p_w: float) -> dict:
    """
    Compute apparent power S, reactive power Q, and power factor PF
    from the three values received over BLE.

    S  = V * I
    Q  = sqrt( max(S^2 - P^2, 0) )   — max() guards against float rounding
    PF = P / S                        — undefined if S == 0
    """
    s_va  = v_rms * i_rms
    q_var = (s_va ** 2 - p_w ** 2)
    q_var = (q_var ** 0.5) if q_var > 0 else 0.0
    pf    = (p_w / s_va) if s_va > 0.0 else 0.0
    return {"s_va": s_va, "q_var": q_var, "pf": pf}


# ── BLE callbacks ─────────────────────────────────────────────────────────────
def on_relay_notification(sender, data: bytearray):
    try:
        state = "ON" if data[0] == 0x01 else "OFF"
        print(f"[Relay notify] state={state}")
    except Exception:
        traceback.print_exc()


def on_measurement_notification(sender, data: bytearray):
    try:
        if len(data) != MEAS_LEN:
            print(f"[Meas notify] unexpected length {len(data)} "
                  f"(expected {MEAS_LEN}): {data.hex()}")
            return

        v_raw, i_raw, p_raw, freq_raw, temp_raw, humid_raw, relay = \
            struct.unpack(MEAS_FMT, data)

        # Convert fixed-point integers to physical values
        v_rms = v_raw   / 100.0     # centivolts  → V
        i_rms = i_raw   / 1000.0    # milliamps   → A
        p_w   = p_raw   / 100.0     # centiwatts  → W
        freq  = freq_raw / 100.0    # centi-Hz    → Hz
        temp  = temp_raw / 100.0    # centi-°C    → °C
        humid = humid_raw / 100.0   # centi-%RH   → %

        derived = compute_derived(v_rms, i_rms, p_w)

        # Print to terminal
        print(
            f"Vrms={v_rms:.2f} V  "
            f"Irms={i_rms:.3f} A  "
            f"P={p_w:.2f} W  "
            f"S={derived['s_va']:.2f} VA  "
            f"Q={derived['q_var']:.2f} VAr  "
            f"PF={derived['pf']:.3f}  "
            f"f={freq:.2f} Hz  "
            f"T={temp:.2f} °C  "
            f"H={humid:.2f}%  "
            f"Relay={'ON' if relay else 'OFF'}"
        )

        # Log to file (only if logger is active)
        logger.write({
            "v_rms": v_rms, "i_rms": i_rms, "p_w": p_w,
            "s_va":  derived["s_va"],
            "q_var": derived["q_var"],
            "pf":    derived["pf"],
            "freq":  freq, "temp": temp, "humid": humid, "relay": relay
        })

    except Exception:
        traceback.print_exc()


# ── Relay + logger command input ──────────────────────────────────────────────
async def input_loop(cmd_queue: asyncio.Queue):
    """
    Read commands from stdin.

    Relay:   on / off / toggle (or t)
    Logger:  log start / log stop
    """
    loop = asyncio.get_running_loop()
    print("Commands: 'on'  'off'  'toggle'  'log start'  'log stop'")
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        cmd  = line.strip().lower()
        if cmd in ("on", "off", "toggle", "t"):
            await cmd_queue.put(cmd)
        elif cmd == "log start":
            logger.start()
        elif cmd == "log stop":
            logger.stop()
        else:
            if cmd:
                print(f"Unknown command: '{cmd}'")


# ── BLE session ───────────────────────────────────────────────────────────────
async def run_session(client: BleakClient, cmd_queue: asyncio.Queue):
    await client.start_notify(RELAY_UUID, on_relay_notification)
    await client.start_notify(MEAS_UUID,  on_measurement_notification)
    print("Subscribed. Listening for measurements...")

    while client.is_connected:
        try:
            cmd = cmd_queue.get_nowait()
        except asyncio.QueueEmpty:
            cmd = None

        if cmd is not None:
            try:
                if cmd == "on":
                    await client.write_gatt_char(RELAY_UUID, bytes([0x01]))
                elif cmd == "off":
                    await client.write_gatt_char(RELAY_UUID, bytes([0x00]))
                elif cmd in ("toggle", "t"):
                    await client.write_gatt_char(RELAY_UUID, bytes([0xFF]))
            except BleakError as e:
                print(f"[relay write failed: {e}]")

        await asyncio.sleep(0.2)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    cmd_queue: asyncio.Queue = asyncio.Queue()
    asyncio.ensure_future(input_loop(cmd_queue))

    while True:
        print(f"Connecting to {ADDRESS} ...")
        try:
            async with BleakClient(ADDRESS) as client:
                print("Connected.")
                await run_session(client, cmd_queue)
                print("Disconnected.")
        except BleakError as e:
            print(f"BLE error: {e}")
        except Exception:
            traceback.print_exc()

        print(f"Reconnecting in {RECONNECT_DELAY} s ...")
        await asyncio.sleep(RECONNECT_DELAY)


asyncio.run(main())