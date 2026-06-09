import asyncio
import struct
import sys
import traceback
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

def on_relay_notification(sender, data: bytearray):
    try:
        state = "ON" if data[0] == 0x01 else "OFF"
        print(f"[Relay notify] state={state}")
    except Exception:
        traceback.print_exc()

def on_measurement_notification(sender, data: bytearray):
    try:
        if len(data) != MEAS_LEN:
            print(f"[Meas notify] unexpected length {len(data)} (expected {MEAS_LEN}): {data.hex()}")
            return
        v_rms, i_rms, p_w, freq, temp, humid, relay = struct.unpack(MEAS_FMT, data)
        print(
            f"Vrms={v_rms/100:.2f} V  "
            f"Irms={i_rms/1000:.3f} A  "
            f"P={p_w/100:.2f} W  "
            f"f={freq/100:.2f} Hz  "
            f"T={temp/100:.2f} °C  "
            f"H={humid/100:.2f}%  "
            f"Relay={'ON' if relay else 'OFF'}"
        )
    except Exception:
        traceback.print_exc()

async def relay_input_loop(cmd_queue: asyncio.Queue):
    """Read relay commands from stdin and push them onto cmd_queue."""
    loop = asyncio.get_running_loop()
    print("Commands: 'on', 'off', 'toggle' — then Enter.")
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = line.strip().lower()
        if cmd in ("on", "off", "toggle", "t"):
            await cmd_queue.put(cmd)

async def run_session(client: BleakClient, cmd_queue: asyncio.Queue):
    """Subscribe and handle one connected session until disconnection."""
    await client.start_notify(RELAY_UUID, on_relay_notification)
    await client.start_notify(MEAS_UUID,  on_measurement_notification)
    print(f"Subscribed. Listening for measurements...")

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

async def main():
    cmd_queue: asyncio.Queue = asyncio.Queue()
    asyncio.ensure_future(relay_input_loop(cmd_queue))

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
