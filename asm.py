#!/usr/bin/env python3
"""Baut aus PC44_V0101.syx eine Version mit eingebautem 16-Step-Sequencer (Test 1).

  (Assembler und Selbsttest; von build.py verwendet)

Was gepatcht wird (alle Adressen = Byteadressen im Flash-Abbild):
  0x0BC   Vektor TCE0-Überlauf: rjmp 0x194 -> jmp isr
  0x6856  in main: call 0x407e -> call init   (init macht Timer-Setup und springt dann nach 0x407e)
  0x6D00  neuer Code (init, isr, Pattern-Tabelle)
Voraussetzungen (aus der Analyse):
  0xA9A   midi_send3(status=r24, data1=r22, data2=r20) -> r24=1 gesendet / 0 belegt
  Rücksprungadresse auf dem Stack: 3 Bytes (128K+8K Flash), nach 16 Pushes bei SP+17..19
  TCE0 (0x0A00) und GPIOR0..2 (0x00..0x02) werden von der Firmware nicht benutzt.
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pc44tool import decode, encode          # noqa: E402
from avrdis import dis                       # noqa: E402

CODE_BASE = 0x6D00
SEND3 = 0xA9A
# Sperrbereich: Senderoutinen, die die UART-Interrupts selbst abschalten (0x99A..0xBF0).
# Unterbricht der Timer Code in diesem Bereich, wird der Tick ausgelassen.
GUARD_LO, GUARD_HI = 0x99A, 0xBF0
ORIG_CALL = 0x407E
VEC_TCE0_OVF = 0x00BC
CALL_SITE = 0x6856

# 16 Steps, MIDI-Noten (0 = Pause), c-Moll-Linie
PATTERN = [48, 0, 51, 55, 0, 51, 0, 53, 48, 0, 55, 58, 55, 0, 51, 0]
# PER = 62499 -> bei 32 MHz / 64 = 125 ms pro Step (16tel bei 120 BPM)
PER = 62499

ASM = """
init:
    ldi r18,PERLO
    sts 0x0a26,r18
    ldi r18,PERHI
    sts 0x0a27,r18
    ldi r18,0x02
    sts 0x0a06,r18
    ldi r18,0x05
    sts 0x0a00,r18
    out 0x00,r1
    out 0x01,r1
    out 0x02,r1
    jmp ORIG
isr:
    push r1
    push r0
    in r0,0x3f
    push r0
    clr r1
    in r0,0x3b
    push r0
    push r18
    push r19
    push r20
    push r21
    push r22
    push r23
    push r24
    push r25
    push r26
    push r27
    push r30
    push r31
    out 0x3b,r1
    in r30,0x3d
    in r31,0x3e
    ldd r25,z+18
    ldd r24,z+19
    subi r24,GLO
    sbci r25,GHI
    cpi r24,GLENLO
    ldi r18,GLENHI
    cpc r25,r18
    brcs Lexit
    in r18,0x01
    tst r18
    breq Lnote
    ldi r24,0x80
    mov r22,r18
    ldi r20,0x40
    call SEND3
    tst r24
    breq Lexit
    out 0x01,r1
Lnote:
    in r18,0x00
    ldi r30,lo8(table)
    ldi r31,hi8(table)
    add r30,r18
    adc r31,r1
    lpm r19,z
    tst r19
    breq Ladv
    out 0x02,r19
    ldi r24,0x90
    mov r22,r19
    ldi r20,0x64
    call SEND3
    tst r24
    breq Lexit
    in r19,0x02
    out 0x01,r19
Ladv:
    in r18,0x00
    inc r18
    andi r18,0x0f
    out 0x00,r18
Lexit:
    pop r31
    pop r30
    pop r27
    pop r26
    pop r25
    pop r24
    pop r23
    pop r22
    pop r21
    pop r20
    pop r19
    pop r18
    pop r0
    out 0x3b,r0
    pop r0
    out 0x3f,r0
    pop r0
    pop r1
    reti
table:
    .byte TABLE
"""


# ---------------------------------------------------------------- Assembler
def reg(s):
    m = re.fullmatch(r'r(\d+)', s.strip().lower())
    assert m, 'Register erwartet: %r' % s
    n = int(m.group(1))
    assert 0 <= n <= 31
    return n


def num(s, labels=None):
    s = s.strip()
    m = re.fullmatch(r'(lo8|hi8)\((\w+)\)', s)
    if m:
        v = labels[m.group(2)] if m.group(2) in (labels or {}) else int(m.group(2), 0)
        return v & 0xFF if m.group(1) == 'lo8' else (v >> 8) & 0xFF
    if labels and s in labels:
        return labels[s]
    return int(s, 0)


def two(rd, rr, base):
    return base | ((rr & 0x10) << 5) | (rd << 4) | (rr & 0x0F)


def w(*words):
    return b''.join(x.to_bytes(2, 'little') for x in words)


def encode_line(op, args, pc, labels):
    a = [x.strip() for x in args.split(',')] if args else []
    if op == 'push': return w(0x920F | reg(a[0]) << 4)
    if op == 'pop': return w(0x900F | reg(a[0]) << 4)
    if op == 'reti': return w(0x9518)
    if op == 'nop': return w(0)
    if op == 'cli': return w(0x94F8)
    if op == 'sei': return w(0x9478)
    if op == 'clr': return w(two(reg(a[0]), reg(a[0]), 0x2400))
    if op == 'tst': return w(two(reg(a[0]), reg(a[0]), 0x2000))
    if op == 'mov': return w(two(reg(a[0]), reg(a[1]), 0x2C00))
    if op == 'add': return w(two(reg(a[0]), reg(a[1]), 0x0C00))
    if op == 'adc': return w(two(reg(a[0]), reg(a[1]), 0x1C00))
    if op == 'inc': return w(0x9403 | reg(a[0]) << 4)
    if op == 'cpc': return w(two(reg(a[0]), reg(a[1]), 0x0400))
    if op in ('sbrs', 'sbrc'):
        b = num(a[1], labels)
        assert 0 <= b <= 7
        return w((0xFE00 if op == 'sbrs' else 0xFC00) | reg(a[0]) << 4 | b)
    if op == 'lds':
        return w(0x9000 | reg(a[0]) << 4, num(a[1], labels))
    if op == 'ldd':
        m = re.fullmatch(r'z\+(\d+)', a[1].lower())
        q = int(m.group(1))
        assert 0 <= q <= 63
        return w(0x8000 | (q & 0x20) << 8 | (q & 0x18) << 7 | reg(a[0]) << 4 | (q & 7))
    if op in ('ldi', 'andi', 'subi', 'sbci', 'cpi', 'ori'):
        d, k = reg(a[0]), num(a[1], labels)
        assert d >= 16 and 0 <= k <= 255
        base = {'ldi': 0xE000, 'andi': 0x7000, 'subi': 0x5000, 'sbci': 0x4000, 'cpi': 0x3000, 'ori': 0x6000}[op]
        return w(base | (k & 0xF0) << 4 | (d - 16) << 4 | (k & 0x0F))
    if op == 'in':
        A = num(a[1], labels)
        return w(0xB000 | (A & 0x30) << 5 | reg(a[0]) << 4 | (A & 0x0F))
    if op == 'out':
        A = num(a[0], labels)
        return w(0xB800 | (A & 0x30) << 5 | reg(a[1]) << 4 | (A & 0x0F))
    if op == 'sts':
        return w(0x9200 | reg(a[1]) << 4, num(a[0], labels))
    if op == 'lpm':
        assert a[1].lower() in ('z', 'z+')
        return w((0x9005 if a[1].lower() == 'z+' else 0x9004) | reg(a[0]) << 4)
    if op == 'ret': return w(0x9508)
    if op == 'adiw':
        d, k = reg(a[0]), num(a[1], labels)
        assert d in (24, 26, 28, 30) and 0 <= k <= 63
        return w(0x9600 | (k & 0x30) << 2 | ((d - 24) // 2) << 4 | (k & 0x0F))
    if op == 'and': return w(two(reg(a[0]), reg(a[1]), 0x2000))
    if op == 'cp': return w(two(reg(a[0]), reg(a[1]), 0x1400))
    if op == 'st':
        m = {'x': 0x920C, 'x+': 0x920D, 'z+': 0x9201, 'z': 0x8200}[a[0].lower()]
        return w(m | reg(a[1]) << 4)
    if op == 'ld':
        m = {'z+': 0x9001, 'z': 0x8000, 'x': 0x900C, 'x+': 0x900D}[a[1].lower()]
        return w(m | reg(a[0]) << 4)
    if op == 'mul': return w(two(reg(a[0]), reg(a[1]), 0x9C00))
    if op == 'eor': return w(two(reg(a[0]), reg(a[1]), 0x2400))
    if op == 'or': return w(two(reg(a[0]), reg(a[1]), 0x2800))
    if op == 'swap': return w(0x9402 | reg(a[0]) << 4)
    if op == 'neg': return w(0x9401 | reg(a[0]) << 4)
    if op == 'lsr': return w(0x9406 | reg(a[0]) << 4)
    if op == 'ror': return w(0x9407 | reg(a[0]) << 4)
    if op == 'dec': return w(0x940A | reg(a[0]) << 4)
    if op == 'sub': return w(two(reg(a[0]), reg(a[1]), 0x1800))
    if op == 'rjmp':
        off = (num(a[0], labels) - (pc + 2)) // 2
        assert -2048 <= off <= 2047, 'rjmp zu weit'
        return w(0xC000 | (off & 0xFFF))
    if op in ('jmp', 'call'):
        k = num(a[0], labels) // 2
        first = (0x940C if op == 'jmp' else 0x940E) | ((k >> 17) & 0x1F) << 4 | ((k >> 16) & 1)
        return w(first, k & 0xFFFF)
    if op in ('breq', 'brcs', 'brcc', 'brne'):
        off = (num(a[0], labels) - (pc + 2)) // 2
        assert -64 <= off <= 63, '%s %s zu weit (bei 0x%X)' % (op, a[0], pc)
        base = {'breq': 0xF001, 'brcs': 0xF000, 'brcc': 0xF400, 'brne': 0xF401}[op]
        return w(base | (off & 0x7F) << 3)
    raise ValueError('unbekannter Befehl ' + op)


def size_of(op):
    return 4 if op in ('jmp', 'call', 'sts', 'lds') else 2


def assemble(src, base, consts):
    lines = []
    for raw in src.splitlines():
        t = raw.split(';')[0].strip()
        if not t:
            continue
        for k, v in consts.items():
            t = re.sub(r'\b%s\b' % k, str(v), t)
        lines.append(t)
    labels, pc, items = {}, base, []
    for t in lines:                                   # Pass 1
        if t.endswith(':'):
            labels[t[:-1]] = pc
            continue
        op, _, args = t.partition(' ')
        if op == '.byte':
            n = len([x for x in args.split(',') if x.strip()])
            items.append((pc, op, args))
            pc += n
        else:
            items.append((pc, op, args))
            pc += size_of(op)
    out = bytearray()
    for pc, op, args in items:                        # Pass 2
        if op == '.byte':
            out += bytes(int(x, 0) for x in args.split(','))
        else:
            out += encode_line(op, args, pc, labels)
    return bytes(out), labels


def self_test():
    """Der Assembler muss Befehle bytegleich zu echten Firmware-Befehlen erzeugen."""
    cases = [  # (Befehl, Argumente, erwartete Bytes aus PC44_V0101.lst)
        ('push', 'r1', '1f 92'), ('pop', 'r0', '0f 90'), ('in', 'r0,0x3f', '0f b6'),
        ('out', '0x3b,r0', '0b be'), ('clr', 'r1', '11 24'), ('ldi', 'r30,0xa2', 'e2 ea'),
        ('andi', 'r24,0xf0', '80 7f'), ('mov', 'r28,r24', 'c8 2f'), ('lpm', 'r30,z', 'e4 91'),
        ('sts', '0x08a3,r1', '10 92 a3 08'), ('call', '0x99a', '0e 94 cd 04'),
        ('jmp', '0x6c68', '0c 94 34 36'), ('reti', '', '18 95'), ('tst', 'r24', '88 23'),
        ('inc', 'r24', '83 95'), ('add', 'r30,r18', 'e2 0f'), ('adc', 'r31,r1', 'f1 1d'),
        ('subi', 'r30,0x0e', 'ee 50'), ('sbci', 'r31,0xc5', 'f5 4c'), ('cpi', 'r18,0xc0', '20 3c'),
        ('cpc', 'r27,r18', 'b2 07'), ('ldd', 'r18,z+1', '21 81'),
        ('dec', 'r21', '5a 95'), ('adiw', 'r30,1', '31 96'), ('ori', 'r24,0xc0', '80 6c'), ('and', 'r22,r21', '65 23'), ('cp', 'r24,r18', '82 17'),
        ('st', 'x,r22', '6c 93'), ('ld', 'r18,z+', '21 91'), ('ld', 'r17,x', '1c 91'), ('ld', 'r24,z', '80 81'),
        ('st', 'x+,r1', '1d 92'), ('st', 'z,r1', '10 82'), ('st', 'z+,r0', '01 92'), ('mul', 'r14,r27', 'eb 9e'), ('swap', 'r24', '82 95'),
        ('lsr', 'r24', '86 95'), ('ror', 'r24', '87 95'), ('eor', 'r24,r25', '89 27'), ('or', 'r28,r29', 'cd 2b'), ('sub', 'r24,r14', '8e 19'), ('ret', '', '08 95'),
        ('sbrs', 'r24,0', '80 ff'), ('sbrc', 'r24,0', '80 fd'), ('lds', 'r24,0x3c37', '80 91 37 3c'),
    ]
    for op, args, exp in cases:
        got = encode_line(op, args, 0, {}).hex(' ')
        assert got == exp, '%s %s: %s != %s' % (op, args, got, exp)
    for pc, op, tgt, exp in [(0x9ac, 'brcs', 0x9c4, '58 f0'), (0x46e, 'brcc', 0x48c, '70 f4'),
                             (0x182, 'rjmp', 0x186, '01 c0'), (0x18a, 'brne', 0x184, 'e1 f7'), (0x4, 'rjmp', 0x194, 'c7 c0'),
                             (0x932, 'breq', 0x940, '31 f0')]:
        got = encode_line(op, hex(tgt), pc, {}).hex(' ')
        assert got == exp, '%s %s: %s != %s' % (op, args, got, exp)


# -------------------------------------------------------------------- Build
def main(src, dst):
    self_test()
    hdr, img = decode(open(src, 'rb').read())
    img = bytearray(img)
    assert len(img) == 0x6D00 and CODE_BASE == len(img)
    assert img[VEC_TCE0_OVF:VEC_TCE0_OVF + 4] == bytes.fromhex('6b c0 00 00'), 'Vektor unerwartet'
    assert img[CALL_SITE:CALL_SITE + 4] == bytes.fromhex('0e 94 3f 20'), 'Aufrufstelle unerwartet'

    glo, glen = GUARD_LO // 2, (GUARD_HI - GUARD_LO) // 2
    consts = dict(PERLO=PER & 0xFF, PERHI=PER >> 8, ORIG=ORIG_CALL, SEND3=SEND3,
                  GLO=glo & 0xFF, GHI=glo >> 8, GLENLO=glen & 0xFF, GLENHI=glen >> 8,
                  TABLE=', '.join(str(n) for n in PATTERN))
    code, labels = assemble(ASM, CODE_BASE, consts)
    print('Code: %d Bytes bei 0x%04X  init=0x%04X isr=0x%04X table=0x%04X'
          % (len(code), CODE_BASE, labels['init'], labels['isr'], labels['table']))

    img[VEC_TCE0_OVF:VEC_TCE0_OVF + 4] = encode_line('jmp', hex(labels['isr']), 0, {})
    img[CALL_SITE:CALL_SITE + 4] = encode_line('call', hex(labels['init']), 0, {})
    img += code
    img += b'\xff' * (-len(img) % 256)

    out = encode(bytes(img), hdr)
    open(dst, 'wb').write(out)
    print('geschrieben:', dst, len(out), 'Bytes,', len(img) // 256, 'Seiten')
    return img, labels


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
