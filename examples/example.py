import asyncio

from umodbus.functions import ReadCoils

from tcp_modbus_aio.client import TCPModbusClient


async def example() -> None:
    example_message = ReadCoils()
    example_message.starting_address = 0
    example_message.quantity = 1

    async with TCPModbusClient("192.168.250.204") as conn:
        response = await conn.send_modbus_message(example_message)

    assert response is not None, "we expect a response from ReadCoils"
    print(response.data)


if __name__ == "__main__":
    asyncio.run(example())
