import asyncio
import logging
import random
import socket
import struct
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from cachetools import TTLCache

from tcp_modbus_aio.exceptions import (
    ModbusCommunicationFailureError,
    ModbusCommunicationTimeoutError,
    ModbusNotConnectedError,
)
from tcp_modbus_aio.ping import ping_ip
from tcp_modbus_aio.typed_functions import (
    ModbusFunctionT,
    ReadCoils,
    create_function_from_response_pdu,
)
from tcp_modbus_aio.utils import catchtime

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self
    from umodbus.functions import ModbusFunction


@dataclass
class CoilWatchStatus:
    msg: "ModbusFunction"

    memo_key: Any
    expiry: float
    hz: float
    task: asyncio.Task | None = None


TEST_CONNECTION_MESSAGE = ReadCoils()
TEST_CONNECTION_MESSAGE.starting_address = 0
TEST_CONNECTION_MESSAGE.quantity = 1

DEFAULT_MODBUS_TIMEOUT_SEC = 0.1
MAX_TRANSACTION_ID = 2**16 - 1  # maximum number that fits in 2 bytes
MODBUS_MBAP_SIZE = 7
MBAP_HEADER_STRUCT_FORMAT = ">HHHB"


@dataclass
class TCPModbusClient:
    KEEPALIVE_AFTER_IDLE_SEC: ClassVar = 10
    KEEPALIVE_INTERVAL_SEC: ClassVar = 10
    KEEPALIVE_MAX_FAILS: ClassVar = 5

    PING_LOOP_PERIOD: ClassVar = 1
    CONSECUTIVE_TIMEOUTS_TO_RECONNECT: ClassVar = 5

    def __init__(
        self,
        host: str,
        port: int = 502,
        slave_id: int = 1,
        *,
        logger: logging.Logger | None = None,
        enforce_pingable: bool = True,
        ping_timeout: float = 0.5,
    ) -> None:
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.logger = logger
        self.ping_timeout = ping_timeout

        # If True, will throw an exception if attempting to send a request and the device is not pingable
        self.enforce_pingable = enforce_pingable

        # Unique identifier for this client (used only for logging)
        self._id = uuid.uuid4()

        # TCP reader and writer objects for active connection, or None if no connection
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

        # Number of current consecutive modbus calls that resulted in a timeout
        self._consecutive_timeouts = 0

        # Last ping time in seconds from ping loop, or None if the last ping failed
        self._last_ping: float | None = None

        # Task that pings the device every second
        self._ping_loop: asyncio.Task | None = asyncio.create_task(
            self._ping_loop_task(),
            name=f"TCPModbusClient._ping_loop_task[{self.host}:{self.port}]",
        )

        # Event that is set when the first ping is received
        self._first_ping_event: asyncio.Event = asyncio.Event()

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
        self._next_transaction_id = random.randint(0, MAX_TRANSACTION_ID)

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
            self._last_ping = await ping_ip(self.host, timeout=self.ping_timeout)

            if self.logger is not None:
                self.logger.debug(f"[{self}][_ping_loop_task] ping ping ping")

            self._first_ping_event.set()
            await asyncio.sleep(self.PING_LOOP_PERIOD)

    async def _get_tcp_connection(
        self, timeout: float | None = DEFAULT_MODBUS_TIMEOUT_SEC
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._reader is not None and self._writer is not None:
            return self._reader, self._writer

        self._lifetime_tcp_connection_num += 1

        if self.logger is not None:
            self.logger.info(
                f"[{self}][_get_tcp_connection] creating new TCP connection (#{self._lifetime_tcp_connection_num})"
            )

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host=self.host, port=self.port), timeout
            )
        except asyncio.TimeoutError:
            msg = (
                f"Timed out connecting to TCP modbus device at {self.host}:{self.port}"
            )
            if self.logger is not None:
                self.logger.warning(f"[{self}][_get_tcp_connection] {msg}")
            raise ModbusCommunicationTimeoutError(msg)
        except OSError:
            msg = f"Cannot connect to TCP modbus device at {self.host}:{self.port}"
            if self.logger is not None:
                self.logger.warning(f"[{self}][_get_tcp_connection] {msg}")
            raise ModbusNotConnectedError(msg)

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

        return reader, writer

    async def __aenter__(self) -> "Self":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: "TracebackType | None",
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """
        Permanent close of the TCP connection and ping loop.  Only call this on final destruction of the object.
        """

        if self._ping_loop is None:
            return

        self.clear_tcp_connection()

        if self._ping_loop is not None:
            if self.logger is not None:
                self.logger.debug(f"[{self}][close] Cancelling ping loop")
            self._ping_loop.cancel()
            self._ping_loop = None

    def log_watch(
        self, msg: "ModbusFunction", *, memo_key: Any, period: float, hz: float
    ) -> None:
        """
        Triggers a loop that reads the coil(s) at the given index at the given frequency and
        writes the current values to logs for debugging purposes.

        This debug loop expires after the given period, but is refreshed every time this request_function
        is called.
        """

        if self._ping_loop is None:
            raise RuntimeError("Cannot log watch on closed TCPModbusClient")

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

    def clear_tcp_connection(self) -> None:
        """
        Closes the current TCP connection and clears the reader and writer objects.
        On the next send_modbus_message call, a new connection will be created.
        """

        self._consecutive_timeouts = 0

        if self._ping_loop is None:
            raise RuntimeError("Cannot clear TCP connection on closed TCPModbusClient")

        if self._writer is not None:
            if self.logger is not None:
                self.logger.warning(
                    f"[{self}][clear_tcp_connection] closing TCP connection #{self._lifetime_tcp_connection_num}"
                )

            self._writer.close()

        self._reader = None
        self._writer = None

    async def test_connection(
        self, timeout: float | None = DEFAULT_MODBUS_TIMEOUT_SEC
    ) -> None:
        """
        Tests the connection to the device by sending a ReadCoil message (see TEST_CONNECTION_MESSAGE)
        Uses a cached awaitable to prevent spamming the connection on this call
        """

        if self._ping_loop is None:
            raise RuntimeError("Cannot test connection on closed TCPModbusClient")

        try:
            if self._active_connection_probe is None:
                self._active_connection_probe = asyncio.create_task(
                    self.send_modbus_message(TEST_CONNECTION_MESSAGE, timeout=timeout),
                    name=f"TCPModbusClient.test_connection({self.host}:{self.port})",
                )

            await self._active_connection_probe
        finally:
            self._active_connection_probe = None

    async def is_pingable(self) -> bool:
        """
        Returns True if the device is pingable, False if not.
        Will wait for the first ping to be received (or timeout) before returning.
        """

        if self._ping_loop is None:
            raise RuntimeError("Cannot check pingability on closed TCPModbusClient")

        if not self._first_ping_event.is_set():
            await self._first_ping_event.wait()

        return self._last_ping is not None

    async def send_modbus_message(
        self,
        request_function: ModbusFunctionT,
        timeout: float | None = DEFAULT_MODBUS_TIMEOUT_SEC,
        retries: int = 1,
        error_on_no_response: bool = True,
    ) -> ModbusFunctionT | None:
        """
        Sends a modbus message to the device and returns the response.
        Will create a new TCP connection if one does not exist.
        """

        if self._ping_loop is None:
            raise RuntimeError("Cannot send modbus message on closed TCPModbusClient")

        if self.enforce_pingable and not await self.is_pingable():
            raise ModbusNotConnectedError(
                f"Cannot send modbus message to {self.host} because it is not pingable"
            )

        request_transaction_id = self._next_transaction_id
        self._next_transaction_id = (self._next_transaction_id + 1) % MAX_TRANSACTION_ID

        msg_str = f"{request_function.__class__.__name__}[{request_transaction_id}]"

        request_mbap_header = struct.pack(
            MBAP_HEADER_STRUCT_FORMAT,
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

        time_budget_remaining = timeout if timeout is not None else float("inf")

        # STEP ONE: WE ACQUIRE THE LOCK TO THE CONNECTION
        with catchtime() as lock_t:
            try:
                await asyncio.wait_for(
                    self._comms_lock.acquire(), time_budget_remaining
                )
            except asyncio.TimeoutError:
                raise ModbusCommunicationTimeoutError(
                    f"Failed to acquire lock to send request {msg_str} to modbus device {self.host}"
                )
        time_budget_remaining -= lock_t()

        try:
            if self.logger is not None:
                self.logger.debug(
                    f"[{self}][send_modbus_message] acquired lock to send {msg_str}"
                )

            # STEP TWO: CREATE A CONNECTION IF ONE DOES NOT EXIST
            with catchtime() as conn_t:
                reader, writer = await self._get_tcp_connection(
                    timeout=time_budget_remaining
                )

            time_budget_remaining -= conn_t()

            # STEP THREE: WRITE OUR REQUEST
            try:
                writer.write(request_adu)

                with catchtime() as write_t:
                    await asyncio.wait_for(writer.drain(), time_budget_remaining)
                time_budget_remaining -= write_t()

                if self.logger is not None:
                    self.logger.debug(f"[{self}][send_modbus_message] wrote {msg_str}")

            except OSError:  # this includes timeout errors
                # Clear connection no matter what if we fail on the write
                # TODO: consider revisiting this to not do it on a timeouterror
                # (but Gru is scared about partial writes)

                if self.logger is not None:
                    self.logger.warning(
                        f"[{self}][send_modbus_message] Failed to send data to modbus device for "
                        f"request {msg_str}, clearing connection"
                    )

                self.clear_tcp_connection()

                if retries > 0:
                    if self.logger is not None:
                        self.logger.warning(
                            f"[{self}][send_modbus_message] Retrying {retries} more time(s) after failure to write"
                        )

                    # release the lock before retrying (so we can re-get it)
                    self._comms_lock.release()

                    return await self.send_modbus_message(
                        request_function,
                        timeout=timeout,
                        retries=retries - 1,
                    )

                raise

            try:
                # STEP FOUR: READ THE MBAP HEADER FROM THE RESPONSE (AND ANY JUNK)
                expected_response_mbap_header = struct.pack(
                    MBAP_HEADER_STRUCT_FORMAT,
                    request_transaction_id,
                    0,
                    request_function.expected_response_pdu_size + 1,
                    self.slave_id,
                )

                with catchtime() as read_mbap_t:
                    response_up_to_mbap_header = await asyncio.wait_for(
                        reader.readuntil(expected_response_mbap_header),
                        timeout=time_budget_remaining,
                    )
                time_budget_remaining -= read_mbap_t()

                if len(response_up_to_mbap_header) > MODBUS_MBAP_SIZE:
                    # TODO: consider introspecting the discarded traffic here for better introspection
                    if self.logger is not None:
                        self.logger.warning(
                            f"[{self}][send_modbus_message] got {response_up_to_mbap_header[:MODBUS_MBAP_SIZE]!r} "
                            "before mbap header, likely catching up stream after timeouts"
                        )

                # STEP FOUR: READ THE RESPONSE PDU
                with catchtime() as read_pdu_time:
                    response_pdu = await asyncio.wait_for(
                        reader.readexactly(request_function.expected_response_pdu_size),
                        timeout=time_budget_remaining,
                    )
                time_budget_remaining -= read_pdu_time()

            except asyncio.TimeoutError:
                # Sometimes it is ok to not hear back
                if not error_on_no_response:
                    return None

                raise
        except asyncio.TimeoutError as e:
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= self.CONSECUTIVE_TIMEOUTS_TO_RECONNECT:
                if self.logger is not None:
                    self.logger.warning(
                        f"[{self}][send_modbus_message] {self._consecutive_timeouts} consecutive timeouts, "
                        "clearing connection"
                    )
                self.clear_tcp_connection()

            raise ModbusCommunicationTimeoutError(
                f"Request {msg_str} timed out to {self.host}:{self.port}"
            ) from e
        except OSError as e:
            if self.logger is not None:
                self.logger.warning(
                    f"[{self}][send_modbus_message] OSError{type(e).__name__}({e}) while sending request {msg_str}, "
                    "clearing connection"
                )

            self.clear_tcp_connection()

            raise ModbusCommunicationFailureError(
                f"Request {msg_str} failed to {self.host}:{self.port} ({type(e).__name__}({e}))"
            ) from e
        finally:
            if self._comms_lock.locked():
                self._comms_lock.release()

        self._consecutive_timeouts = 0

        if self.logger is not None:
            self.logger.debug(
                f"[{self}][send_modbus_message] executed request/response with timing "
                f"lock={1000*lock_t():0.2f}ms conn={1000*conn_t():0.2f}ms "
                f"write={1000*write_t():0.2f}ms read_mbap={1000*read_mbap_t():0.2f}ms "
                f"read_pdu={1000*read_pdu_time():0.2f}ms"
            )

        response_function = create_function_from_response_pdu(
            response_pdu, request_function
        )

        response_msg = (
            f"{response_function.__class__.__name__}[{request_transaction_id}]"
        )

        if self.logger is not None:
            self.logger.debug(
                f"[{self}][send_modbus_message] received response {response_msg} for request "
                f"{msg_str} {response_function.data=} {response_pdu=} {len(response_pdu)=})"
            )

        return response_function
