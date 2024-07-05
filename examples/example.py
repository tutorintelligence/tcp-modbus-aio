import asyncio

from umodbus.functions import WriteSingleCoil

from tcp_modbus_aio.client import TCPModbusClient
from tcp_modbus_aio.exceptions import ModbusCommunicationTimeoutError
from tcp_modbus_aio.typed_functions import ReadCoils

DIGITAL_IN_COILS = list(range(8))
DIGITAL_OUT_COILS = list(range(32, 32 + 12))


async def example() -> None:

    async with TCPModbusClient("192.168.250.207") as conn:
        for _ in range(1000):
            for digital_in_coil in DIGITAL_IN_COILS:
                example_message = ReadCoils()
                example_message.starting_address = digital_in_coil
                example_message.quantity = 1

                try:
                    response = await conn.send_modbus_message(
                        example_message, retries=0
                    )
                    assert response is not None, "we expect a response from ReadCoils"
                    print(response.data)  # noqa: T201
                except ModbusCommunicationTimeoutError as e:
                    print(f"{type(e).__name__}({e})")

            for digital_out_coil in DIGITAL_OUT_COILS:
                example_message = WriteSingleCoil()
                example_message.address = digital_out_coil
                example_message.value = False

                try:
                    await conn.send_modbus_message(example_message, retries=0)
                except ModbusCommunicationTimeoutError as e:
                    print(f"{type(e).__name__}({e})")


if __name__ == "__main__":
    asyncio.run(example())
