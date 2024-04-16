import struct
from typing import Any, TypeVar

from umodbus.functions import (
    READ_COILS,
    READ_DISCRETE_INPUTS,
    READ_HOLDING_REGISTERS,
    READ_INPUT_REGISTERS,
    WRITE_MULTIPLE_COILS,
    WRITE_MULTIPLE_REGISTERS,
    WRITE_SINGLE_COIL,
    WRITE_SINGLE_REGISTER,
    ModbusFunction,
)
from umodbus.functions import ReadCoils as ReadCoilsUntyped
from umodbus.functions import ReadDiscreteInputs, ReadHoldingRegisters
from umodbus.functions import ReadInputRegisters as ReadInputRegistersUntyped
from umodbus.functions import (
    WriteMultipleCoils,
    WriteMultipleRegisters,
    WriteSingleCoil,
    WriteSingleRegister,
    getfullargspec,
    pdu_to_function_code_or_raise_error,
)

ModbusFunctionT = TypeVar("ModbusFunctionT", bound=ModbusFunction)


class ReadCoils(ReadCoilsUntyped):  # type: ignore
    @property
    def return_value(self) -> tuple[bool, ...]:
        return tuple(bool(v) for v in self.data[: self.quantity])

    def __repr__(self) -> str:
        return f"ReadInputRegisters({self.starting_address=}, {self.return_value=})"


class ReadInputRegisters(ReadInputRegistersUntyped):  # type: ignore
    def __init__(self, struct_dtype: str = "") -> None:
        self.struct_dtype = struct_dtype
        super().__init__()

    @property
    def return_value(self) -> Any:
        return struct.unpack(
            self.struct_dtype, struct.pack("<" + "H" * len(self.data), *self.data)
        )[0]

    def __repr__(self) -> str:
        return f"ReadInputRegisters<{self.struct_dtype}>({self.starting_address=}, {self.return_value=})"


function_code_to_function_map = {
    READ_COILS: ReadCoils,
    READ_DISCRETE_INPUTS: ReadDiscreteInputs,
    READ_HOLDING_REGISTERS: ReadHoldingRegisters,
    READ_INPUT_REGISTERS: ReadInputRegisters,
    WRITE_SINGLE_COIL: WriteSingleCoil,
    WRITE_SINGLE_REGISTER: WriteSingleRegister,
    WRITE_MULTIPLE_COILS: WriteMultipleCoils,
    WRITE_MULTIPLE_REGISTERS: WriteMultipleRegisters,
}


def create_function_from_response_pdu(
    resp_pdu: bytes, req: ModbusFunctionT
) -> ModbusFunctionT:
    """Parse response PDU and return instance of :class:`ModbusFunction` or
    raise error.

    :param resp_pdu: PDU of response.
    :param  req_pdu: Request PDU, some functions require more info than in
        response PDU in order to create instance. Default is None.
    :return: Number or list with response data.
    """
    function_code = pdu_to_function_code_or_raise_error(resp_pdu)
    function = function_code_to_function_map[function_code]

    if "req_pdu" in getfullargspec(function.create_from_response_pdu).args:
        return_msg = function.create_from_response_pdu(resp_pdu, req.request_pdu)
    else:
        return_msg = function.create_from_response_pdu(resp_pdu)

    if isinstance(req, ReadInputRegisters):
        return_msg.struct_dtype = req.struct_dtype

    return return_msg
