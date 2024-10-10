from umodbus.exceptions import ModbusError


class ModbusCommunicationFailureError(ModbusError):
    """Generic modbus communication error."""


class ModbusConcurrencyError(ModbusError):
    """Too many concurrent requests"""


class ModbusNotConnectedError(ModbusCommunicationFailureError):
    """Modbus not connected error."""
