# tcp-modbus-aio

[![PyPI version](https://badge.fury.io/py/tcp-modbus-aio.svg)](https://badge.fury.io/py/tcp-modbus-aio)

asyncio client library for tcp modbus devices. built on top of [umodbus](https://pypi.org/project/uModbus/) but extended for more *industrial robustness* and asyncio compat. the [umodbus documentation](https://umodbus.readthedocs.io/en/latest/) is recommended reading to have any hope of using this code.

narrowly constructed for the use cases of [Tutor Intelligence](http://tutorintelligence.com/), but feel free to post an issue or PR if relevant to you.

### usage

create a `TCPModbusClient`. once you have it, you can call the following methods on it:
 - `await conn.send_modbus_message(request_function, **kwargs)`: sends a `umodbus.functions.ModbusFunction` to the modbus device and returns the corresponding `ModbusFunction` reply.
 - `await conn.test_connection()`: sends a modbus message to the device to ensure it's still operational (currently hardcoded to read coil 0) and return boolean of whether it succeeded. is implemented as a cached awaitable to allow you to spam this call.
 - `await conn.clear_tcp_connection()`: kill the current TCP socket (a new one will automatically be created for the next request)
 - `await conn.log_watch(msg, memo_key="system_temperature", expiry_period_s=10, hz=1)`: spins up a background coroutine to log the result of that message for the next `expiry_period` seconds at `hz` frequency. `memo_key` is used to allow multiple calls to `log_watch` without having overlapping log watch loops.
 - `await conn.close()`: for cleaning up the connection (kills TCP conn and ping loop)