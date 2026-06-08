import asyncio
from bleak import BleakClient

ADDRESS = "48:23:35:F4:00:07"
RELAY_UUID = "11111111-0000-0000-0000-111111111111"

def on_notification(sender, data):
    print(f"Raw bytes: {data.hex()}")

async def main():
    print("Connecting...")
    async with BleakClient(ADDRESS) as client:
        print(f"Connected: {client.is_connected}")
        await client.start_notify(RELAY_UUID, on_notification)
        print("Listening for notifications for 30 seconds...")
        await asyncio.sleep(30)
        print("Done.")

asyncio.run(main())