import asyncio
import logging
import random
import socket
import struct
import time
import uuid
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar

from cachetools import TTLCache
from typing_extensions import Self
from umodbus.functions import ModbusFunction

from tcp_modbus_aio.exceptions import (
    ModbusCommunicationFailureError,
    ModbusNotConnectedError,
)
from tcp_modbus_aio.ping import ping_ip
from tcp_modbus_aio.typed_functions import (
    ModbusFunctionT,
    ReadCoils,
    create_function_from_response_pdu,
)


@dataclass
class CoilWatchStatus:
    msg: ModbusFunction

    memo_key: Any
    expiry: float
    hz: float
    task: asyncio.Task | None = None


TEST_CONNECTION_MESSAGE = ReadCoils()
TEST_CONNECTION_MESSAGE.starting_address = 0
TEST_CONNECTION_MESSAGE.quantity = 1


@dataclass
class TCPModbusClient:
    KEEPALIVE_AFTER_IDLE_SEC: ClassVar = 10
    KEEPALIVE_INTERVAL_SEC: ClassVar = 10
    KEEPALIVE_MAX_FAILS: ClassVar = 5

    PING_LOOP_PERIOD: ClassVar = 1

    DEFAULT_MODBUS_TIMEOUT_SEC: ClassVar = 0.1
    MAX_TRANSACTION_ID: ClassVar = 2**16 - 1  # maximum number that fits in 2 bytes
    MODBUS_MBAP_SIZE: ClassVar = 7
    MBAP_HEADER_STRUCT_FORMAT: ClassVar = ">HHHB"

    def __init__(
        self,
        host: str,
        port: int = 502,
        slave_id: int = 1,
        logger: logging.Logger | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.logger = logger

        # Unique identifier for this client (used only for logging)
        self._id = uuid.uuid4()

        # TCP reader and writer objects for active connection, or None if no connection
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

        # Last ping time in seconds from ping loop, or None if the last ping failed
        self._last_ping: float | None = None

        # Task that pings the device every second
        self._ping_loop: asyncio.Task | None = asyncio.create_task(
            self._ping_loop_task(),
            name=f"TCPModbusClient._ping_loop_task[{self.host}:{self.port}]",
        )

        # List of CoilWatchStatus objects that are being logged
        self._log_watches = list[CoilWatchStatus]()

        # We cache anly active awaitable testing TCP connectivity to prevent spamming the connection
        self._active_connection_probe: asyncio.Task | None = None

        # We track this number because the ADAM module has a firmware bug where it will stop responding
        # if there are 24 unclosed connections within a 1000s period.  Hopefully if we see this happening
        # we can see it in logs because of this.
        self._lifetime_tcp_connection_num = 0

        # Lock to prevent multiple concurrent requests on the same connection.  In theory this should not be
        # necessary because the MODBUS protocol is designed to handle multiple requests on the same connection,
        # but my hope is that the performance impact of this lock is minimal, and the complexity/risk of
        # concurrent requests is high enough that I'm ok with the tradeoff.
        self._comms_lock = asyncio.Lock()

        # If we succesfully write a request but the response times out, we cache the transaction ID here
        # so we know to throw it away if we see it again.
        self._lost_transaction_ids = TTLCache[int, bool](maxsize=1000, ttl=60)

        # Instead of randomly sampling transaction IDs, we can use a global counter with random seed.
        # This way, we can avoid duplicate transaction IDs via birthday paradox.
        self._next_transaction_id = random.randint(0, self.MAX_TRANSACTION_ID)

    def __repr__(self) -> str:
        last_ping_msg = (
            f"{self._last_ping*1000:.1f}ms ping"
            if self._last_ping is not None
            else "no ping"
        )
        return (
            f"{self.__class__.__name__}({str(self._id)[:4]})[{self.host}:{self.port}]"
            f"[{last_ping_msg}, conn #{self._lifetime_tcp_connection_num}]"
        )

    async def _ping_loop_task(self) -> None:
        while True:
            self._last_ping = await ping_ip(self.host)
            if self.logger is not None:
                self.logger.debug(f"[{self}][_ping_loop_task] ping ping ping")

            await asyncio.sleep(self.PING_LOOP_PERIOD)

    async def _get_tcp_connection(
        self, timeout: float | None = DEFAULT_MODBUS_TIMEOUT_SEC
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._reader is None or self._writer is None:
            self._lifetime_tcp_connection_num += 1

            if self.logger is not None:
                self.logger.info(
                    f"[{self}][_get_tcp_connection] creating new TCP connection (#{self._lifetime_tcp_connection_num})"
                )

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host=self.host, port=self.port), timeout
                )

                sock: socket.socket = writer.get_extra_info("socket")

                # Receive and send buffers set to 900 bytes (recommended by MODBUS implementation guide: this is
                # becuase the max request size is 256 bytes + the header size of 7 bytes = 263 bytes, and the
                # max response size is 256 bytes + the header size of 7 bytes = 263 bytes, so a 900 byte buffer
                # can store 3 frames of buffering, which is apparently the suggestion).
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 900)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 900)

                # Reuse address (perf optimization, recommended by MODBUS implementation guide)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                # Enable TCP_NODELAY (prevent small packet buffering, recommended by MODBUS implementation guide)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                # Enable TCP keepalive (otherwise the Adam connection will terminate after 720 (1000?) seconds
                # with an open idle connection: this is also recommended by the MODBUS implementation guide)
                #
                # In most cases this is not necessary because Adam commands are short lived and we
                # close the connection after each command. However, if we want to keep a connection
                # open for a long time we would need to enable keepalive.

                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "TCP_KEEPIDLE"):
                    # Only available on Linux so this makes typing work cross platform
                    sock.setsockopt(
                        socket.IPPROTO_TCP,
                        socket.TCP_KEEPIDLE,
                        self.KEEPALIVE_AFTER_IDLE_SEC,
                    )

                sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPINTVL,
                    self.KEEPALIVE_INTERVAL_SEC,
                )
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPCNT, self.KEEPALIVE_MAX_FAILS
                )

                self._reader, self._writer = reader, writer
            except (asyncio.TimeoutError, OSError):
                msg = f"Cannot connect to TCP modbus device at {self.host}:{self.port}"
                if self.logger is not None:
                    self.logger.warning(f"[{self}][_get_tcp_connection] {msg}")
                raise ModbusNotConnectedError(msg)
        else:
            reader, writer = self._reader, self._writer

        return reader, writer

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self.clear_tcp_connection()

        if self._ping_loop is not None:
            if self.logger is not None:
                self.logger.debug(f"[{self}][close] Cancelling ping loop")
            self._ping_loop.cancel()
            self._ping_loop = None

    def log_watch(
        self, msg: ModbusFunction, *, memo_key: Any, period: float, hz: float
    ) -> None:
        """
        Triggers a loop that reads the coil(s) at the given index at the given frequency and
        writes the current values to logs for debugging purposes.

        This debug loop expires after the given period, but is refreshed every time this request_function
        is called.
        """

        for watch in self._log_watches:
            if watch.memo_key == memo_key:
                watch.expiry = time.perf_counter() + period
                watch.hz = hz
                watch.msg = msg

                break
        else:
            watch = CoilWatchStatus(
                memo_key=memo_key,
                expiry=time.perf_counter() + period,
                hz=hz,
                msg=msg,
            )
            self._log_watches.append(watch)

        if watch.task and not watch.task.done():
            # task is already running, we're gucci
            return

        log_prefix = f"[{self.host}:_watch_loop({watch.memo_key=})]"

        async def _watch_loop() -> None:
            if self.logger is not None:
                self.logger.debug(f"{log_prefix} coil watch started")

            while True:
                if time.perf_counter() > watch.expiry:
                    if self.logger is not None:
                        self.logger.debug(f"{log_prefix} coil watch expired")

                    self._log_watches.remove(watch)
                    return

                try:
                    response = await self.send_modbus_message(
                        watch.msg, timeout=1 / watch.hz
                    )

                    if self.logger is not None:
                        self.logger.debug(f"[{log_prefix}] {response=}")

                except Exception:
                    if self.logger is not None:
                        self.logger.exception(
                            f"{log_prefix} got error reading {watch.memo_key=}"
                        )

                await asyncio.sleep(1 / watch.hz)

        watch.task = asyncio.create_task(
            _watch_loop(), name=f"TCPModbusClient{log_prefix}"
        )

    async def clear_tcp_connection(self) -> None:
        if self._writer is not None:
            if self.logger is not None:
                self.logger.warning(
                    f"[{self}][clear_tcp_connection] closing TCP connection #{self._lifetime_tcp_connection_num}"
                )

            self._writer.close()
            await self._writer.wait_closed()

        self._reader = None
        self._writer = None

    async def test_connection(
        self, timeout: float | None = DEFAULT_MODBUS_TIMEOUT_SEC
    ) -> None:
        """
        Uses a cached awaitable to prevent spamming the connection on this call
        """

        try:
            if self._active_connection_probe is None:
                self._active_connection_probe = asyncio.create_task(
                    self.send_modbus_message(TEST_CONNECTION_MESSAGE, timeout=timeout),
                    name=f"TCPModbusClient.test_connection({self.host}:{self.port})",
                )

            await self._active_connection_probe
        finally:
            self._active_connection_probe = None

    async def send_modbus_message(
        self,
        request_function: ModbusFunctionT,
        timeout: float | None = DEFAULT_MODBUS_TIMEOUT_SEC,
        retries: int = 1,
        error_on_no_response: bool = True,
    ) -> ModbusFunctionT | None:
        """Send ADU over socket to to server and return parsed response.

        :param adu: Request ADU.
        :param sock: Socket instance.
        :return: Parsed response from server.
        """

        request_transaction_id = self._next_transaction_id
        self._next_transaction_id = (
            self._next_transaction_id + 1
        ) % self.MAX_TRANSACTION_ID

        msg_str = f"{request_function.__class__.__name__}[{request_transaction_id}]"

        request_mbap_header = struct.pack(
            self.MBAP_HEADER_STRUCT_FORMAT,
            request_transaction_id,
            0,
            len(request_function.request_pdu) + 1,
            self.slave_id,
        )

        request_adu = request_mbap_header + request_function.request_pdu

        if self.logger is not None:
            self.logger.debug(
                f"[{self}][send_modbus_message] sending request {msg_str}: {request_adu=}"
            )

        async with self._comms_lock:
            if self.logger is not None:
                self.logger.debug(
                    f"[{self}][send_modbus_message] acquired lock to send {msg_str}"
                )

            reader, writer = await self._get_tcp_connection(timeout=timeout)

            try:
                writer.write(request_adu)
                await asyncio.wait_for(writer.drain(), timeout)

                if self.logger is not None:
                    self.logger.debug(f"[{self}][send_modbus_message] wrote {msg_str}")

            except (asyncio.TimeoutError, OSError):
                if retries > 0:
                    if self.logger is not None:
                        self.logger.warning(
                            f"[{self}][send_modbus_message] Failed to send data to modbus device for "
                            f"request {msg_str}, retrying {retries} more time(s)"
                        )

                    await self.clear_tcp_connection()

                    return await self.send_modbus_message(
                        request_function,
                        timeout=timeout,
                        retries=retries - 1,
                    )

                raise ModbusCommunicationFailureError(
                    f"Failed to write request {msg_str} to modbus device {self.host}"
                )

            expected_response_size = (
                request_function.expected_response_pdu_size + self.MODBUS_MBAP_SIZE
            )

            try:
                seen_response_transaction_ids = []
                while True:
                    response_adu = await asyncio.wait_for(
                        reader.read(expected_response_size), timeout=timeout
                    )

                    response_pdu = response_adu[self.MODBUS_MBAP_SIZE :]
                    response_mbap_header = response_adu[: self.MODBUS_MBAP_SIZE]

                    (
                        response_transaction_id,
                        _,
                        mbap_asserted_pdu_length_plus_one,
                        response_asserted_slave_id,
                    ) = struct.unpack(
                        self.MBAP_HEADER_STRUCT_FORMAT, response_mbap_header
                    )

                    seen_response_transaction_ids.append(response_transaction_id)

                    if response_transaction_id in self._lost_transaction_ids:
                        self._lost_transaction_ids.pop(response_transaction_id)
                        if self.logger is not None:
                            self.logger.warning(
                                f"[{self}][send_modbus_message] Received response {response_transaction_id} for "
                                f"request {msg_str} that was previously lost, skipping"
                            )

                        continue

                    elif len(response_adu) != expected_response_size:
                        msg = (
                            f"[{self}][send_modbus_message] Received response {response_transaction_id} for "
                            f"request {msg_str} with unexpected size {len(response_adu)}, expected "
                            f"{expected_response_size}"
                        )

                        if self.logger is not None:
                            self.logger.error(msg)

                        raise ModbusCommunicationFailureError(msg)

                    elif response_asserted_slave_id != self.slave_id:
                        raise ModbusCommunicationFailureError(
                            f"Response slave ID {response_asserted_slave_id} does not match expected "
                            f"{self.slave_id} on {self.host}"
                        )

                    elif mbap_asserted_pdu_length_plus_one != len(response_pdu) + 1:
                        raise ModbusCommunicationFailureError(
                            f"Response PDU length {len(response_pdu)} does not match expected "
                            f"{mbap_asserted_pdu_length_plus_one-1} on {self.host}"
                        )

                    break

            except asyncio.TimeoutError:
                self._lost_transaction_ids[request_transaction_id] = True

                if error_on_no_response:
                    raise ModbusCommunicationFailureError(
                        f"Failed to read response to {msg_str} from modbus device {self.host} "
                        f"({seen_response_transaction_ids=})"
                    )

                else:
                    if self.logger is not None:
                        self.logger.warning(
                            f"[{self}][send_modbus_message] failed to read response to {msg_str}"
                        )

                    return None

        mismatch = response_transaction_id != request_transaction_id

        response_function = create_function_from_response_pdu(
            response_pdu, request_function
        )

        response_msg = (
            f"{response_function.__class__.__name__}[{response_transaction_id}]"
        )

        if self.logger is not None:
            self.logger.debug(
                f"[{self}][send_modbus_message] received response {response_msg} for request "
                f"{msg_str} ({mismatch=} {response_function.data=} {response_pdu=} {len(response_pdu)=})"
            )

        if mismatch:
            msg = (
                f"Response transaction ID {response_transaction_id} does not match request "
                f"{msg_str} on {self.host}"
            )

            if self.logger is not None:
                self.logger.error(
                    f"[{self}][send_modbus_message] {msg} {response_adu=}"
                )

            raise ModbusCommunicationFailureError(msg)

        return response_function
