#!/usr/bin/env python3
"""Funktionstest PC44_seq25.syx im Emulator (GPIOR4..15 wie am Gerät ohne Speicher)."""
import contextlib
import io
import os
import random
import sys

import os
import sys
import tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
ORIG = os.environ.get('PC44_ORIG', os.path.join(os.path.dirname(HERE), 'PC44_V0101.syx'))
TMP = tempfile.gettempdir()
from pc44tool import decode   # noqa: E402
from eesim import EEAVR as AVR  # noqa: E402
from avrdis import dis        # noqa: E402
import build as B       # noqa: E402

SYX = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TMP, '_pc44mod_test.syx')
with contextlib.redirect_stdout(io.StringIO()):
    LB = B.main(ORIG, os.path.join(TMP, '_pc44mod_test.syx'))
_, img = decode(open(SYX, 'rb').read())
m = AVR(img)
N, V, P, R, L = (B.RAM[k] for k in ('N', 'V', 'P', 'R', 'L'))
SPD, CHN, DIR, MUTE, MREQ, LOOP, POS = 0x3E60, 0x3E64, 0x3E68, 0x3E80, 0x3E84, 0x3E7C, 0x3DEE
TLEN, OCT, EDTRK, EDPAR = 0x3DF2, 0x3DE9, 0x3E8C, 0x3E8D
DMODE, DVAL, RAWVAL = 0x3DD8, 0x3DD9, 0x3DF6
sent, flow = [], []
ok = True


def clob(m):
    for i in list(range(18, 28)) + [30, 31]: m.r[i] = random.randrange(256)


def send3(m): sent.append((m.r[24], m.r[22], m.r[20])); clob(m); m.r[24] = 1


SEG = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f]
m.stubs.update({0xA9A: send3, 0x3AC0: clob, 0x407E: clob,
                0x2E08: lambda mm: mm.r.__setitem__(24, SEG[mm.r[24]] if mm.r[24] < 10 else 0),
                0x2F50: lambda mm: [mm.mem.__setitem__(0x2fe6 + mm.r[22] + i, SEG[int(c)]) for i, c in enumerate('%03d' % mm.r[24])],
                0x136E: lambda m: flow.append('bearbeitet'), 0x1466: lambda m: flow.append('bearbeitet'),
                0x11EC: lambda m: flow.append('original'), 0x5EBA: lambda m: flow.append('lock-weiter'), 0x11F4: lambda m: flow.append('setup'), 0x1362: lambda m: flow.append('original'),
                0x3E6A: lambda m: flow.append('anzeige'), 0x3BFC: lambda m: flow.append('led'),
                0x24E8: lambda m: flow.append('fw-edit1'), 0x1686: lambda m: flow.append('fw-edit2'),
                0x2FA6: lambda m: flow.append('fw-anzeige')})


def check(c, msg):
    global ok
    print(('  OK     ' if c else '  FEHLER ') + msg); ok &= bool(c)


def call(n):
    m.call(LB[n])
    assert m.r[1] == 0 and m.sp == 0x3FFF, 'Register/Stack nach ' + n


def tick(n):
    ev = []
    for t in range(n):
        m.call(LB['tce0isr']); call('hook')
        ev += [(t,) + s for s in sent]; sent.clear()
    return ev


def btns(*b):
    for k in range(9): m.mem[0x230e + k] = 0
    for k in b: m.mem[0x230e + k] = 1


SNAP = [0]
def poti(btn, idx, val, shift=0, setup=0, lock=0):
    btns(*([btn] if btn else []))
    m.mem[0x3a56] = idx; m.mem[0x3aa7] = val; m.mem[RAWVAL] = val; m.mem[0x2283] = shift; m.mem[0x3a57] = lock
    flow.clear()
    if m.mem[0x220e]:
        call('potisend')
    else:
        m.r[10] = setup; m.r[24] = SNAP[0]; m.r[25] = 0x55; call('seqpoti')
    btns(); m.mem[0x2283] = 0; m.mem[0x3a57] = 0; return flow[-1]


def start():
    m.mem[2] = 0; m.mem[0x2216] = 1; m.mem[0x2315] = 1; call('hook'); m.mem[0x2216] = 0; m.mem[0x2315] = 0
    m.mem[0x3DE0] = m.mem[0x3DE1]; sent.clear()


def ons(ev, st=0x90):
    return [e for e in ev if e[1] & 0xF0 == st]


def clear_steps():
    for i in range(64): m.mem[V + i] = 0; m.mem[P + i] = 9; m.mem[R + i] = 1; m.mem[L + i] = 2; m.mem[N + i] = B.TUNE_DEFAULT


seg = {0x3f: '0', 0x06: '1', 0x5b: '2', 0x4f: '3', 0x66: '4', 0x6d: '5', 0x7d: '6', 0x07: '7', 0x7f: '8', 0x6f: '9',
       0x78: 't', 0x54: 'n', 0x1c: 'u', 0x73: 'P', 0x50: 'r', 0x38: 'L', 0x5c: 'o', 0x71: 'F', 0: ' ', 0x39: 'C',
       0x76: 'H', 0x74: 'h', 0x5e: 'd', 0x77: 'A', 0x79: 'E', 0x40: '-', 0x58: 'c', 0x10: 'i', 0x3d: 'G'}


def text():
    return ''.join(seg.get(x & 0x7f, '?') + ('.' if x & 0x80 else '') for x in m.mem[0x2fe6:0x2fea])


print('1) Grundzustand und Abspielen')
call('init'); m.mem[0x2218] = 8
check(list(m.mem[SPD:SPD + 4]) == [4] * 4 and list(m.mem[CHN:CHN + 4]) == [0, 1, 2, 3], 'Speed x1, Kanäle 1-4')
check(set(m.mem[P:P + 64]) == {9}, 'Wahrscheinlichkeit 100 %')
start()
ev = tick(12 * 16)
check([e[0] for e in ons(ev)] == [0, 48, 96, 144] and all(e[2] == 60 for e in ons(ev)), 'Spur 1 spielt C4 auf Step 1,5,9,13')
check(sum(1 for e in ev if e[1] == 0xF8) == 96, 'Clock 24 ppqn')

print('2) Speed pro Spur')
clear_steps()
for s in range(16): m.mem[V + 16 + s] = 100       # Spur 2 alle Steps
for sp, ticks in [(6, 6), (2, 24), (0, 96), (3, 16), (5, 8)]:
    m.mem[SPD + 1] = sp; start(); ev = tick(12 * 16)
    t2 = [e[0] for e in ons(ev, 0x90) if e[1] == 0x91]
    d = sorted(set(b - a for a, b in zip(t2, t2[1:])))
    check(d == [ticks], 'Spur 2 Speed %s: Abstand %s Ticks (erwartet %d)' % (B.SPEEDS[sp][:2], d, ticks))
m.mem[SPD + 1] = 4

print('3) Richtung')
clear_steps()
for s in range(4): m.mem[V + s] = 100; m.mem[N + s] = [0, 40, 80, 127][s]
m.mem[TLEN] = 4
def seqpos(d, n=10):
    m.mem[DIR] = d; start(); ev = tick(12 * n)
    return [[0, 40, 80, 127].index(next(v for v in range(128) if m.mem[N] == v) if False else 0) for _ in []] or \
           [e[2] for e in ons(ev) if e[1] == 0x90]
notes = [B.tunetable()[v] for v in (0, 40, 80, 127)]
idx = lambda seq: [notes.index(x) for x in seq]
check(idx(seqpos(0, 8)) == [0, 1, 2, 3, 0, 1, 2, 3], 'vorwärts 1234 1234')
check(idx(seqpos(1, 8)) == [3, 2, 1, 0, 3, 2, 1, 0], 'rückwärts 4321 4321')
check(idx(seqpos(2, 10)) == [0, 1, 2, 3, 2, 1, 0, 1, 2, 3], 'Pingpong 1234321234')
r = idx(seqpos(3, 40))
check(len(r) == 40 and set(r) <= {0, 1, 2, 3} and len(set(r)) >= 3, 'zufällig innerhalb der Länge (%s...)' % r[:8])
m.mem[DIR] = 0; m.mem[TLEN] = 16

print('4) Bedingungen und Prozent')
clear_steps(); m.mem[V] = 100
for pidx, exp in [(10, '1:2'), (11, '2:2'), (13, '2:3'), (44, '8:8')]:
    a, b = B.CONDS[pidx - 10]
    m.mem[P] = pidx; start(); ev = tick(12 * 16 * 8)
    loops = [e[0] // 192 for e in ons(ev)]
    want = [k for k in range(8) if k % b == a - 1]
    check(loops == want, 'Bedingung %s: spielt in Durchlauf %s' % (exp, [k + 1 for k in loops]))
m.mem[P] = 4; start(); ev = tick(12 * 16 * 100)
n = len(ons(ev))
check(35 <= n <= 65, 'Wahrscheinlichkeit 50 %%: %d von 100' % n)
check(poti(3, 0, 0) == 'bearbeitet' and m.mem[P] == 0, 'Taste 3 Poti links = 10 %')
check(poti(3, 0, 127) == 'bearbeitet' and m.mem[P] == 44, 'Taste 3 Poti rechts = 8:8')
m.mem[DMODE] = 4; m.mem[DVAL] = 6; m.mem[0x3DD4] = 5; flow.clear(); call('rendhook'); t1 = text()
m.mem[DVAL] = 13; call('rendhook'); t2 = text()
check(t1 == 'P070' and t2 == 'c2-3', 'Anzeige %s / %s' % (t1, t2))
m.mem[P] = 9

print('5) Mute quantisiert')
clear_steps(); m.mem[V] = 100; m.mem[V + 16] = 100; m.mem[TLEN] = 4
start(); tick(12 * 2)
m.mem[0x3E10 + 3] = 60; poti(0, 3, 70, shift=1)      # Shift + nach rechts: Spur 1 stumm (läuft gerade)
check(m.mem[MREQ] == 1 and m.mem[MUTE] == 0, 'Mute-Wunsch gespeichert, noch nicht aktiv')
m.mem[DMODE] = 12; m.mem[DVAL] = 0; m.mem[0x3DD4] = 5; call('rendhook')
check(text().rstrip() == 'oFF.', 'Anzeige wartet: %s' % text())
ev = tick(12 * 16)
t1 = [e[0] for e in ons(ev) if e[1] == 0x90]
check(t1 == [], 'Spur 1 verstummt ab dem nächsten Pattern-Durchlauf')
poti(0, 3, 50, shift=1); ev = tick(12 * 8)
check([e[0] for e in ons(ev) if e[1] == 0x90] == [24, 72], 'Unmute ebenfalls erst am Pattern-Ende (Step %s)' % [e[0] for e in ons(ev) if e[1] == 0x90])
m.mem[TLEN] = 16

print('6) Edit-Seite')
m.mem[0x220e] = 1; m.mem[0x3bf3] = 0
call('isedit'); check(m.r[25] == 1, 'Edit-Seite im SEq-Modus erkannt')
check(poti(0, 40, 50) == 'bearbeitet' and m.mem[EDTRK] == 2, 'Poti Reihe 5 wählt Spur 3, sendet kein MIDI')
def edbtn(k):
    m.mem[0x220f + k] = 1; m.mem[0x230e + k] = 1; flow.clear(); call('seqedit'); m.mem[0x230e + k] = 0
def enc(up, n=1):
    for _ in range(n): m.mem[0x3bf8] = 1; m.mem[0x213e] = 1 if up else 0; call('seqedit')
def show():
    flow.clear(); call('edshow'); return text()
edbtn(4); enc(False, 2)
check(m.mem[EDPAR] == 4 and m.mem[SPD + 2] == 2, 'Taste 4 + Encoder: Speed Spur 3 = 1/2')
check(show() == ' 1-2', 'Anzeige Speed %r' % show())
edbtn(5); enc(True, 9)
check(m.mem[CHN + 2] == 11 and show() == 'Ch12', 'Kanal Spur 3 = 12 (%s)' % show())
edbtn(6); enc(True, 2); check(m.mem[DIR + 2] == 2 and show() == 'PinG', 'Richtung Pingpong (%s)' % show())
edbtn(2); enc(False, 4); check(m.mem[TLEN + 2] == 12 and show() == 'LP12', 'Länge 12 (%s)' % show())
edbtn(3); enc(True, 1); check(m.mem[OCT + 2] == 4 and show() == 'oc 1', 'Oktave +1 (%s)' % show())
edbtn(1); enc(True, 1); check(m.mem[EDTRK] == 3 and show() == 'tr 4', 'Spur 4 gewählt (%s)' % show())
enc(True, 3); check(m.mem[EDTRK] == 3, 'Spurwahl begrenzt auf 4')
call('ledhook'); check(list(m.mem[0x3bf9:0x3c01]) == [3, 0, 0, 0, 0, 0, 0, 0], 'LED zeigt gewählten Parameter (Taste 1)')
m.mem[2] = 0; edbtn(8); check(m.mem[2] == 1, 'Taste 8 startet auf der Edit-Seite')
edbtn(8); check(m.mem[2] == 0, 'Taste 8 nochmals: Stopp')
flow.clear(); m.r[24] = 0; m.mem[0x2218] = 5; call('seqedit'); call('seqedit2')
check(flow == ['fw-edit1', 'fw-edit2'], 'ohne SEq: Original-Edit der Firmware')
m.mem[0x2218] = 8; m.mem[0x220e] = 0

print('7) Kanal beim Abspielen')
clear_steps(); m.mem[V + 32] = 90; m.mem[SPD + 2] = 4; m.mem[DIR + 2] = 0
start(); ev = tick(12 * 16)
on3 = [e for e in ons(ev) if e[1] == 0x9B]
off3 = [e for e in ev if e[1] == 0x8B]
check(on3 and off3, 'Spur 3 sendet Note-On/Off auf Kanal 12')
m.mem[CHN + 2] = 2


print('8) Spur löschen (Taste 6)')
for i in range(16, 32): m.mem[V + i] = 99; m.mem[N + i] = 5; m.mem[P + i] = 3; m.mem[R + i] = 3; m.mem[L + i] = 9
m.mem[V] = 77
check(poti(6, 20, 60) == 'bearbeitet' and m.mem[V + 16] == 99, 'Poti halb: noch nichts gelöscht')
m.mem[0x3DD4] = 5; call('rendhook'); check(text() == 'CL 2', 'Anzeige %r' % text())
poti(6, 20, 127)
check(set(m.mem[V + 16:V + 32]) == {0} and set(m.mem[N + 16:N + 32]) == {B.TUNE_DEFAULT}
      and set(m.mem[P + 16:P + 32]) == {9} and set(m.mem[R + 16:R + 32]) == {1}
      and set(m.mem[L + 16:L + 32]) == {B.LEN_DEFAULT}, 'Spur 2 gelöscht')
check(m.mem[V] == 77 and m.mem[V + 32] == 90, 'andere Spuren unverändert')
call('rendhook'); check(text() == 'CLr2', 'Anzeige %r' % text())

print('9) Speichern im EEPROM')
check(m.errors == [], 'NVM-Zugriffe korrekt %s' % m.errors[:3])
m.mem[2] = 0
for i in range(64): m.mem[V + i] = (i * 7) % 128; m.mem[N + i] = (i * 3) % 128; m.mem[P + i] = i % 45; m.mem[R + i] = 1 + i % 4; m.mem[L + i] = i % 16
for t in range(4):
    m.mem[SPD + t] = t + 1; m.mem[CHN + t] = 15 - t; m.mem[DIR + t] = t; m.mem[TLEN + t] = 13 + t; m.mem[OCT + t] = t + 2; m.mem[MREQ + t] = t & 1
m.mem[0x3DE2] = 7; m.mem[0x3DE8] = 5; m.mem[0x3DED] = 4; m.mem[3] = 133
snap = {k: bytes(m.mem[a:a + n]) for k, (a, n) in dict(N=(N, 64), V=(V, 64), P=(P, 64), R=(R, 64), L=(L, 64),
        T=(0x3DE2, 12), TL=(TLEN, 4), S=(SPD, 12), MQ=(MREQ, 4), BPM=(3, 1)).items()}
m.pagewrites.clear(); tick(60)
check(m.pagewrites == {}, 'ohne Speichern keine EEPROM-Schreibvorgänge')
m.mem[V + 5] = 111
snap['V'] = bytes(m.mem[V:V + 64])
call('pattern_save'); tick(220)
check(bytes(m.ee[0x5e0:0x5e6]) == bytes((0x50, 26, 0, 255, 1, 254)), 'Kennung im EEPROM')
m.pagewrites.clear(); start(); tick(100); m.mem[2] = 0
check(m.pagewrites == {}, 'Abspielen ohne Änderungen schreibt nichts (Laufposition wird nicht gespeichert)')
check(m.errors == [], 'NVM-Zugriffe korrekt %s' % m.errors[:3])

print('10) Aus- und Einschalten')
ee = bytes(m.ee)
m2 = AVR(img, ee); m2.stubs.update(m.stubs)
m, keep = m2, m
call('init')
got = {k: bytes(m.mem[a:a + n]) for k, (a, n) in dict(N=(N, 64), V=(V, 64), P=(P, 64), R=(R, 64), L=(L, 64),
       T=(0x3DE2, 12), TL=(TLEN, 4), S=(SPD, 12), MQ=(MREQ, 4), BPM=(3, 1)).items()}
diff = [k for k in snap if snap[k][:1] != got[k][:1] or (k != 'T' and snap[k] != got[k])]
tmask = lambda b: bytes(b[i] for i in (0, 6, 7, 8, 9, 10, 11))   # Skala, Grundton, Oktaven, Shuffle
check(diff == [] and tmask(snap['T']) == tmask(got['T']), 'alles wiederhergestellt %s' % diff)
check(list(m.mem[MUTE:MUTE + 4]) == [0, 1, 0, 1], 'Mute aktiv wie gespeichert')
check(m.mem[0x0a26] | m.mem[0x0a27] << 8 == B.per(133), 'Timer auf gespeichertes Tempo 133')
check(list(m.mem[POS:POS + 4]) == [0xff] * 4, 'Laufposition beginnt neu')
m3 = AVR(img); m3.stubs.update(keep.stubs); m = m3; call('init')
check(m.mem[V] == 100 and m.mem[3] == 120 and m.mem[SPD] == 4, 'leeres EEPROM: Grundeinstellung')
bad = bytearray(ee)
bad[0x400:0x5e0] = bytes([0xee]) * 480
m4 = AVR(img, bad); m4.stubs.update(keep.stubs); m = m4; call('init')
check(set(m.mem[N:N + 64]) == {62} and set(m.mem[P:P + 64]) == {9} and set(m.mem[R:R + 64]) == {1} and m.mem[3] == 238
      and set(m.mem[SPD:SPD + 4]) == {4} and set(m.mem[TLEN:TLEN + 4]) == {16}, 'kaputte Werte -> Grundwerte')
check(list(m.mem[CHN:CHN + 4]) == [0, 1, 2, 3], 'kaputte Kanäle -> Kanal 1-4 wie beim Einschalten')

print('11) Firmware-eigenes EEPROM (Setups 0x010..0x11F) bleibt nutzbar')
m = m2
m.r[24], m.r[25], m.r[22], m.r[23] = 0x10, 0, 0x34, 0x12; m.call(0x6bfc)
for _ in range(10): m.rd(0x1CF)
m.r[24], m.r[25] = 0x10, 0; m.call(0x6bf4)
check((m.r[24], m.r[25]) == (0x34, 0x12) and m.ee[0x400:0x400 + B.EESIZE] == ee[0x400:0x400 + B.EESIZE],
      'Firmware schreibt/liest ihre Adressen, Pattern unberührt')
m.pagewrites.clear(); tick(400)
check(m.pagewrites == {} and m.errors == [], 'danach keine unnötigen Schreibvorgänge, keine NVM-Fehler %s' % m.errors[:2])


print('12) Gespeichertes Pattern aus seq20 bleibt beim Update erhalten')
import build_seq20 as B20
with contextlib.redirect_stdout(io.StringIO()):
    B20.main(ORIG, os.path.join(TMP, '_seq20_old.syx'))
_, img20 = decode(open(os.path.join(TMP, '_seq20_old.syx'), 'rb').read())
LB20 = __import__('build_seq20').main.__globals__  # nur für Pfad; Labels separat
with contextlib.redirect_stdout(io.StringIO()):
    LBo = B20.main(ORIG, os.path.join(TMP, '_seq20_old.syx'))
o = AVR(img20); o.stubs.update(keep.stubs); o.call(LBo['init']); o.mem[0x2218] = 8
for i in range(64): o.mem[V + i] = (i * 5) % 128
o.mem[SPD] = 2; o.mem[3] = 97
for _ in range(400): o.call(LBo['tce0isr']); o.call(LBo['hook'])
m = AVR(img, bytes(o.ee)); m.stubs.update(keep.stubs); call('init')
check(bytes(m.mem[V:V + 64]) == bytes(o.mem[V:V + 64]) and m.mem[SPD] == 2 and m.mem[3] == 97, 'Steps, Speed, Tempo übernommen')
check(list(m.mem[B.consts_MODE:B.consts_MODE + 4]) == [0] * 4 if hasattr(B, 'consts_MODE') else list(m.mem[0x3DC8:0x3DCC]) == [0] * 4,
      'neue Felder (Modus) auf Grundwert')
check(set(m.mem[0x3E90:0x3ED0]) == {0}, 'Akkordart auf Grundwert (Dreiklang)')

print('13) Chord-Modus')
MODE, CT, LNX = 0x3DC8, 0x3E90, 0x3E54
m = AVR(img); m.stubs.update(keep.stubs); call('init'); m.mem[0x2218] = 8
clear_steps()
m.mem[MODE] = 1; m.mem[0x3DE2] = 1           # Spur 1 Chord, Skala Dur
m.mem[V] = 100; m.mem[N] = B.TUNE_DEFAULT       # C4
m.mem[V + 4] = 100; m.mem[N + 4] = B.TUNE_DEFAULT; m.mem[CT + 4] = 3     # Step 5: Septakkord
m.mem[V + 8] = 100                                                          # Step 9: Note aus Skala (2. Stufe)
tt = B.tunetable(); v9 = next(v for v in range(128) if tt[128 + v] == 62); m.mem[N + 8] = v9   # D4
m.mem[V + 12] = 100; m.mem[N + 12] = B.TUNE_DEFAULT; m.mem[CT + 12] = 7  # Step 13: Power
start(); ev = tick(12 * 16)
chords = {}
for e in ons(ev):
    if e[1] == 0x90: chords.setdefault(e[0], []).append(e[2])
got = [sorted(chords.get(t, [])) for t in (0, 48, 96, 144)]
check(got[0] == [60, 64, 67], 'Dreiklang C-Dur: %s' % got[0])
check(got[1] == [60, 64, 67, 71], 'Septakkord in Dur (Cmaj7): %s' % got[1])
check(got[2] == [62, 65, 69], 'Stufe 2 in Dur ergibt d-Moll: %s' % got[2])
check(got[3] == [60, 67, 72], 'Power-Akkord: %s' % got[3])
offs = [e for e in ev if e[1] == 0x80]
check(sorted(e[2] for e in offs) == sorted(sum(got, [])), 'jede Akkordnote bekommt ein Note-Off')
m.mem[0x3DE2] = 0; m.mem[CT] = 0; start(); ev = tick(12)
check(sorted(e[2] for e in ons(ev) if e[1] == 0x90) == [60, 64, 67], 'chromatisch: Dur-Dreiklang in Halbtönen')
m.mem[0x3DE2] = 2; m.mem[0x3DE8] = 2; start(); ev = tick(12)
check(sorted(e[2] for e in ons(ev) if e[1] == 0x90) == [62, 65, 69], 'Moll mit Grundton D: d-Moll %s' % sorted(e[2] for e in ons(ev) if e[1] == 0x90))
m.mem[0x3DE8] = 0; m.mem[0x3DE2] = 1
m.mem[2] = 0; call('stopseq')
check(set(m.mem[LNX:LNX + 12]) == {0xff}, 'Stopp beendet alle Akkordnoten')
check(poti(4, 4, 127) == 'bearbeitet' and m.mem[CT + 4] == 7 and m.mem[R + 4] == 1, 'Taste 4 in Chord-Spur: Akkordart, Ratchet bleibt')
m.mem[0x3DD4] = 5; call('rendhook'); t1 = text()
poti(4, 4, 0); call('rendhook'); t2 = text()
check(t1 == '1-5 ' and t2 == 'tri ', 'Anzeige %r / %r' % (t1, t2))
check(poti(4, 20, 127) == 'bearbeitet' and m.mem[R + 20] == 4, 'Taste 4 in Note-Spur: weiterhin Ratchet')
m.mem[R] = 2; start(); ev = tick(12)
check(len([e for e in ons(ev) if e[1] == 0x90]) == 6, 'Ratchet 2 in Chord-Spur: Akkord 2x')
m.mem[R] = 1

print('14) Pad-Modus')
m.mem[R + 20] = 1
m.mem[MODE + 1] = 2; m.mem[V + 16] = 100; m.mem[N + 16] = B.TUNE_DEFAULT; m.mem[V + 20] = 100; m.mem[N + 20] = 64
m.mem[0x3DE2] = 5; m.mem[0x3DE8] = 7
start(); ev = tick(12 * 8)
pn = [e[2] for e in ons(ev) if e[1] == 0x91]
check(pn == [36, 38], 'Pad: Grundstellung = 36, chromatisch, ohne Skala/Grundton: %s' % pn)
poti(1, 16, 63); check(m.mem[0x3DD9] == 37, 'Taste 1 zeigt Pad-Note 37')
m.mem[0x3DE2] = 1; m.mem[0x3DE8] = 0

print('15) Edit-Seite: Modus')
m.mem[0x220e] = 1; m.mem[0x3bf3] = 0
poti(0, 40, 50); edbtn(7)
check(m.mem[EDPAR] == 7 and m.mem[EDTRK] == 2, 'Taste 7 wählt Modus, Spur 3')
check(show() == 'notE', 'Anzeige %r' % show())
enc(True); check(m.mem[MODE + 2] == 1 and show() == 'Chrd', 'Encoder: Chord')
enc(True); check(m.mem[MODE + 2] == 2 and show() == 'PAd ', 'Encoder: Pad')
enc(True); check(m.mem[MODE + 2] == 2, 'Ende bei Pad')
call('ledhook'); check(list(m.mem[0x3bf9:0x3c01]) == [0, 0, 0, 0, 0, 0, 3, 0], 'LED 7 leuchtet')
m.mem[MODE + 2] = 0; m.mem[0x220e] = 0

print('16) Externe Clock')
EXT, EXTCMD = 0x3DCC, 0x3DCE
clear_steps(); m.mem[V] = 100; m.mem[V + 1] = 100; m.mem[R + 1] = 3; m.mem[MODE] = 0
for k in range(4): m.mem[MODE + k] = 0
m.mem[2] = 0
def rx(b, port=0, cnt=None):
    if cnt is not None: m.mem[0x0a20] = cnt & 0xff; m.mem[0x0a21] = cnt >> 8
    m.mem[0x08a0 if port == 0 else 0x09a0] = b
    m.r[28] = 0; m.call(LB['rxc0' if port == 0 else 'rxd0'])
    assert m.r[28] == b
def hookrun():
    call('hook'); r = list(sent); sent.clear(); return r
PER120 = 10416
ext = []
rx(0xFA); out = hookrun()
check(m.mem[EXT] == 1 and m.mem[2] == 1, 'FA: Start, externe Clock aktiv')
check(not any(x[0] in (0xFA, 0xF8) for x in out), 'kein FA/F8 zurück an die MPC')
t = 0
for k in range(24 * 4):
    rx(0xF8, cnt=PER120); ext += [(t,) + x for x in hookrun()]; t += 1
    if m.mem[0x0a07]:
        check(m.mem[0x0a28] | m.mem[0x0a29] << 8 == (PER120 // 2 if k else 0) or k == 0, 'halber Abstand im Vergleichsregister') if k == 1 else None
        m.call(LB['tceccaisr']); ext += [(t,) + x for x in hookrun()]
    t += 1
on1 = [e[0] for e in ext if e[1] == 0x90]
on2 = [e[0] for e in ext if e[1] == 0x91]
check(on1 == [0, 12, 16, 20] * 1 + [] and len(on1) == 4, 'Step 1 auf Tick 0, Step 2 mit Ratchet 3 auf 12/16/20 (halbe Clocks): %s' % on1)
rx_ok = True
check(not any(e[1] in (0xF8, 0xFA, 0xFC) for e in ext), 'keine eigene Clock gesendet')
m.r[24] = 0; call('extbpm'); check(m.r[18] == 120, 'gemessenes Tempo %d' % m.r[18])
m.mem[DMODE] = 0; m.mem[0x3DD4] = 5; call('rendhook'); check(text() == 'E120', 'Anzeige %r' % text())
pos = m.mem[POS]
rx(0xF8, port=1, cnt=PER120); hookrun()
check(m.mem[0x3DE0] == m.mem[0x3DE1] and m.mem[POS] == pos, 'Clock vom zweiten Eingang wird ignoriert')
rx(0xFC); out = hookrun()
check(m.mem[2] == 0 and not any(x[0] == 0xFC for x in out), 'FC: Stopp, kein FC zurück')
rx(0xFB); hookrun(); check(m.mem[2] == 1 and m.mem[POS] == pos, 'FB: weiter ab Position')
m.call(LB['tce0isr']); out = hookrun()
check(m.mem[EXT] == 0 and m.mem[2] == 0, 'Clock bleibt aus: Stopp, zurück zum internen Takt')
check(m.mem[0x0a26] | m.mem[0x0a27] << 8 == B.per(m.mem[3]), 'interner Timer wieder auf Tempo %d' % m.mem[3])
start(); ev = tick(12 * 4)
check([e[0] for e in ons(ev) if e[1] == 0x90][:1] == [0] and sum(1 for e in ev if e[1] == 0xF8) == 24, 'intern läuft wieder normal, sendet Clock')
m.mem[2] = 0

print('17) Akkord + Mute + Speichern zusammen')
m.mem[0x3DD3] = 0
check(m.errors == [], 'keine NVM-Fehler %s' % m.errors[:2])


print('18) Snap pro Parameter')
m = AVR(img); m.stubs.update(keep.stubs); call('init'); m.mem[0x2218] = 8; m.mem[2] = 0
for k in range(68): m.mem[B.RAM['V'] - B.RAM['V'] + 0x3E10 + k] = 0xff
SNAP[0] = 1
m.mem[V + 5] = 100
poti(0, 5, 20); poti(0, 5, 30)
check(m.mem[V + 5] == 100, 'Velocity: Poti unter dem Wert, noch nicht eingefangen')
m.mem[0x3DD4] = 5; call('rendhook'); check(text() == 'u100', 'Anzeige zeigt aktuellen Wert %r' % text())
poti(0, 5, 110); check(m.mem[V + 5] == 110, 'überfahren: übernommen (110)')
poti(0, 5, 104); check(m.mem[V + 5] == 104, 'danach folgt der Wert direkt (104)')
m.mem[N + 6] = 62; poti(1, 6, 100); poti(1, 6, 90)
check(m.mem[N + 6] == 62, 'Tonhöhe: nicht eingefangen')
call('rendhook'); check(text().startswith('nC4'), 'Anzeige aktuelle Note %r' % text())
poti(1, 6, 50); check(m.mem[N + 6] == 50, 'Tonhöhe übernommen nach Überfahren')
m.mem[L + 7] = 2; poti(2, 7, 100); poti(2, 7, 90); check(m.mem[L + 7] == 2, 'Länge: nicht eingefangen')
poti(2, 7, 10); check(m.mem[L + 7] == 1, 'Länge: übernommen')
poti(2, 7, 20); check(m.mem[L + 7] == 2, 'Länge: Poti in derselben Stufe -> übernommen')
m.mem[P + 8] = 9; poti(3, 8, 0); poti(3, 8, 10); check(m.mem[P + 8] == 9, 'Wahrscheinlichkeit: nicht eingefangen')
poti(3, 8, 127); check(m.mem[P + 8] == 44, 'Wahrscheinlichkeit: übernommen')
m.mem[R + 9] = 1; poti(4, 9, 127); poti(4, 9, 120); check(m.mem[R + 9] == 1, 'Ratchet: nicht eingefangen')
poti(4, 9, 10); check(m.mem[R + 9] == 1, 'Ratchet: Stufe 1 erreicht'); poti(4, 9, 60); check(m.mem[R + 9] == 2, 'Ratchet: folgt')
m.mem[MODE] = 1; m.mem[CT + 10] = 0; poti(4, 10, 127); poti(4, 10, 120); check(m.mem[CT + 10] == 0, 'Akkordart: nicht eingefangen')
call('rendhook'); check(text() == 'tri ', 'Anzeige aktuelle Akkordart %r' % text())
poti(4, 10, 5); poti(4, 10, 40); check(m.mem[CT + 10] == 2, 'Akkordart: übernommen')
m.mem[MODE] = 0
m.mem[0x3DE2] = 1; poti(0, 67, 120, shift=1); poti(0, 67, 110, shift=1); check(m.mem[0x3DE2] == 1, 'Skala: nicht eingefangen')
poti(0, 67, 5, shift=1); check(m.mem[0x3DE2] == 0, 'Skala: übernommen')
m.mem[0x3DED] = 3; poti(0, 64, 0, shift=1); poti(0, 64, 10, shift=1); check(m.mem[0x3DED] == 3, 'Shuffle: nicht eingefangen')
poti(0, 64, 127, shift=1); check(m.mem[0x3DED] == 6, 'Shuffle: übernommen')
m.mem[0x3DE8] = 0; poti(0, 66, 100, shift=1); poti(0, 66, 80, shift=1); check(m.mem[0x3DE8] == 0, 'Grundton: nicht eingefangen')
check(poti(0, 65, 80) == 'bearbeitet' and m.mem[B.patterns.CONSTS['VTRIM1']] == 80,
      'Poti 66: Velocity-Trim für Spur 2')
poti(0, 65, 64)
SNAP[0] = 0
m.mem[V + 11] = 100; poti(0, 11, 20); check(m.mem[V + 11] == 20, 'Jump-Modus: sofort übernommen')

print('19) Shift + Poti = Mute')
m.mem[V + 16] = 77; m.mem[MREQ + 1] = 0
poti(0, 16, 30); poti(0, 16, 31, shift=1)
check(m.mem[MREQ + 1] == 1 and m.mem[MUTE + 1] == 1 and m.mem[V + 16] == 30, 'Shift + rechts: Spur 2 stumm, Step unverändert')
call('rendhook'); check(text().rstrip() == 'oFF', 'Anzeige %r' % text())
poti(0, 31, 90, shift=1); check(m.mem[MREQ + 1] == 1, 'anderes Poti der Spur, erste Bewegung rechts der Mitte: bleibt stumm')
poti(0, 31, 80, shift=1); check(m.mem[MREQ + 1] == 0 and m.mem[MUTE + 1] == 0, 'Shift + links: Spur 2 wieder an')
check(m.mem[V + 31] == 0, 'Step-Velocity von Poti 32 unverändert')
m.mem[0x3DE2] = 4; poti(0, 67, 30)
check(m.mem[0x3DE2] == 4 and m.mem[B.patterns.CONSTS['VTRIM3']] == 30, 'Poti 68 ohne Shift: nur Velocity-Trim')
poti(0, 67, 64)
v40 = m.mem[V + 40]; poti(5, 40, 90); check(m.mem[V + 40] == v40, 'Taste 5 verändert nicht mehr die Velocity')
check(poti(0, 12, 50, setup=1) == 'setup', 'Setup-Seite: Firmware wie gehabt')
poti(0, 12, 50); m.mem[V + 12] = 9; poti(0, 12, 50)
check(m.mem[V + 12] == 9, 'unveränderter Rohwert: keine Aktion')


print('20) Nudge (Taste 5)')
NUD = 0x3EE0
m = AVR(img); m.stubs.update(keep.stubs); call('init'); m.mem[0x2218] = 8; m.mem[2] = 0
SNAP[0] = 0
check(set(m.mem[NUD:NUD + 64]) == {6}, 'Grundwert: alle Steps ohne Verschiebung')
def run(n): start(); return tick(n)
def on(ev, ch=0x90): return [e[0] for e in ev if e[1] == ch]
clear_steps()
for i in range(64): m.mem[NUD + i] = 6
m.mem[V + 1] = 100                                   # Step 2 (Tick 12)
check(on(run(48)) == [12], 'ohne Nudge: Step 2 auf Tick 12')
m.mem[NUD + 1] = 9; check(on(run(48)) == [15], 'Nudge +3: Tick 15')
m.mem[NUD + 1] = 3; check(on(run(48)) == [9], 'Nudge -3: Tick 9 (im vorherigen Step ausgelöst)')
m.mem[NUD + 1] = 0; check(on(run(48)) == [6], 'Nudge -6: Tick 6 (halber Step früher)')
m.mem[NUD + 1] = 12; check(on(run(48)) == [18], 'Nudge +6: Tick 18')
ev = run(48); offs = [e[0] for e in ev if e[1] == 0x80]
check(len(offs) == 1 and offs[0] == 18 + 6, 'Note-Off kommt Notenlänge nach dem verschobenen Note-On (%s)' % offs)
m.mem[NUD + 1] = 6; m.mem[R + 1] = 2; m.mem[NUD + 1] = 12
check(on(run(48)) == [18, 24], 'Nudge +6 mit Ratchet 2: zweiter Schlag ragt in den nächsten Step (18, 24)')
m.mem[R + 1] = 4; m.mem[NUD + 1] = 0
check(on(run(48)) == [6, 9, 12, 15], 'Nudge -6 mit Ratchet 4: 6, 9, 12, 15')
m.mem[R + 1] = 1; m.mem[NUD + 1] = 6
m.mem[SPD] = 2; m.mem[NUD + 1] = 0                   # Speed 1/2: Step = 24 Ticks
check(on(run(96)) == [12], 'Speed 1/2: Nudge -6 = 12 Ticks früher (Tick 12 statt 24)')
m.mem[SPD] = 4; m.mem[NUD + 1] = 6
m.mem[V + 1] = 0
m.mem[V] = 100; m.mem[NUD] = 2; m.mem[TLEN] = 4
r1 = on(run(96)); check(r1 == [0, 44, 92], 'Step 1 vorgezogen: beim Start auf Tick 0, danach 4 Ticks vor jedem Durchlauf (%s)' % r1)
m.mem[TLEN] = 16; m.mem[NUD] = 6; m.mem[V] = 0
# Zufall/Pingpong: vorgezogene Steps passen zur tatsächlichen Reihenfolge
for d in (2, 3):
    clear_steps()
    for i in range(8): m.mem[V + i] = 100; m.mem[N + i] = 10 + 10 * i; m.mem[NUD + i] = 3
    m.mem[TLEN] = 8; m.mem[DIR] = d
    ev = run(12 * 40); ns = [e for e in ev if e[1] == 0x90]
    gaps = sorted(set(b[0] - a[0] for a, b in zip(ns[1:], ns[2:])))
    check(len(ns) == 41 and ns[-1][0] == 477 and ns[0][0] == 0 and ns[1][0] == 9 and gaps == [12], '%s: jeder Step genau einmal (41. schon vorgezogen auf 477), ab Step 2 je 3 Ticks früher (Abstände %s)'
          % ('Pingpong' if d == 2 else 'Zufall', gaps))
m.mem[DIR] = 0; m.mem[TLEN] = 16
for i in range(64): m.mem[NUD + i] = 6
# Chord mit Nudge
clear_steps(); m.mem[MODE] = 1; m.mem[0x3DE2] = 1; m.mem[V + 1] = 100; m.mem[NUD + 1] = 3
ev = run(48); ch = sorted(e[2] for e in ev if e[1] == 0x90 and e[0] == 9)
check(ch == [60, 64, 67], 'Chord vorgezogen: ganzer Akkord auf Tick 9 %s' % ch)
m.mem[MODE] = 0; m.mem[0x3DE2] = 0; m.mem[NUD + 1] = 6
# Bedienung
m.mem[2] = 0
check(poti(5, 7, 0) == 'bearbeitet' and m.mem[NUD + 7] == 0, 'Taste 5 + Poti links: -6')
m.mem[0x3DD4] = 5; call('rendhook'); t1 = text()
poti(5, 7, 64); t2 = (call('rendhook'), text())[1]
poti(5, 7, 127); t3 = (call('rendhook'), text())[1]
check(m.mem[NUD + 7] == 12 and (t1, t2, t3) == ('nd-6', 'nd 0', 'nd 6'), 'Anzeige %s %s %s' % (t1, t2, t3))
SNAP[0] = 1; m.mem[NUD + 8] = 12; m.mem[0x3E10 + 8] = 0xff
poti(5, 8, 0); poti(5, 8, 10); check(m.mem[NUD + 8] == 12, 'Snap: Nudge erst nach Einfangen')
poti(5, 8, 127); poti(5, 8, 70); check(m.mem[NUD + 8] == 7, 'Snap: dann übernommen')
SNAP[0] = 0
for i in range(16, 32): m.mem[NUD + i] = 1
poti(6, 20, 127); check(set(m.mem[NUD + 16:NUD + 32]) == {6}, 'Spur löschen setzt Nudge zurück')
m.mem[NUD + 33] = 2
call('pattern_save'); tick(220)
check(m.ee[0x400 + 6 * 64 + 33] == 2, 'Nudge wird im EEPROM gespeichert')

print('21) Durchlauf-Wechsel beim ersten Step')
clear_steps(); m.mem[TLEN] = 4; m.mem[V + 3] = 100; m.mem[P + 3] = 10   # Step 4, Bedingung 1:2
ev = run(48 * 6)
check(on(ev) == [36, 132, 228], 'Bedingung 1:2 auf dem letzten Step: Durchlauf 1, 3, 5 (%s)' % on(ev))
m.mem[P + 3] = 9; start(); tick(40)
m.mem[0x3E10 + 3] = 60; poti(0, 3, 70, shift=1)
ev = tick(48)
check(on(ev) == [], 'Mute während Durchlauf: letzter Step des Durchlaufs ist schon nach dem Wechsel stumm (%s)' % on(ev))
m.mem[0x3E10 + 3] = 60; poti(0, 3, 50, shift=1); start(); tick(30)
m.mem[0x3E10 + 3] = 50; poti(0, 3, 70, shift=1); ev = tick(18)
check(on(ev) == [36 - 30], 'Mute im laufenden Durchlauf: Step 4 dieses Durchlaufs spielt noch (%s)' % on(ev))
m.mem[TLEN] = 16

print('22) Ctrl all (Lock + Poti)')
m = AVR(img); m.stubs.update(keep.stubs); call('init'); m.mem[0x2218] = 8; m.mem[2] = 0
SNAP[0] = 0
for k in range(68): m.mem[0x3E10 + k] = 0xff
clear_steps()
for k in range(64): m.mem[NUD + k] = 6
T2 = 16
vals = {0: 100, 3: 50, 7: 120, 12: 2}
for k, v in vals.items(): m.mem[V + T2 + k] = v
m.mem[V + 0] = 90; m.mem[V + 32] = 80                 # andere Spuren
before_other = bytes(m.mem[V:V + 16]) + bytes(m.mem[V + 32:V + 64])
check(poti(0, 17, 40, lock=1) == 'bearbeitet' and [m.mem[V + T2 + k] for k in (0, 3, 7, 12)] == [100, 50, 120, 2],
      'erste Bewegung (Ausgangsstellung unbekannt): keine Änderung')
poti(0, 17, 50, lock=1)
check([m.mem[V + T2 + k] for k in (0, 3, 7, 12)] == [110, 60, 127, 12], 'Velocity +10 relativ, 120 begrenzt auf 127')
check(m.mem[V + T2 + 5] == 0 and m.mem[V + T2 + 1] == 0, 'ausgeschaltete Steps bleiben aus')
check(bytes(m.mem[V:V + 16]) + bytes(m.mem[V + 32:V + 64]) == before_other, 'andere Spuren unverändert')
m.mem[0x3DD4] = 5; call('rendhook'); check(text() == 'u   ' or text().startswith('u') or text() == 'oFF ', 'Anzeige Velocity %r' % text())
poti(0, 17, 0, lock=1)
check([m.mem[V + T2 + k] for k in (0, 3, 7, 12)] == [60, 10, 77, 1], 'Velocity -50: nie unter 1, Steps bleiben aktiv')
poti(0, 18, 127, lock=1); poti(0, 18, 100, lock=1)
check([m.mem[V + T2 + k] for k in (0, 3, 7, 12)] == [33, 1, 50, 1], 'anderes Poti derselben Spur wirkt genauso (-27)')
for k in range(16): m.mem[N + T2 + k] = 62
m.mem[N + T2 + 3] = 70
poti(1, 20, 30, lock=1); poti(1, 20, 35, lock=1)
check([m.mem[N + T2 + k] for k in (0, 3, 5)] == [67, 75, 62], 'Taste 1: Tonhöhe aller aktiven Steps +5, inaktive bleiben')
call('rendhook'); check(text().startswith('n'), 'Anzeige Note des bewegten Steps %r' % text())
poti(2, 21, 0, lock=1); poti(2, 21, 64, lock=1)
check([m.mem[L + T2 + k] for k in (0, 3, 7)] == [10, 10, 10], 'Taste 2: Länge +8 Stufen (2 -> 10)')
poti(2, 21, 127, lock=1); check(m.mem[L + T2] == 15, 'Länge begrenzt auf 15')
poti(3, 22, 127, lock=1); poti(3, 22, 0, lock=1)
check(m.mem[P + T2] == 0, 'Taste 3: Wahrscheinlichkeit nach ganz links begrenzt (10 %)')
poti(4, 23, 0, lock=1); poti(4, 23, 127, lock=1)
check([m.mem[R + T2 + k] for k in (0, 3)] == [4, 4], 'Taste 4: Ratchet +3, begrenzt auf 4')
m.mem[MODE + 1] = 1
poti(4, 24, 0, lock=1); poti(4, 24, 50, lock=1)
check([m.mem[CT + T2 + k] for k in (0, 3)] == [3, 3] and m.mem[R + T2] == 4, 'Chord-Spur: Taste 4 verschiebt Akkordart (+3), Ratchet bleibt')
m.mem[MODE + 1] = 0
poti(5, 25, 64, lock=1); poti(5, 25, 30, lock=1)
check([m.mem[NUD + T2 + k] for k in (0, 3, 1)] == [3, 3, 6], 'Taste 5: Nudge aller aktiven Steps -3')
v0 = bytes(m.mem[V + T2:V + T2 + 16])
poti(6, 26, 0, lock=1); poti(6, 26, 127, lock=1)
check(bytes(m.mem[V + T2:V + T2 + 16]) == v0 and m.mem[V + T2 + 1] == 0, 'Lock + Taste 6: nichts (kein Löschen)')
m.mem[0x3DE2] = 0; poti(0, 67, 120, shift=1, lock=1)
check(m.mem[0x3DE2] == 10, 'Shift + grosses Poti mit Lock: Skala')
m.mem[0x212f] = 1; flow.clear(); call('locktog')
check(m.mem[0x212f] == 0 and flow == ['lock-weiter'], 'Lock im SEq-Spielmodus: keine Anzeige-Verriegelung')
m.mem[0x2218] = 1; flow.clear(); call('locktog'); a = m.mem[0x212f]; call('locktog'); b = m.mem[0x212f]
check((a, b) == (1, 0), 'Lock ausserhalb SEq: Anzeige-Verriegelung wie original (an/aus)')
m.mem[0x2218] = 8
print('\nERGEBNIS:', 'alles in Ordnung' if ok else 'FEHLER gefunden')
sys.exit(0 if ok else 1)
