import asyncio
from bleak import BleakClient

ADDRESS = "48:23:35:F4:00:07"
RELAY_UUID = "11111111-0000-0000-0000-111111111111"

def on_notification(sender, data):
    state = "ON" if data[0] == 0x01 else "OFF"
    print(f"Relay state: {state}")

async def main():
    async with BleakClient(ADDRESS) as client:
        print(f"Connected: {client.is_connected}")
        await client.start_notify(RELAY_UUID, on_notification)

        # Send commands from laptop
        await client.write_gatt_char(RELAY_UUID, bytes([0x01]))  # ON
        await asyncio.sleep(2)
        await client.write_gatt_char(RELAY_UUID, bytes([0x00]))  # OFF
        await asyncio.sleep(2)
        await client.write_gatt_char(RELAY_UUID, bytes([0xFF]))  # TOGGLE
        await asyncio.sleep(2)

asyncio.run(main())