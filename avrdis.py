#!/usr/bin/env python3
"""Minimaler AVR/XMEGA-Disassembler.
Benutzung: python avrdis.py image.bin > image.lst
Zeilenformat: Byteadresse: Rohbytes  Mnemonic  Operanden  ; Hinweise
"""
import sys

BR = {  # SREG-Bit -> (gesetzt, gelöscht)
    0: ('brcs', 'brcc'), 1: ('breq', 'brne'), 2: ('brmi', 'brpl'), 3: ('brvs', 'brvc'),
    4: ('brlt', 'brge'), 5: ('brhs', 'brhc'), 6: ('brts', 'brtc'), 7: ('brie', 'brid')}
FLAG = 'cznvshti'


def s(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def dis(img, a):
    """Gibt (Länge in Bytes, Text) für die Instruktion an Byteadresse a zurück."""
    w = img[a] | img[a + 1] << 8
    w2 = (img[a + 2] | img[a + 3] << 8) if a + 3 < len(img) else 0
    d5 = (w >> 4) & 31
    r5 = (w & 15) | ((w >> 5) & 16)
    d4 = 16 + ((w >> 4) & 15)
    k8 = (w & 15) | ((w >> 4) & 0xF0)

    if w == 0x0000: return 2, 'nop'
    top = w >> 12
    if top == 0:
        op = (w >> 8) & 15
        if op == 1: return 2, 'movw r%d,r%d' % (((w >> 4) & 15) * 2, (w & 15) * 2)
        if op == 2: return 2, 'muls r%d,r%d' % (d4, 16 + (w & 15))
        if op == 3:
            n = ['mulsu', 'fmul', 'fmuls', 'fmulsu'][((w >> 6) & 2) | ((w >> 3) & 1)]
            return 2, '%s r%d,r%d' % (n, 16 + ((w >> 4) & 7), 16 + (w & 7))
        n = {4: 'cpc', 5: 'cpc', 6: 'sbc', 7: 'sbc', 8: 'add', 9: 'add', 10: 'add', 11: 'add'}  # grob
        n = ['', '', '', '', 'cpc', 'cpc', 'cpc', 'cpc', 'sbc', 'sbc', 'sbc', 'sbc', 'add', 'add', 'add', 'add'][op]
        if op in (4, 5, 6, 7): n = 'cpc'
        if op in (8, 9, 10, 11): n = 'sbc'
        if op in (12, 13, 14, 15): n = 'add'
        return 2, '%s r%d,r%d' % (n, d5, r5)
    if top == 1:
        n = ['cpse', 'cp', 'sub', 'adc'][(w >> 10) & 3]
        return 2, '%s r%d,r%d' % (n, d5, r5)
    if top == 2:
        n = ['and', 'eor', 'or', 'mov'][(w >> 10) & 3]
        if n == 'eor' and d5 == r5: return 2, 'clr r%d' % d5
        return 2, '%s r%d,r%d' % (n, d5, r5)
    if top in (3, 4, 5, 6, 7):
        n = {3: 'cpi', 4: 'sbci', 5: 'subi', 6: 'ori', 7: 'andi'}[top]
        return 2, '%s r%d,0x%02x' % (n, d4, k8)
    if top in (8, 10):
        q = ((w >> 8) & 0x20) | ((w >> 7) & 0x18) | (w & 7)
        yz = 'y' if w & 8 else 'z'
        if w & 0x200: return 2, 'std %s+%d,r%d' % (yz, q, d5) if q else 'st %s,r%d' % (yz, d5)
        return 2, 'ldd r%d,%s+%d' % (d5, yz, q) if q else 'ld r%d,%s' % (d5, yz)
    if top == 9:
        hi = (w >> 8) & 15
        lo = w & 15
        if hi in (0, 1):
            m = {0: ('lds', 4), 1: ('ld r%d,z+', 0), 2: ('ld r%d,-z', 0), 4: ('lpm r%d,z', 0), 5: ('lpm r%d,z+', 0),
                 6: ('elpm r%d,z', 0), 7: ('elpm r%d,z+', 0), 9: ('ld r%d,y+', 0), 10: ('ld r%d,-y', 0),
                 12: ('ld r%d,x', 0), 13: ('ld r%d,x+', 0), 14: ('ld r%d,-x', 0), 15: ('pop r%d', 0)}
            if lo == 0: return 4, 'lds r%d,0x%04x' % (d5, w2)
            if lo in m: return 2, m[lo][0] % d5
        if hi in (2, 3):
            m = {1: 'st z+,r%d', 2: 'st -z,r%d', 4: 'xch z,r%d', 5: 'las z,r%d', 6: 'lac z,r%d', 7: 'lat z,r%d',
                 9: 'st y+,r%d', 10: 'st -y,r%d', 12: 'st x,r%d', 13: 'st x+,r%d', 14: 'st -x,r%d', 15: 'push r%d'}
            if lo == 0: return 4, 'sts 0x%04x,r%d' % (w2, d5)
            if lo in m: return 2, m[lo] % d5
        if hi in (4, 5):
            m = {0: 'com', 1: 'neg', 2: 'swap', 3: 'inc', 5: 'asr', 6: 'lsr', 7: 'ror', 10: 'dec'}
            if lo in m: return 2, '%s r%d' % (m[lo], d5)
            if lo == 8:
                sp = {0x9508: 'ret', 0x9518: 'reti', 0x9588: 'sleep', 0x9598: 'break', 0x95A8: 'wdr',
                      0x95C8: 'lpm', 0x95D8: 'elpm', 0x95E8: 'spm', 0x95F8: 'spm z+'}
                if w in sp: return 2, sp[w]
                if (w & 0xFF8F) == 0x9408: return 2, 'se' + FLAG[(w >> 4) & 7]
                if (w & 0xFF8F) == 0x9488: return 2, 'cl' + FLAG[(w >> 4) & 7]
            if lo == 9:
                sp = {0x9409: 'ijmp', 0x9419: 'eijmp', 0x9509: 'icall', 0x9519: 'eicall'}
                if w in sp: return 2, sp[w]
            if lo == 11 and hi == 4: return 2, 'des 0x%x' % ((w >> 4) & 15)
            if lo in (12, 13, 14, 15):
                tgt = ((((w >> 3) & 0x3E) | (w & 1)) << 16 | w2) * 2
                return 4, '%s 0x%x' % ('jmp' if lo < 14 else 'call', tgt)
        if hi in (6, 7):
            n = 'adiw' if hi == 6 else 'sbiw'
            return 2, '%s r%d,%d' % (n, 24 + ((w >> 3) & 6), ((w >> 2) & 0x30) | (w & 15))
        if hi in (8, 9, 10, 11):
            n = ['cbi', 'sbic', 'sbi', 'sbis'][hi - 8]
            return 2, '%s 0x%02x,%d' % (n, (w >> 3) & 31, w & 7)
        if hi >= 12: return 2, 'mul r%d,r%d' % (d5, r5)
        return 2, '.dw 0x%04x' % w
    if top == 11:
        A = ((w >> 5) & 0x30) | (w & 15)
        if w & 0x800: return 2, 'out 0x%02x,r%d' % (A, d5)
        return 2, 'in r%d,0x%02x' % (d5, A)
    if top in (12, 13):
        k = s(w & 0xFFF, 12)
        return 2, '%s 0x%x' % ('rjmp' if top == 12 else 'rcall', (a + 2 + 2 * k) & 0x1FFFF)
    if top == 14:
        if k8 == 0xFF: return 2, 'ser r%d' % d4
        return 2, 'ldi r%d,0x%02x' % (d4, k8)
    if top == 15:
        if w & 0x800 == 0:
            k = s((w >> 3) & 0x7F, 7)
            sb = w & 7
            n = BR[sb][1 if w & 0x400 else 0]
            return 2, '%s 0x%x' % (n, (a + 2 + 2 * k) & 0x1FFFF)
        n = ['bld', 'bst', 'sbrc', 'sbrs'][(w >> 9) & 3]
        return 2, '%s r%d,%d' % (n, d5, w & 7)
    return 2, '.dw 0x%04x' % w


def main(path):
    img = open(path, 'rb').read()
    a = 0
    while a + 1 < len(img):
        n, t = dis(img, a)
        raw = ' '.join('%02x' % b for b in img[a:a + n])
        print('%05x: %-12s %s' % (a, raw, t))
        a += n


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
