import asyncio
import struct

import pytest
from umodbus.exceptions import IllegalDataAddressError

import tcp_modbus_aio.client
from tcp_modbus_aio.client import TCPModbusClient
from tcp_modbus_aio.typed_functions import ReadCoils


async def _exception_reply_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    # Answer every request with a modbus exception reply: illegal data address (code 0x02)
    while True:
        try:
            header = await reader.readexactly(7)
        except asyncio.IncompleteReadError:
            break
        transaction_id, protocol_id, length, unit_id = struct.unpack(">HHHB", header)
        pdu = await reader.readexactly(length - 1)
        writer.write(struct.pack(">HHHBBB", transaction_id, protocol_id, 3, unit_id, pdu[0] | 0x80, 0x02))
        await writer.drain()
    writer.close()


async def _read_coil_from_exception_server() -> None:
    server = await asyncio.start_server(_exception_reply_server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = TCPModbusClient("127.0.0.1", port, enforce_pingable=False)
    try:
        request = ReadCoils()
        request.starting_address = 0
        request.quantity = 1
        await client.send_modbus_message(request, timeout=1.0)
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


async def _fake_ping_ip(*args: object, **kwargs: object) -> float:
    return 0.001


def test_exception_reply_raises_modbus_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the ping loop from spawning a real ping subprocess
    monkeypatch.setattr(tcp_modbus_aio.client, "ping_ip", _fake_ping_ip)
    with pytest.raises(IllegalDataAddressError):
        asyncio.run(_read_coil_from_exception_server())
