"""Tiny Tapeout host and peer. All observations are made outside the DUT."""

from cocotb.triggers import Timer


class Pins:
    def __init__(self, dut):
        self.dut = dut
        self.inputs = 0x02  # Idle RX; host strobe and mode low.
        self.peer_mask = 0x0B

    async def reset(self):
        self.inputs = 0x02
        self.peer_mask = 0x0B
        self.dut.ui_in.value = 0
        self.dut.ena.value = 1
        self.dut.rst_n.value = 0
        await self.tick(2)
        self.dut.rst_n.value = 1
        await self.tick()
        assert (self.uo, self.out, self.oe) == (1, 0, 0xF4)

    async def tick(self, count=1):
        for _ in range(count):
            self.dut.clk.value = 0
            self.dut.uio_in.value = self.inputs
            self.dut.peer_oe.value = self.peer_mask
            await Timer(10, unit="ns")
            self.dut.clk.value = 1
            await Timer(10, unit="ns")
            assert self.oe & self.peer_mask == 0, "DUT and peer both enabled a pad"

    def host(self, data, mode, strobe):
        self.dut.ui_in.value = data
        self.inputs = (self.inputs & ~0x09) | (mode << 3) | strobe

    async def write(self, data, mode=1):
        self.host(data, mode, 0)
        await self.tick()
        self.host(data, mode, 1)
        await self.tick()

    async def enter(self):
        await self.write(0)
        assert self.oe == 0xF4
        await self.write(0x83)
        assert self.oe == 0x04

    async def load(self, program):
        await self.write(1)  # CLEAR
        for byte in program:
            await self.write(byte, mode=0)

    @property
    def uo(self):
        return int(self.dut.uo_out.value)

    @property
    def out(self):
        return int(self.dut.uio_out.value)

    @property
    def oe(self):
        return int(self.dut.uio_oe.value)

    @property
    def rx_byte(self):
        return (self.uo & 0xF0) | (self.out >> 4)

    @property
    def running(self):
        return bool(self.out & 4)
