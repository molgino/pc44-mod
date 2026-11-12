"""Interrupts (TCE0 OVF/CCA) an zufälligen Befehlsgrenzen des Hauptprogramms einstreuen."""
import os, sys, io, contextlib, random, importlib
import tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
ORIG = os.environ.get('PC44_ORIG', os.path.join(os.path.dirname(HERE), 'PC44_V0101.syx'))
TMP = tempfile.gettempdir()
from pc44tool import decode
from eesim import EEAVR
from avrdis import dis
ver = '25'
seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
n = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
syx = os.path.join(TMP, '_pc44mod_irq.syx')
import build as B
with contextlib.redirect_stdout(io.StringIO()):
    LB = B.main(ORIG, syx)
_, img = decode(open(syx, 'rb').read())
random.seed(seed)
bad = []

class M(EEAVR):
    depth = 0
    budget = 0
    def run(self, pc, maxsteps):
        k = 0
        while True:
            if pc == 0x3FFFE: return
            if pc in self.stubs:
                self.stubs[pc](self); pc = self.pop_pc(); continue
            k += 1
            if k > maxsteps: raise RuntimeError('Endlosschleife 0x%X' % pc)
            if self.depth == 0 and self.budget > 0 and random.random() < 0.01:
                self.budget -= 1
                isr = random.choice(['tce0isr', 'tceccaisr'])
                fl = (self.C, self.Z, self.N, self.V, self.S); regs = list(self.r); sp = self.sp
                self.depth = 1; self.call(LB[isr]); self.depth = 0
                assert self.sp == sp
                self.C, self.Z, self.N, self.V, self.S = fl
                for i in range(32):
                    if i != 24 and self.r[i] != regs[i]: bad.append('ISR %s verändert r%d' % (isr, i))
                if self.mem[0x0a07] not in (0, 1): bad.append('INTCTRLB=0x%02X nach %s bei 0x%X (r1=0x%02X)' % (self.mem[0x0a07], isr, pc, self.r[1]))
                if self.mem[0x3DCC] not in (0, 1, 2): bad.append('EXT=0x%02X nach %s bei 0x%X' % (self.mem[0x3DCC], isr, pc))
                self.r[24] = regs[24]
            if pc not in self.cache: self.cache[pc] = dis(self.f, pc)
            ln, txt = self.cache[pc]
            pc = self.exec(pc, ln, txt)

m = M(img)
def clob(mm):
    for i in list(range(18, 28)) + [30, 31]: mm.r[i] = random.randrange(256)
def send3(mm): clob(mm); mm.r[24] = 1
m.stubs.update({0xA9A: send3, 0x3AC0: clob, 0x407E: clob, 0x2E08: lambda mm: None, 0x2F50: clob, 0x136E: clob,
                0x1362: clob, 0x3E6A: clob, 0x3BFC: clob, 0x24E8: clob, 0x1686: clob, 0x2FA6: clob, 0x3C30: clob, 0x1466: clob, 0x5EBA: clob, 0x11EC: clob, 0x11F4: clob})
m.call(LB['init']); m.mem[0x2218] = 8
for i in range(64): m.mem[B.RAM['V'] + i] = random.choice([0, 100])
m.mem[2] = 1
for step in range(n):
    m.mem[0x3DCC] = random.choice([0, 1]); m.mem[0x0a07] = random.choice([0, 1])
    for k in range(9): m.mem[0x230e + k] = 0
    bt = random.choice([0, 1, 3, 4]); m.mem[0x230e + bt] = 1 if bt else 0
    m.mem[0x3a56] = random.choice([random.randrange(64), 64, 66, 67]); v = random.randrange(128)
    m.mem[0x3aa7] = v; m.mem[0x3DF6] = v
    m.budget = 3
    if ver >= '23':
        m.r[10] = 0; m.r[24] = random.randrange(2); m.mem[0x2283] = random.choice([0, 0, 1]); m.mem[0x3a57] = random.choice([0, 0, 1]); m.call(LB['seqpoti'])
    else:
        m.call(LB['potisend'])
    m.r[1] = 0
    m.mem[0x3de0] = (m.mem[0x3de0] + 1) & 255; m.budget = 3; m.call(LB['hook']); m.r[1] = 0
    m.mem[0x3DD4] = 5; m.mem[0x3DD8] = random.choice([0, 1, 2, 4, 7, 14]); m.budget = 3; m.call(LB['rendhook'])
    for _ in range(3): m.rd(0x1CF)
print('Seed %d: %d Probleme' % (seed, len(bad)), sorted(set(bad))[:6])
