#!/usr/bin/env python3
"""Kleiner AVR-Emulator für die Befehle, die der Sequencer-Code benutzt.
Firmware-Funktionen werden über 'stubs' (Adresse -> Python-Funktion) ersetzt.
"""
import re
from avrdis import dis


class AVR:
    def __init__(self, flash):
        self.f = bytes(flash) + b'\xff' * 0x40000
        self.r = [0] * 32
        self.mem = bytearray(0x4000)   # Datenraum bis 0x3FFF
        self.sp = 0x3FFF
        self.C = self.Z = self.N = self.V = self.S = 0
        self.stubs = {}
        self.gpior_max = 3   # wie am Gerät gemessen: nur GPIOR0..3 behalten Werte
        self.cache = {}
        self.steps = 0

    # --- Speicher
    # XMEGA: Register liegen nicht im Datenraum, 0x0000.. ist der I/O-Bereich
    def rd(self, a):
        if 4 <= a <= 15 and a > self.gpior_max: return 0
        return self.mem[a]

    def wr(self, a, v):
        v &= 0xFF
        if 4 <= a <= 15 and a > self.gpior_max: return
        self.mem[a] = v

    def push(self, v):
        self.mem[self.sp] = v & 0xFF; self.sp -= 1

    def pop(self):
        self.sp += 1; return self.mem[self.sp]

    def push_pc(self, pc):  # 3 Byte Rücksprungadresse (Wortadresse)
        w = pc // 2
        self.push(w); self.push(w >> 8); self.push(w >> 16)

    def pop_pc(self):
        h = self.pop(); m = self.pop(); l = self.pop()
        return ((h << 16) | (m << 8) | l) * 2

    def X(self): return self.r[26] | self.r[27] << 8
    def Zr(self): return self.r[30] | self.r[31] << 8
    def setX(self, v): self.r[26] = v & 0xFF; self.r[27] = (v >> 8) & 0xFF
    def setZ(self, v): self.r[30] = v & 0xFF; self.r[31] = (v >> 8) & 0xFF

    def flags_logic(self, res):
        self.Z = int(res == 0); self.N = res >> 7 & 1; self.V = 0; self.S = self.N ^ self.V

    def flags_sub(self, a, b, c=0, keepz=False):
        res = (a - b - c) & 0xFF
        self.C = int(a < b + c)
        z = int(res == 0)
        self.Z = (z and self.Z) if keepz else z
        self.N = res >> 7 & 1
        self.V = int(((a ^ b) & (a ^ res) & 0x80) != 0)
        self.S = self.N ^ self.V
        return res

    def flags_add(self, a, b, c=0):
        t = a + b + c; res = t & 0xFF
        self.C = int(t > 0xFF); self.Z = int(res == 0); self.N = res >> 7 & 1
        self.V = int((~(a ^ b) & (a ^ res) & 0x80) != 0); self.S = self.N ^ self.V
        return res

    # --- Ausführung
    def call(self, addr, maxsteps=200000):
        """Ruft eine Funktion auf und läuft bis zu deren ret."""
        self.push_pc(0x3FFFE)
        self.run(addr, maxsteps)

    def run(self, pc, maxsteps):
        n = 0
        while True:
            if pc == 0x3FFFE: return
            if pc in self.stubs:
                self.stubs[pc](self)
                pc = self.pop_pc()
                continue
            n += 1
            if n > maxsteps: raise RuntimeError('Endlosschleife bei 0x%X' % pc)
            if pc not in self.cache: self.cache[pc] = dis(self.f, pc)
            ln, txt = self.cache[pc]
            pc = self.exec(pc, ln, txt)

    def exec(self, pc, ln, t):
        op, _, args = t.partition(' ')
        a = [x.strip() for x in args.split(',')] if args else []
        nxt = pc + ln
        R = lambda s: int(s[1:])
        I = lambda s: int(s, 0)
        r = self.r
        if op == 'ldi': r[R(a[0])] = I(a[1])
        elif op == 'ser': r[R(a[0])] = 0xFF
        elif op == 'lds': r[R(a[0])] = self.rd(I(a[1]))
        elif op == 'sts': self.wr(I(a[0]), r[R(a[1])])
        elif op == 'in':
            A = I(a[1])
            if A == 0x3D: r[R(a[0])] = self.sp & 0xFF
            elif A == 0x3E: r[R(a[0])] = self.sp >> 8
            elif 4 <= A <= 15 and A > self.gpior_max: r[R(a[0])] = 0
            else: r[R(a[0])] = self.mem[A]
        elif op == 'out':
            A = I(a[0]); v = r[R(a[1])]
            if A == 0x3D: self.sp = (self.sp & 0xFF00) | v
            elif A == 0x3E: self.sp = (self.sp & 0x00FF) | v << 8
            elif 4 <= A <= 15 and A > self.gpior_max: pass
            else: self.mem[A] = v
        elif op == 'push': self.push(r[R(a[0])])
        elif op == 'pop': r[R(a[0])] = self.pop()
        elif op == 'mov': r[R(a[0])] = r[R(a[1])]
        elif op == 'movw':
            d, s2 = R(a[0]), R(a[1]); r[d] = r[s2]; r[d + 1] = r[s2 + 1]
        elif op == 'ldi' and False: pass
        elif op == 'clr': r[R(a[0])] = 0; self.flags_logic(0)
        elif op in ('and', 'eor', 'or'):
            d, s = R(a[0]), R(a[1])
            v = {'and': r[d] & r[s], 'eor': r[d] ^ r[s], 'or': r[d] | r[s]}[op]
            r[d] = v; self.flags_logic(v)
        elif op == 'andi': d = R(a[0]); r[d] &= I(a[1]); self.flags_logic(r[d])
        elif op == 'add': d = R(a[0]); r[d] = self.flags_add(r[d], r[R(a[1])])
        elif op == 'adc': d = R(a[0]); r[d] = self.flags_add(r[d], r[R(a[1])], self.C)
        elif op == 'sub': d = R(a[0]); r[d] = self.flags_sub(r[d], r[R(a[1])])
        elif op == 'subi': d = R(a[0]); r[d] = self.flags_sub(r[d], I(a[1]))
        elif op == 'sbci': d = R(a[0]); r[d] = self.flags_sub(r[d], I(a[1]), self.C, True)
        elif op == 'cp': self.flags_sub(r[R(a[0])], r[R(a[1])])
        elif op == 'cpc': self.flags_sub(r[R(a[0])], r[R(a[1])], self.C, True)
        elif op == 'cpi': self.flags_sub(r[R(a[0])], I(a[1]))
        elif op == 'inc':
            d = R(a[0]); r[d] = (r[d] + 1) & 0xFF
            self.Z = int(r[d] == 0); self.N = r[d] >> 7; self.V = int(r[d] == 0x80); self.S = self.N ^ self.V
        elif op == 'dec':
            d = R(a[0]); r[d] = (r[d] - 1) & 0xFF
            self.Z = int(r[d] == 0); self.N = r[d] >> 7; self.V = int(r[d] == 0x7F); self.S = self.N ^ self.V
        elif op == 'swap': d = R(a[0]); r[d] = ((r[d] << 4) | (r[d] >> 4)) & 0xFF
        elif op == 'lsr':
            d = R(a[0]); self.C = r[d] & 1; r[d] >>= 1; self.Z = int(r[d] == 0); self.N = 0
        elif op == 'ror':
            d = R(a[0]); c = r[d] & 1; r[d] = (r[d] >> 1) | (self.C << 7); self.C = c
            self.Z = int(r[d] == 0); self.N = r[d] >> 7
        elif op == 'mul':
            p = r[R(a[0])] * r[R(a[1])]; r[0] = p & 0xFF; r[1] = p >> 8
            self.C = p >> 15 & 1; self.Z = int(p == 0)
        elif op == 'ld':
            d = R(a[0]); m = a[1]
            if m == 'x': r[d] = self.rd(self.X())
            elif m == 'x+': r[d] = self.rd(self.X()); self.setX(self.X() + 1)
            elif m == 'z+': r[d] = self.rd(self.Zr()); self.setZ(self.Zr() + 1)
            elif m == 'z': r[d] = self.rd(self.Zr())
            elif m == 'y': r[d] = self.rd(r[28] | r[29] << 8)
            elif m == 'y+':
                p = r[28] | r[29] << 8; r[d] = self.rd(p); p += 1; r[28] = p & 0xFF; r[29] = p >> 8 & 0xFF
            else: raise NotImplementedError(t)
        elif op == 'st':
            m, s = a[0], r[R(a[1])]
            if m == 'x': self.wr(self.X(), s)
            elif m == 'x+': self.wr(self.X(), s); self.setX(self.X() + 1)
            elif m in ('z', 'y'):
                p = self.Zr() if m == 'z' else (r[28] | r[29] << 8); self.wr(p, s)
            elif m == 'z+': self.wr(self.Zr(), s); self.setZ(self.Zr() + 1)
            elif m == 'y+':
                p = r[28] | r[29] << 8
                self.wr(p, s)
                p += 1
                r[28], r[29] = p & 0xFF, p >> 8
            else: raise NotImplementedError(t)
        elif op == 'lpm':
            d = R(a[0])
            if self.mem[0x01CA] != 0: r[d] = 0xFF          # wie auf der Hardware
            else: r[d] = self.f[self.Zr()]
            if a[1] == 'z+': self.setZ(self.Zr() + 1)
        elif op == 'sbrs':
            if r[R(a[0])] >> I(a[1]) & 1: nxt += dis(self.f, nxt)[0]
        elif op == 'sbrc':
            if not r[R(a[0])] >> I(a[1]) & 1: nxt += dis(self.f, nxt)[0]
        elif op in ('rjmp', 'jmp'): return I(a[0])
        elif op in ('rcall', 'call'): self.push_pc(nxt); return I(a[0])
        elif op in ('ret', 'reti'): return self.pop_pc()
        elif op in ('breq', 'brne', 'brcs', 'brcc', 'brlt', 'brge', 'brmi', 'brpl', 'brvs', 'brvc', 'brhs', 'brhc', 'brie', 'brid'):
            if op in ('brvs', 'brvc', 'brhs', 'brhc', 'brie', 'brid'):
                c = {'brvs': self.V, 'brvc': not self.V}.get(op, 0)
                if c: return I(a[0])
                return nxt
            c = {'breq': self.Z, 'brne': not self.Z, 'brcs': self.C, 'brcc': not self.C,
                 'brlt': self.S, 'brge': not self.S, 'brmi': self.N, 'brpl': not self.N}[op]
            if c: return I(a[0])
        elif op == 'adiw':
            d = R(a[0]); v = (r[d] | r[d + 1] << 8) + I(a[1]); self.C = int(v > 0xFFFF); v &= 0xFFFF
            r[d] = v & 0xFF; r[d + 1] = v >> 8; self.Z = int(v == 0); self.N = v >> 15
        elif op == 'sbiw':
            d = R(a[0]); o = r[d] | r[d + 1] << 8; v = o - I(a[1]); self.C = int(v < 0); v &= 0xFFFF
            r[d] = v & 0xFF; r[d + 1] = v >> 8; self.Z = int(v == 0); self.N = v >> 15; self.S = self.N
        elif op == 'cpse':
            if r[R(a[0])] == r[R(a[1])]: nxt += dis(self.f, nxt)[0]
        elif op == 'sbc': d = R(a[0]); r[d] = self.flags_sub(r[d], r[R(a[1])], self.C, True)
        elif op == 'com': d = R(a[0]); r[d] ^= 0xFF; self.flags_logic(r[d]); self.C = 1
        elif op == 'neg': d = R(a[0]); r[d] = self.flags_sub(0, r[d])
        elif op == 'asr':
            d = R(a[0]); self.C = r[d] & 1; r[d] = (r[d] >> 1) | (r[d] & 0x80); self.Z = int(r[d] == 0); self.N = r[d] >> 7
        elif op == 'or': d = R(a[0]); r[d] |= r[R(a[1])]; self.flags_logic(r[d])
        elif op == 'ori': d = R(a[0]); r[d] |= I(a[1]); self.flags_logic(r[d])
        elif op == 'sbci' and False: pass
        elif op == 'bst': self.T = r[R(a[0])] >> I(a[1]) & 1
        elif op == 'bld':
            d = R(a[0]); b = I(a[1]); r[d] = (r[d] & ~(1 << b) & 0xFF) | (getattr(self, 'T', 0) << b)
        elif op in ('set', 'clt', 'sei', 'cli', 'sec', 'clc'):
            if op == 'set': self.T = 1
            if op == 'clt': self.T = 0
            if op == 'sec': self.C = 1
            if op == 'clc': self.C = 0
        elif op in ('ldd', 'std'):
            if op == 'ldd': d, m2 = R(a[0]), a[1]
            else: m2, d = a[0], R(a[1])
            base, _, q = m2.partition('+')
            p = (r[28] | r[29] << 8) if base == 'y' else (r[30] | r[31] << 8)
            p += int(q or 0)
            if op == 'ldd': r[d] = self.rd(p)
            else: self.wr(p, r[d])
        elif op == 'elpm':
            d = R(a[0]); r[d] = self.f[self.Zr() | self.mem[0x3B] << 16]
            if a[1].endswith('+'): self.setZ(self.Zr() + 1)
        elif op in ('brts', 'brtc'):
            c = getattr(self, 'T', 0) if op == 'brts' else not getattr(self, 'T', 0)
            if c: return I(a[0])
        elif op == 'nop': pass
        else: raise NotImplementedError('Befehl %s bei 0x%X' % (t, pc))
        return nxt
