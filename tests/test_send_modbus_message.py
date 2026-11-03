import asyncio
import unittest

from tcp_modbus_aio.client import TCPModbusClient
from tcp_modbus_aio.exceptions import ModbusCommunicationFailureError
from tcp_modbus_aio.typed_functions import ReadCoils

MBAP_SIZE = 7


def read_coils() -> ReadCoils:
    msg = ReadCoils()
    msg.starting_address = 0
    msg.quantity = 1
    return msg


class FlakyServer:
    """
    Local TCP server that drops the first connection as soon as a request
    arrives (like a device resetting the socket), then accepts requests on
    later connections without ever answering them.
    """

    def __init__(self) -> None:
        self.connections = 0
        self.server: asyncio.AbstractServer | None = None

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        try:
            await reader.readexactly(MBAP_SIZE)
            if self.connections == 1:
                return
            await reader.read()  # never respond
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self.server is not None
        self.server.close()


class TestRetryKeepsErrorOnNoResponse(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = FlakyServer()
        port = await self.server.start()
        self.client = TCPModbusClient("127.0.0.1", port, enforce_pingable=False)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.stop()

    async def test_no_response_after_retry_returns_none(self) -> None:
        response = await self.client.send_modbus_message(
            read_coils(), timeout=0.2, error_on_no_response=False
        )
        self.assertIsNone(response)
        self.assertEqual(self.server.connections, 2)

    async def test_no_response_after_retry_raises_by_default(self) -> None:
        with self.assertRaises(ModbusCommunicationFailureError):
            await self.client.send_modbus_message(read_coils(), timeout=0.2)
        self.assertEqual(self.server.connections, 2)


if __name__ == "__main__":
    unittest.main()
