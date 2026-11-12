"""EEPROM/NVM-Modell für avrsim (ATxmega128A4U: 2 KB, Seiten zu 32 Byte, eingeblendet ab 0x1000)."""
from avrsim import AVR


class EEAVR(AVR):
    def __init__(self, flash, ee=None):
        super().__init__(flash)
        self.ee = bytearray(ee) if ee is not None else bytearray(b'\xff' * 2048)
        self.buf = {}
        self.busy = 0
        self.pagewrites = {}
        self.errors = []

    def rd(self, a):
        if a == 0x1CF:
            st = (0x80 if self.busy else 0) | (0x02 if self.buf else 0)
            if self.busy: self.busy -= 1
            return st
        if 0x1000 <= a < 0x1800:
            if not self.mem[0x1CC] & 0x08: self.errors.append('EEPROM gelesen ohne EEMAPEN')
            if self.busy: self.errors.append('EEPROM gelesen während NVM busy')
            return self.ee[a - 0x1000]
        return super().rd(a)

    def wr(self, a, v):
        v &= 0xFF
        if a == 0x1C4 and self.mem[0x1CA] == 0x33:
            if self.mem[0x1CC] & 0x08: self.errors.append('Puffer geladen bei EEMAPEN')
            adr = self.mem[0x1C0] | self.mem[0x1C1] << 8
            self.buf[adr & 31] = v
        if a == 0x1CB and v & 1:
            if self.mem[0x34] != 0xD8: self.errors.append('CMDEX ohne CCP')
            self.mem[0x34] = 0
            cmd = self.mem[0x1CA]
            if self.busy: self.errors.append('Befehl während busy')
            if cmd == 0x35:
                pg = (self.mem[0x1C0] | self.mem[0x1C1] << 8) & 0x7E0
                for i, b in self.buf.items(): self.ee[pg + i] = b
                self.pagewrites[pg] = self.pagewrites.get(pg, 0) + 1
                self.buf = {}
                self.busy = 4
            elif cmd == 0x36:
                self.buf = {}
                self.busy = 1
            else:
                self.errors.append('unbekannter NVM-Befehl 0x%02X' % cmd)
            return
        super().wr(a, v)
