import asyncio

from aiosocks import Socks5Addr

from tcp_modbus_aio.client import TCPModbusClient
from tcp_modbus_aio.exceptions import (
    ModbusCommunicationFailureError,
    ModbusCommunicationTimeoutError,
)
from tcp_modbus_aio.typed_functions import ReadCoils

DIGITAL_IN_COILS = list(range(8))
DIGITAL_OUT_COILS = list(range(32, 32 + 12))


async def example() -> None:

    async with TCPModbusClient(
        "192.168.250.207",
        enforce_pingable=False,
        socks_proxy_addr=Socks5Addr("localhost", 1080),
    ) as conn:
        for _ in range(1000):
            for digital_in_coil in DIGITAL_IN_COILS:
                example_message = ReadCoils()
                example_message.starting_address = digital_in_coil
                example_message.quantity = 1

                try:
                    response = await conn.send_modbus_message(
                        example_message, timeout=0.02
                    )
                    assert response is not None, "we expect a response from ReadCoils"
                    print(response.data)  # noqa: T201
                except ModbusCommunicationTimeoutError as e:
                    print(f"{type(e).__name__}({e})")
                except ModbusCommunicationFailureError as e:
                    print(f"{type(e).__name__}({e})")


if __name__ == "__main__":
    asyncio.run(example())
