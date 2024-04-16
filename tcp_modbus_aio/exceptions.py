from umodbus.exceptions import ModbusError


class ModbusCommunicationFailureError(ModbusError):
    """Generic modbus communication error."""

    pass


class ModbusNotConnectedError(ModbusCommunicationFailureError):
    """Modbus not connected error."""

    pass
