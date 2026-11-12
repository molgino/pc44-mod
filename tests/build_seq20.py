#!/usr/bin/env python3
"""PC44-Sequencer v20: Pattern bleibt nach dem Ausschalten erhalten, Spur löschen mit Taste 6.

  python build_seq20.py PC44_V0101.syx PC44_seq20.syx

Spielmodus (Routing "SEq", Setup Taste 2):
  Poti-Reihen 1+2 = Spur 1, 3+4 = Spur 2, 5+6 = Spur 3, 7+8 = Spur 4 (je 16 Steps)
  Poti allein:            Velocity, ganz links = Step aus          "u100" / "oFF"
  Taste 1 + Poti:         Tonhöhe in der Skala                     "nC4", "nF.3"
  Taste 2 + Poti:         Notenlänge 0.08..16 Steps                "L0.50" / "L004"
  Taste 3 + Poti:         Wahrscheinlichkeit 10..100 %, dann Bedingung 1:2..8:8   "P070" / "c2-3"
  Taste 4 + Poti:         Ratchet 1..4                             "r002"
  Taste 5 + Poti:         Mute der Spur (rechts = stumm), wirkt am Ende des Patterns   "on" / "OFF" (Punkt = wartet)
  Taste 6 + Poti:         Spur löschen: Poti einer Spur ganz nach rechts  "CL 1" -> "CLr1"
  Taste 7 / 8:            Start (FA) / Stopp (FC), Clock nur während der Wiedergabe
  Poti 65 / 67 / 68:      Shuffle / Grundton / Skala;  Poti 66 normaler Controller
  Encoder:                Tempo 30..250 BPM ("t120")
Edit-Seite (Shift + Edit im SEq-Modus):
  Poti einer Spur bewegen = Spur wählen;  Taste 1..6 = Parameter wählen, Encoder = Wert
  1 Spur "tr 1"   2 Länge "LP16"   3 Oktave "oc 0"   4 Speed "1-8".."2-1"   5 Kanal "Ch01"   6 Richtung "For/rEu/PinG/rnd"
  Taste 7 / 8 = Start / Stopp. Tasten-LED zeigt den gewählten Parameter.
Bedingung A:B = Step spielt nur im A-ten von je B Durchläufen der Spur.
Speichern: automatisch ins EEPROM (ab 0x400), sobald ~2 s nichts mehr geändert wurde.
Gesichert: alle Steps, Spur-Einstellungen, Mute, Skala, Grundton, Shuffle, Tempo. Auf diesem Chip behalten nur GPIOR0..3 Werte.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pc44tool import decode, encode                       # noqa: E402
from asm import assemble, encode_line, self_test   # noqa: E402

BASE = 0x6D00
TICKS = 12
BPM_MIN, BPM_MAX, BPM_START = 30, 250, 120
HOLD = 144               # Anzeige-Haltezeit in Sub-Ticks (~1,5 s bei 120 BPM)

RAM = dict(OFF=0x3DE4, G=0x3C40, N=0x3C80, V=0x3CC0, P=0x3D00, R=0x3D40, LN=0x3D80, ACT=0x3D84, L=0x3D88)

SCALES = [  # (Anzeige als 7-Segment-Codes, Intervalle)
    ((0x39, 0x76, 0x50, 0x5c), list(range(12))),          # CHro
    ((0x5e, 0x1c, 0x50, 0x00), [0, 2, 4, 5, 7, 9, 11]),    # dur
    ((0x77, 0x79, 0x5c, 0x38), [0, 2, 3, 5, 7, 8, 10]),    # AEol (Moll)
    ((0x5e, 0x5c, 0x50, 0x00), [0, 2, 3, 5, 7, 9, 10]),    # dor
    ((0x73, 0x76, 0x50, 0x6e), [0, 1, 3, 5, 7, 8, 10]),    # PHrY
    ((0x38, 0x6e, 0x5e, 0x00), [0, 2, 4, 6, 7, 9, 11]),    # LYd
    ((0x54, 0x06, 0x76, 0x5c), [0, 2, 4, 5, 7, 9, 10]),    # nIHo (mixolydisch)
    ((0x76, 0x77, 0x50, 0x00), [0, 2, 3, 5, 7, 8, 11]),    # HAr (harmonisch Moll)
    ((0x73, 0x40, 0x5e, 0x1c), [0, 2, 4, 7, 9]),           # P-du
    ((0x73, 0x40, 0x77, 0x79), [0, 3, 5, 7, 10]),          # P-AE
    ((0x7c, 0x38, 0x3e, 0x79), [0, 3, 5, 6, 7, 10]),       # bLUE
]
POT_SCALE, POT_ROOT = 67, 66   # interne Poti-Nummern (0-basiert) der großen Potis
# Längen-Stufen: Ticks (12 = ein 16tel), Anzeigezahl, Dezimalpunkt nach 1. Ziffer
LENGTHS = [(1, 8, 1), (3, 25, 1), (6, 50, 1), (9, 75, 1), (12, 1, 0), (24, 2, 0), (36, 3, 0), (48, 4, 0),
           (60, 5, 0), (72, 6, 0), (84, 7, 0), (96, 8, 0), (120, 10, 0), (144, 12, 0), (168, 14, 0), (192, 16, 0)]
LEN_DEFAULT = 2           # halbes 16tel
ROOTS = [(0x39, 0), (0x39, 1), (0x5e, 0), (0x5e, 1), (0x79, 0), (0x71, 0), (0x71, 1), (0x3d, 0), (0x3d, 1),
         (0x77, 0), (0x77, 1), (0x76, 0)]   # C C# D D# E F F# G G# A A# H
BASE_NOTE = 48            # C3, Bereich 2 Oktaven
TUNE_DEFAULT = 62         # Poti-Stellung, die in allen Skalen C4 ergibt


def tunetable():
    out = []
    for _, iv in SCALES:
        notes = [BASE_NOTE + 12 * o + i for o in range(2) for i in iv] + [BASE_NOTE + 24]
        n = len(notes)
        out += [notes[v * n // 128] for v in range(128)]
    return out


SPEEDS = [(1, 8, 96), (1, 4, 48), (1, 2, 24), (3, 4, 16), (1, 1, 12), (3, 2, 8), (2, 1, 6)]  # Zähler, Nenner, Ticks
SPD_DEFAULT = 4
PROB_PCT = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
CONDS = [(a, b) for b in range(2, 9) for a in range(1, b + 1)]       # 1:2, 2:2, 1:3 ... 8:8
NPROB = len(PROB_PCT) + len(CONDS)                                   # 45
PROB_DEFAULT = 9                                                     # 100 %
DIRNAMES = [(0x71, 0x5c, 0x50, 0x00), (0x50, 0x79, 0x1c, 0x00), (0x73, 0x10, 0x54, 0x3d), (0x50, 0x54, 0x5e, 0x00)]


EEBASE = 0x400            # Firmware nutzt EEPROM 0x010..0x11F
EEPAUSE = 96              # Ticks Pause zwischen zwei Prüfdurchläufen (~2 s bei 120 BPM)
MAGIC = (0x53, 20)
EEREGIONS = [  # RAM-Adresse, Länge, Minimum, Maximum (beim Laden begrenzt)
    (0x3C80, 64, 0, 127),   # N Tonhöhe
    (0x3CC0, 64, 0, 127),   # V Velocity
    (0x3D00, 64, 0, 44),    # P Wahrscheinlichkeit/Bedingung
    (0x3D40, 64, 1, 4),     # R Ratchet
    (0x3D88, 64, 0, 15),    # L Notenlänge
    (0x3DE2, 1, 0, 10),     # Skala
    (0x3DE8, 1, 0, 11),     # Grundton
    (0x3DE9, 4, 0, 6),      # Oktave pro Spur
    (0x3DED, 1, 0, 6),      # Shuffle
    (0x3DF2, 4, 1, 16),     # Pattern-Länge
    (0x3E60, 4, 0, 6),      # Speed
    (0x3E64, 4, 0, 15),     # Kanal
    (0x3E68, 4, 0, 3),      # Richtung
    (0x3E84, 4, 0, 1),      # Mute
    (0x0003, 1, 30, 250),   # Tempo (GPIOR3)
    (0x3E04, 2, 0, 255),    # Kennung, muss zuletzt stehen
]
EESIZE = sum(r[1] for r in EEREGIONS)
EENPG = (EESIZE + 31) // 32


def seqtables():
    spdt = [t for _, _, t in SPEEDS]
    swt = [round(sw * t / 12) for _, _, t in SPEEDS for sw in range(7)]
    rint = [max(1, t // r) for _, _, t in SPEEDS for r in range(1, 5)]
    thr = [round(p * 128 / 100) for p in PROB_PCT]
    conda = [a for a, b in CONDS]
    condb = [b for a, b in CONDS]
    spdd = [x for n, d, _ in SPEEDS for x in (n, d)]
    return dict(SPDT=spdt, SWT=swt, RINT=rint, PTHR=thr, CONDA=conda, CONDB=condb, SPDD=spdd,
                DIRN=[c for n in DIRNAMES for c in n])


PATCHES = [
    (0x415A, '97 30', 'cpi r25,0x09'),
    (0x5BB2, '80 91 18 22', 'jmp rinc'),
    (0x5BCE, '80 91 18 22', 'jmp rdec'),
    (0x30E0, '80 e5 80 93', 'jmp rdisp'),
    (0x1F78, '80 91 f8 3b', 'jmp encw'),
    (0x2DE4, '20 91 56 3a', 'call loopend'),
    (0x135E, '60 91 84 22', 'jmp potisend'),
    (0x3C2C, '20 91 e3 2f', 'jmp rendhook'),
    (0x3BF8, 'f0 92 a8 31', 'jmp ledhook'),
    (0x00BC, '6b c0 00 00', 'jmp tce0isr'),
    (0x1074, '20 93 a7 3a', 'call rawsave'),
    (0x1336, '40 91 a7 3a', 'jmp rawcmp'),
    (0x69B0, '0e 94 74 12', 'call seqedit'),
    (0x69B4, '0e 94 43 0b', 'call seqedit2'),
    (0x3C10, '67 e0 c9 d9', 'jmp edrend'),
    (0x6856, '0e 94 3f 20', 'call init'),
    (0x69CE, '0e 94 60 1d', 'call hook'),
]

ASM = r"""
; ================================================================ Start
init:
    ldi r18,BPMSTART
    out 0x03,r18
    ldi r18,PERLO
    sts 0x0a26,r18
    ldi r18,PERHI
    sts 0x0a27,r18
    ldi r18,0x05
    sts 0x0a00,r18
    sts 0x3de0,r1
    sts 0x3de1,r1
    ldi r18,0x01
    sts 0x0a06,r18
    ldi r26,lo8(G)
    ldi r27,hi8(G)
    ldi r18,0x00
    call fill64
    ldi r18,TUNEDEF
    call fill64
    ldi r18,0x00
    call fill64
    ldi r18,PROBDEF
    call fill64
    ldi r18,0x01
    call fill64
    push r18
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    ldi r18,LENDEF
    call fill64
    pop r18
    ldi r18,100
    sts V,r18
    sts V4,r18
    sts V8,r18
    sts V12,r18
    ldi r18,16
    sts TLEN,r18
    sts TLEN1,r18
    sts TLEN2,r18
    sts TLEN3,r18
    call posreset
    ldi r26,lo8(RAWLAST)
    ldi r27,hi8(RAWLAST)
    ldi r18,0xff
    call fill64
    st x+,r18
    st x+,r18
    st x+,r18
    st x+,r18
    call trkinit
    sts SCALE,r1
    sts ROOT,r1
    sts SWING,r1
    ldi r18,0x03
    sts OCT,r18
    sts OCT1,r18
    sts OCT2,r18
    sts OCT3,r18
    sts OFF,r1
    sts OFF1,r1
    sts OFF2,r1
    sts OFF3,r1
    ldi r18,0xff
    sts LEDROW,r18
    ldi r18,0xff
    sts LN,r18
    sts LN1,r18
    sts LN2,r18
    sts LN3,r18
    sts ACT,r1
    sts ACT1,r1
    sts ACT2,r1
    sts ACT3,r1
    sts 0x3dd4,r1
    sts 0x3dd5,r1
    sts 0x3dd6,r1
    sts 0x3dd7,r1
    sts 0x3dd8,r1
    sts 0x3dd9,r1
    sts 0x3dda,r1
    sts 0x3ddb,r1
    sts 0x3ddc,r1
    sts 0x3ddd,r1
    sts 0x3dde,r1
    sts 0x3ddf,r1
    ldi r18,0xa5
    sts 0x3dd6,r18
    ldi r18,0x5a
    sts 0x3dd7,r18
    sts 0x3dd8,r1
    ldi r18,MAG0
    sts MAGIC,r18
    ldi r18,MAG1
    sts MAGIC1,r18
    sts CLRF,r1
    sts EEPG,r1
    sts EEWAIT,r1
    call eeload
    jmp 0x407e

fill64:
    ldi r19,64
F64:
    st x+,r18
    dec r19
    brne F64
    ret

; ================================================================ Hauptschleife
hook:
    lds r24,ROUTING
    cpi r24,SEQ
    breq Hseq
    in r24,0x02
    tst r24
    breq Hdone
    call stopseq
Hdone:
    jmp 0x3ac0
Hseq:
    call isseq
    tst r25
    breq Htick
    lds r24,0x2216
    tst r24
    breq Hb8
    sts 0x2216,r1
    lds r24,0x2315
    tst r24
    breq Hb8
    in r24,0x02
    tst r24
    brne Hb8
    call seqstart
Hb8:
    lds r24,0x2217
    tst r24
    breq Hpush
    sts 0x2217,r1
    lds r24,0x2316
    tst r24
    breq Hpush
    call stopseq
Hpush:
    lds r24,0x230e
    tst r24
    breq Htick
    sts 0x3dd8,r1
    ldi r24,0xff
    sts LEDROW,r24
    ldi r24,HOLD
    sts 0x3dd4,r24
Htick:
    lds r24,0x3de0
    lds r25,0x3de1
    cp r24,r25
    brne Htk1
    rjmp Hdisp
Htk1:
    inc r25
    sts 0x3de1,r25
    lds r24,0x3dd4
    tst r24
    breq Hclk
    dec r24
    sts 0x3dd4,r24
Hclk:
    in r24,0x02
    tst r24
    breq Hrun
    lds r24,0x3dda
    inc r24
    andi r24,0x01
    sts 0x3dda,r24
    brne Hrun
    ldi r24,0xf8
    call SEND3
Hrun:
    in r24,0x02
    tst r24
    breq Hnext
    call seqtick
Hnext:
    call eetick
    rjmp Htick
Hdisp:
    jmp 0x3ac0

; Display-Aufbau der Firmware (in 0x3AC0, Spielmodus): im SEq-Modus eigene Anzeige statt Wert
rendhook:
    call isseq
    tst r25
    breq RHorig
    lds r24,0x3dd4
    tst r24
    breq RHorig
    call showdisp
    jmp 0x3e6a
RHorig:
    lds r18,0x2fe3
    jmp 0x3c30

; ================================================================ Sequencer-Takt
seqtick:
    push r16
    push r17
    lds r24,0x3dd5
    inc r24
    cpi r24,TICKS
    brcs STs
    ldi r24,0x00
    in r18,0x00
    inc r18
    andi r18,0x0f
    out 0x00,r18
STs:
    sts 0x3dd5,r24
    ldi r16,0x00
STloop:
    mov r24,r16
    call trkstep
    mov r24,r16
    call trackev
    inc r16
    cpi r16,0x04
    brne STloop
    pop r17
    pop r16
    ret

; Zufallszahl 0..127 in r24 (16-Bit-LFSR), verändert r23..r25
rand:
    lds r24,0x3dd6
    lds r25,0x3dd7
    lsr r25
    ror r24
    brcc RN1
    ldi r23,0xb4
    eor r25,r23
RN1:
    sts 0x3dd6,r24
    sts 0x3dd7,r25
    andi r24,0x7f
    ret

; Byte aus Flash-Tabelle: Z = Adresse, Ergebnis r20 (verändert r21)
lpmz:
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r20,z
    sts 0x01ca,r21
    ret

; Basis-Steplänge der Spur r17 in Ticks -> r20 (verändert r21,r30,r31)
spdbase:
    ldi r30,lo8(SPD)
    ldi r31,hi8(SPD)
    add r30,r17
    adc r31,r1
    ld r20,z
    ldi r30,lo8(spdt)
    ldi r31,hi8(spdt)
    add r30,r20
    adc r31,r1
    jmp lpmz

; Länge des aktuellen Steps der Spur r17 inkl. Shuffle -> r20 (verändert r0,r1,r19,r21,r30,r31)
curlen:
    ldi r30,lo8(SPD)
    ldi r31,hi8(SPD)
    add r30,r17
    adc r31,r1
    ld r19,z
    ldi r20,0x07
    mul r19,r20
    lds r20,SWING
    add r0,r20
    ldi r30,lo8(swt)
    ldi r31,hi8(swt)
    add r30,r0
    adc r31,r1
    clr r1
    call lpmz
    mov r19,r20
    call spdbase
    ldi r30,lo8(TPAR)
    ldi r31,hi8(TPAR)
    add r30,r17
    adc r31,r1
    ld r21,z
    tst r21
    brne CLodd
    add r20,r19
    ret
CLodd:
    sub r20,r19
    ret

; Spur r24: Sub-Tick weiterzählen, bei neuem Step Position/Durchlauf/Aktiv bestimmen
trkstep:
    mov r17,r24
    ldi r26,lo8(TSUB)
    ldi r27,hi8(TSUB)
    add r26,r17
    adc r27,r1
    ld r18,x
    cpi r18,0xff
    brne TSa
    ldi r30,lo8(TPAR)
    ldi r31,hi8(TPAR)
    add r30,r17
    adc r31,r1
    ldi r19,0x01
    st z,r19
    rjmp TSnew
TSa:
    inc r18
    push r18
    call curlen
    pop r18
    cp r18,r20
    brcc TSnew
    st x,r18
    ret
TSnew:
    st x,r1
    ldi r30,lo8(TPAR)
    ldi r31,hi8(TPAR)
    add r30,r17
    adc r31,r1
    ld r19,z
    ldi r20,0x01
    eor r19,r20
    st z,r19
    call advpos
    ldi r30,lo8(SCNT)
    ldi r31,hi8(SCNT)
    add r30,r17
    adc r31,r1
    ld r19,z
    inc r19
    ldi r26,lo8(TLEN)
    ldi r27,hi8(TLEN)
    add r26,r17
    adc r27,r1
    ld r20,x
    cp r19,r20
    brcs TSc1
    st z,r1
    ldi r30,lo8(LOOP)
    ldi r31,hi8(LOOP)
    add r30,r17
    adc r31,r1
    ld r19,z
    inc r19
    st z,r19
    ldi r30,lo8(MREQ)
    ldi r31,hi8(MREQ)
    add r30,r17
    adc r31,r1
    ld r19,z
    ldi r30,lo8(MUTE)
    ldi r31,hi8(MUTE)
    add r30,r17
    adc r31,r1
    st z,r19
    rjmp TSc2
TSc1:
    st z,r19
TSc2:
    ldi r20,0x00
    ldi r30,lo8(MUTE)
    ldi r31,hi8(MUTE)
    add r30,r17
    adc r31,r1
    ld r19,z
    tst r19
    brne TSact
    ldi r30,lo8(POS)
    ldi r31,hi8(POS)
    add r30,r17
    adc r31,r1
    ld r18,z
    mov r19,r17
    swap r19
    add r19,r18
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    add r26,r19
    adc r27,r1
    ld r18,x
    tst r18
    breq TSact
    ldi r26,lo8(P)
    ldi r27,hi8(P)
    add r26,r19
    adc r27,r1
    ld r18,x
    call probpass
TSact:
    ldi r26,lo8(ACT)
    ldi r27,hi8(ACT)
    add r26,r17
    adc r27,r1
    st x,r20
    ret

; Position der Spur r17 nach Richtung weiterschalten (verändert r18..r25,r30,r31)
advpos:
    ldi r30,lo8(TLEN)
    ldi r31,hi8(TLEN)
    add r30,r17
    adc r31,r1
    ld r19,z
    ldi r30,lo8(DIR)
    ldi r31,hi8(DIR)
    add r30,r17
    adc r31,r1
    ld r20,z
    ldi r30,lo8(POS)
    ldi r31,hi8(POS)
    add r30,r17
    adc r31,r1
    ld r18,z
    cp r18,r19
    brcs APgo
    ldi r18,0x00
    cpi r20,0x01
    brne APst0
    mov r18,r19
    dec r18
APst0:
    ldi r26,lo8(PDIR)
    ldi r27,hi8(PDIR)
    add r26,r17
    adc r27,r1
    st x,r1
    st z,r18
    ret
APgo:
    cpi r20,0x00
    brne APrev
    inc r18
    cp r18,r19
    brcs APst
    ldi r18,0x00
    rjmp APst
APrev:
    cpi r20,0x01
    brne APping
    tst r18
    brne APr1
    mov r18,r19
APr1:
    dec r18
    rjmp APst
APping:
    cpi r20,0x02
    brne APrnd
    cpi r19,0x01
    brne APp0
    ldi r18,0x00
    rjmp APst
APp0:
    ldi r26,lo8(PDIR)
    ldi r27,hi8(PDIR)
    add r26,r17
    adc r27,r1
    ld r21,x
    tst r21
    brne APdown
    inc r18
    cp r18,r19
    brcs APst
    subi r18,0x02
    ldi r21,0x01
    st x,r21
    rjmp APst
APdown:
    tst r18
    breq APup
    dec r18
    rjmp APst
APup:
    ldi r18,0x01
    st x,r1
    rjmp APst
APrnd:
    push r30
    push r31
    call rand
    pop r31
    pop r30
    mov r18,r24
APm:
    cp r18,r19
    brcs APst
    sub r18,r19
    rjmp APm
APst:
    st z,r18
    ret

; Wahrscheinlichkeit/Bedingung r18 für Spur r17 prüfen -> r20 = 1 spielt, 0 nicht (verändert r18..r25,r30,r31)
probpass:
    cpi r18,0x09
    breq PPyes
    brcc PPcond
    ldi r30,lo8(pthr)
    ldi r31,hi8(pthr)
    add r30,r18
    adc r31,r1
    call lpmz
    mov r22,r20
    call rand
    ldi r20,0x00
    cp r24,r22
    brcc PPret
PPyes:
    ldi r20,0x01
PPret:
    ret
PPcond:
    subi r18,0x0a
    ldi r30,lo8(condb)
    ldi r31,hi8(condb)
    add r30,r18
    adc r31,r1
    call lpmz
    mov r22,r20
    ldi r30,lo8(conda)
    ldi r31,hi8(conda)
    add r30,r18
    adc r31,r1
    call lpmz
    mov r23,r20
    dec r23
    ldi r30,lo8(LOOP)
    ldi r31,hi8(LOOP)
    add r30,r17
    adc r31,r1
    ld r21,z
PPm:
    cp r21,r22
    brcs PPm2
    sub r21,r22
    rjmp PPm
PPm2:
    ldi r20,0x00
    cp r21,r23
    brne PPret
    ldi r20,0x01
    ret

; Ereignisse einer Spur pro Tick (r24 = Spur): Ausklingen, Ratchet-Raster, Note-On
trackev:
    mov r17,r24
    ldi r26,lo8(OFF)
    ldi r27,hi8(OFF)
    add r26,r17
    adc r27,r1
    ld r18,x
    tst r18
    breq TEchk
    dec r18
    st x,r18
    brne TEchk
    mov r24,r17
    call noteoff
TEchk:
    ldi r26,lo8(ACT)
    ldi r27,hi8(ACT)
    add r26,r17
    adc r27,r1
    ld r18,x
    tst r18
    brne TEact
    ret
TEact:
    call spdbase
    ldi r26,lo8(TSUB)
    ldi r27,hi8(TSUB)
    add r26,r17
    adc r27,r1
    ld r22,x
    cp r22,r20
    brcs TEin
    ret
TEin:
    ldi r30,lo8(POS)
    ldi r31,hi8(POS)
    add r30,r17
    adc r31,r1
    ld r18,z
    mov r19,r17
    swap r19
    add r19,r18
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    add r26,r19
    adc r27,r1
    ld r18,x
    push r18
    ldi r30,lo8(SPD)
    ldi r31,hi8(SPD)
    add r30,r17
    adc r31,r1
    ld r20,z
    add r20,r20
    add r20,r20
    add r20,r18
    dec r20
    ldi r30,lo8(rint)
    ldi r31,hi8(rint)
    add r30,r20
    adc r31,r1
    call lpmz
    pop r18
    ldi r21,0x00
TEk:
    cp r22,r20
    brcs TEk2
    sub r22,r20
    inc r21
    rjmp TEk
TEk2:
    tst r22
    breq TEk3
    ret
TEk3:
    cp r21,r18
    brcs TEon
    ret
TEon:
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    add r26,r19
    adc r27,r1
    ld r18,x
    call tunenote
    mov r25,r17
    call addoct
    push r18
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    add r26,r19
    adc r27,r1
    ld r18,x
    push r18
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    add r26,r19
    adc r27,r1
    ld r18,x
    call lenticks
    push r18
    mov r24,r17
    call noteoff
    pop r18
    ldi r26,lo8(OFF)
    ldi r27,hi8(OFF)
    add r26,r17
    adc r27,r1
    st x,r18
    pop r20
    pop r22
    ldi r30,lo8(CHN)
    ldi r31,hi8(CHN)
    add r30,r17
    adc r31,r1
    ld r24,z
    push r24
    subi r24,0x70
    push r22
    call SEND3
    pop r22
    pop r21
    tst r24
    breq TEret4
    ldi r26,lo8(LN)
    ldi r27,hi8(LN)
    add r26,r17
    adc r27,r1
    st x,r22
    ldi r26,lo8(LCH)
    ldi r27,hi8(LCH)
    add r26,r17
    adc r27,r1
    st x,r21
TEret4:
    ret

; Längen-Stufe r18 (0..15) -> Ticks r18 (verändert r21,r30,r31)
lenticks:
    andi r18,0x0f
    ldi r30,lo8(lentab)
    ldi r31,hi8(lentab)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r18,z
    sts 0x01ca,r21
    ret

; Note-Off für die letzte Note der Spur r24 (falls vorhanden)
noteoff:
    push r17
    mov r17,r24
    ldi r26,lo8(LN)
    ldi r27,hi8(LN)
    add r26,r17
    adc r27,r1
    ld r22,x
    cpi r22,0xff
    breq NOend
    ldi r30,lo8(LCH)
    ldi r31,hi8(LCH)
    add r30,r17
    adc r31,r1
    ld r24,z
    subi r24,0x80
    ldi r20,0x40
    call SEND3
    tst r24
    breq NOend
    ldi r26,lo8(LN)
    ldi r27,hi8(LN)
    add r26,r17
    adc r27,r1
    ldi r22,0xff
    st x,r22
NOend:
    pop r17
    ret

stopseq:
    in r24,0x02
    tst r24
    breq SPnc
    ldi r24,0xfc
    call SEND3
SPnc:
    out 0x02,r1
    sts OFF,r1
    sts OFF1,r1
    sts OFF2,r1
    sts OFF3,r1
    push r16
    ldi r16,0x00
SPloop:
    mov r24,r16
    call noteoff
    inc r16
    cpi r16,0x04
    brne SPloop
    pop r16
    ldi r26,lo8(MREQ)
    ldi r27,hi8(MREQ)
    ldi r30,lo8(MUTE)
    ldi r31,hi8(MUTE)
    ldi r19,0x04
SPm:
    ld r18,x+
    st z+,r18
    dec r19
    brne SPm
    ret

; Start: FA senden, alle Spuren auf Anfang, Wiedergabe an
seqstart:
    ldi r24,0xfa
    call SEND3
    call posreset
    ldi r24,0x0f
    out 0x00,r24
    ldi r24,TICKS1
    sts 0x3dd5,r24
    ldi r24,0x01
    sts 0x3dda,r24
    out 0x02,r24
    ret

; Grundeinstellungen aller Spuren (beim Einschalten)
trkinit:
    ldi r18,0x00
TIl:
    ldi r26,lo8(SPD)
    ldi r27,hi8(SPD)
    add r26,r18
    adc r27,r1
    ldi r19,SPDDEF
    st x,r19
    ldi r26,lo8(CHN)
    ldi r27,hi8(CHN)
    add r26,r18
    adc r27,r1
    st x,r18
    ldi r26,lo8(LCH)
    ldi r27,hi8(LCH)
    add r26,r18
    adc r27,r1
    st x,r18
    ldi r26,lo8(DIR)
    ldi r27,hi8(DIR)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(MUTE)
    ldi r27,hi8(MUTE)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(MREQ)
    ldi r27,hi8(MREQ)
    add r26,r18
    adc r27,r1
    st x,r1
    inc r18
    cpi r18,0x04
    brne TIl
    sts EDTRK,r1
    ldi r18,0x01
    sts EDPAR,r18
    jmp posreset

; ================================================================ Poti: Taste halten + drehen = Step bearbeiten
potisend:
    call isseq
    tst r25
    brne PSplay
    call isedit
    tst r25
    breq PSorig
    lds r24,0x3a56
    cpi r24,64
    brcc PSorig
    swap r24
    andi r24,0x0f
    sts EDTRK,r24
    jmp 0x136e
PSplay:
    lds r24,0x3a56
    cpi r24,64
    brcs PSseq
    cpi r24,POTSWING
    brne PSn0
    jmp PSswing
PSn0:
    cpi r24,POTSCALE
    brne PSn1
    jmp PSscale
PSn1:
    cpi r24,POTROOT
    brne PSorig
    jmp PSroot
PSorig:
    lds r22,0x2284
    jmp 0x1362
PSseq:
    lds r18,RAWVAL
    mov r19,r24
    andi r19,0xf8
    sts LEDROW,r19
    ldi r20,HOLD
    sts 0x3dd4,r20
    ldi r25,0x02
    lds r20,0x230f
    tst r20
    brne PSgot
    ldi r25,0x06
    lds r20,0x2310
    tst r20
    brne PSgot
    ldi r25,0x04
    lds r20,0x2311
    tst r20
    brne PSgot
    ldi r25,0x05
    lds r20,0x2312
    tst r20
    brne PSgot
    ldi r25,0x0c
    lds r20,0x2313
    tst r20
    brne PSgot
    ldi r25,0x0d
    lds r20,0x2314
    tst r20
    brne PSgot
    ldi r25,0x01
PSgot:
    sts 0x3dd8,r25
    cpi r25,0x01
    brne PS2
    mov r20,r18
    cpi r20,0x02
    brcc PSv
    ldi r20,0x00
PSv:
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    rjmp PSstore
PS2:
    cpi r25,0x02
    brne PS4
    push r24
    call tunenote
    pop r24
    mov r25,r24
    swap r25
    andi r25,0x0f
    call addoct
    sts 0x3dd9,r18
    lds r18,RAWVAL
    mov r20,r18
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    add r26,r24
    adc r27,r1
    st x,r20
    jmp 0x136e
PS4:
    cpi r25,0x04
    brne PS5
    ldi r20,NPROB
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    ldi r26,lo8(P)
    ldi r27,hi8(P)
    rjmp PSstore
PS5:
    cpi r25,0x05
    brne PS9
    mov r20,r18
    swap r20
    lsr r20
    andi r20,0x03
    inc r20
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    rjmp PSstore
PS9:
    cpi r25,0x0c
    breq PS9go
    cpi r25,0x0d
    breq PS9c
    jmp PS6
PS9c:
    jmp PSclr
PS9go:
    ldi r20,0x00
    cpi r18,64
    brcs PSmu
    ldi r20,0x01
PSmu:
    mov r21,r24
    swap r21
    andi r21,0x0f
    ldi r26,lo8(MREQ)
    ldi r27,hi8(MREQ)
    add r26,r21
    adc r27,r1
    st x,r20
    in r19,0x02
    tst r19
    brne PSmu2
    ldi r26,lo8(MUTE)
    ldi r27,hi8(MUTE)
    add r26,r21
    adc r27,r1
    st x,r20
PSmu2:
    sts 0x3dd9,r21
    jmp 0x136e
PS9x:
    cpi r25,0x0b
    brne PS9b
    mov r20,r18
    lsr r20
    lsr r20
    lsr r20
    inc r20
    mov r21,r24
    swap r21
    andi r21,0x0f
    ldi r26,lo8(TLEN)
    ldi r27,hi8(TLEN)
    add r26,r21
    adc r27,r1
    st x,r20
    sts 0x3dd9,r20
    jmp 0x136e
PS9b:
    cpi r25,0x09
    brne PS6
    ldi r20,0x07
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    mov r21,r24
    swap r21
    andi r21,0x0f
    ldi r26,lo8(OCT)
    ldi r27,hi8(OCT)
    add r26,r21
    adc r27,r1
    st x,r20
    sts 0x3dd9,r20
    jmp 0x136e
PS6:
    mov r20,r18
    lsr r20
    lsr r20
    lsr r20
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    rjmp PSstore
PSscale:
    lds r18,RAWVAL
    ldi r20,0x07
    sts 0x3dd8,r20
    ldi r20,0xff
    sts LEDROW,r20
    ldi r20,HOLD
    sts 0x3dd4,r20
    ldi r20,NSCALES
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    sts SCALE,r20
    sts 0x3dd9,r20
    jmp 0x136e
PSswing:
    lds r18,RAWVAL
    ldi r20,0x0a
    sts 0x3dd8,r20
    ldi r20,0xff
    sts LEDROW,r20
    ldi r20,HOLD
    sts 0x3dd4,r20
    ldi r20,0x07
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    sts SWING,r20
    sts 0x3dd9,r20
    jmp 0x136e
PSroot:
    lds r18,RAWVAL
    ldi r20,0x08
    sts 0x3dd8,r20
    ldi r20,0xff
    sts LEDROW,r20
    ldi r20,HOLD
    sts 0x3dd4,r20
    ldi r20,12
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    sts ROOT,r20
    sts 0x3dd9,r20
    jmp 0x136e
; Taste 6: Spur der Poti-Reihe löschen, sobald das Poti ganz rechts ist
PSclr:
    mov r21,r24
    swap r21
    andi r21,0x0f
    sts 0x3dd9,r21
    cpi r18,120
    brcc PSclgo
    sts CLRF,r1
    jmp 0x136e
PSclgo:
    ldi r20,0x01
    sts CLRF,r20
    mov r22,r21
    swap r22
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    ldi r18,0x00
    call fill16
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    ldi r18,TUNEDEF
    call fill16
    ldi r26,lo8(P)
    ldi r27,hi8(P)
    ldi r18,PROBDEF
    call fill16
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    ldi r18,0x01
    call fill16
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    ldi r18,LENDEF
    call fill16
    jmp 0x136e

; X = Basis, r22 = Offset: 16 Bytes mit r18 füllen
fill16:
    add r26,r22
    adc r27,r1
    ldi r19,16
F16:
    st x+,r18
    dec r19
    brne F16
    ret
PSstore:
    add r26,r24
    adc r27,r1
    st x,r20
    sts 0x3dd9,r20
    jmp 0x136e

; Rohwert des Potis (0..127, vor der Lower/Upper-Umrechnung der Firmware) merken
rawsave:
    sts RAWVAL,r18
    sts 0x3aa7,r18
    ret

; Vor dem Vergleich "Wert geändert?" der Firmware: im SEq-Modus auch auf Änderung des Rohwerts reagieren
rawcmp:
    call isseq
    tst r25
    breq RCorig
    cpi r24,68
    brcc RCorig
    cpi r24,65
    breq RCorig
    ldi r26,lo8(RAWLAST)
    ldi r27,hi8(RAWLAST)
    add r26,r24
    adc r27,r1
    ld r18,x
    lds r19,RAWVAL
    cp r18,r19
    breq RCorig
    st x,r19
    ldi r25,0x00
    jmp 0x135e
RCorig:
    ldi r25,0x00
    lds r20,0x3aa7
    jmp 0x133a

; Poti-Stellung r18 (0..127) -> MIDI-Note r18 in der aktuellen Skala (verändert r0,r1,r20,r21,r30,r31)
tunenote:
    lds r20,SCALE
    ldi r21,128
    mul r20,r21
    ldi r30,lo8(tunetab)
    ldi r31,hi8(tunetab)
    add r30,r0
    adc r31,r1
    clr r1
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r18,z
    sts 0x01ca,r21
    lds r21,ROOT
    add r18,r21
    ret

; Alle Spuren auf "vor Step 1": POS/TSUB = 0xFF, Step- und Durchlaufzähler 0, Pingpong aufwärts
posreset:
    ldi r18,0x00
PRl:
    ldi r19,0xff
    ldi r26,lo8(POS)
    ldi r27,hi8(POS)
    add r26,r18
    adc r27,r1
    st x,r19
    ldi r26,lo8(TSUB)
    ldi r27,hi8(TSUB)
    add r26,r18
    adc r27,r1
    st x,r19
    ldi r26,lo8(SCNT)
    ldi r27,hi8(SCNT)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(LOOP)
    ldi r27,hi8(LOOP)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(PDIR)
    ldi r27,hi8(PDIR)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(ACT)
    ldi r27,hi8(ACT)
    add r26,r18
    adc r27,r1
    st x,r1
    inc r18
    cpi r18,0x04
    brne PRl
    ret

; Note r18 um die Oktave der Spur r25 verschieben (OCT 3 = 0); verändert r20,r26,r27
addoct:
    ldi r26,lo8(OCT)
    ldi r27,hi8(OCT)
    add r26,r25
    adc r27,r1
    ld r20,x
AO:
    cpi r20,0x03
    breq AOret
    brcs AOdn
    subi r18,0xf4
    dec r20
    rjmp AO
AOdn:
    subi r18,12
    inc r20
    rjmp AO
AOret:
    ret

; Tasten-LEDs (in 0x3AC0 nach der LED-Schleife): Steps der zuletzt bewegten Reihe bzw. Lauflicht
ledhook:
    call isseq
    tst r25
    brne LHplay
    call isedit
    tst r25
    breq LHorig
    lds r24,EDPAR
    dec r24
    ldi r30,0xf9
    ldi r31,0x3b
    ldi r21,0x08
    ldi r20,0x00
LHe:
    ldi r19,0x00
    cp r20,r24
    brne LHe2
    ldi r19,0x03
LHe2:
    st z+,r19
    inc r20
    dec r21
    brne LHe
    rjmp LHorig
LHplay:
    lds r24,0x3dd4
    tst r24
    breq LHrun
    lds r24,LEDROW
    cpi r24,0xff
    breq LHrun
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    add r26,r24
    adc r27,r1
    ldi r30,0xf9
    ldi r31,0x3b
    ldi r21,0x08
LHg:
    ld r18,x+
    ldi r19,0x00
    tst r18
    breq LHg2
    ldi r19,0x03
LHg2:
    st z+,r19
    dec r21
    brne LHg
    rjmp LHorig
LHrun:
    in r24,0x02
    tst r24
    breq LHorig
    in r24,0x00
    andi r24,0x07
    ldi r30,0xf9
    ldi r31,0x3b
    ldi r21,0x08
    ldi r20,0x00
LHr:
    ldi r19,0x00
    cp r20,r24
    brne LHr2
    ldi r19,0x03
LHr2:
    st z+,r19
    inc r20
    dec r21
    brne LHr
LHorig:
    sts 0x31a8,r15
    jmp 0x3bfc

; ================================================================ Anzeige
showdisp:
    lds r24,0x3dd8
    cpi r24,0x01
    brne SDsc
    lds r18,0x3dd9
    tst r18
    brne SDvel
    ldi r24,0x5c
    sts 0x2fe6,r24
    ldi r24,0x71
    sts 0x2fe7,r24
    sts 0x2fe8,r24
    sts 0x2fe9,r1
    jmp dispcopy
SDvel:
    ldi r25,0x1c
    rjmp SDw
SDsc:
    cpi r24,0x06
    brne SDrt
    lds r18,0x3dd9
    andi r18,0x0f
    add r18,r18
    ldi r30,lo8(lendisp)
    ldi r31,hi8(lendisp)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r24,z+
    lpm r18,z
    sts 0x01ca,r21
    push r18
    ldi r22,0x01
    call SHOWNUM
    pop r18
    ldi r24,0x38
    sts 0x2fe6,r24
    tst r18
    breq SDl2
    lds r24,0x2fe7
    ori r24,0x80
    sts 0x2fe7,r24
SDl2:
    jmp dispcopy
SDrt:
    cpi r24,0x08
    brne SDsc7
    lds r18,0x3dd9
    add r18,r18
    ldi r30,lo8(rootdisp)
    ldi r31,hi8(rootdisp)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r24,z+
    lpm r18,z
    sts 0x01ca,r21
    tst r18
    breq SDr2
    ori r24,0x80
SDr2:
    sts 0x2fe8,r24
    ldi r24,0x50
    sts 0x2fe6,r24
    ldi r24,0x78
    sts 0x2fe7,r24
    sts 0x2fe9,r1
    jmp dispcopy
SDsc7:
    cpi r24,0x07
    breq SDsc7b
    cpi r24,0x02
    brne SDoc0
    jmp SDnote
SDoc0:
    cpi r24,0x09
    brne SDsw0
    jmp SDoct
SDsw0:
    cpi r24,0x0a
    brne SDpr0
    jmp SDswing
SDpr0:
    cpi r24,0x04
    brne SDmu0
    jmp SDprob
SDmu0:
    cpi r24,0x0c
    brne SDcl0
    jmp SDmute
SDcl0:
    cpi r24,0x0d
    brne SDlp0
    ldi r24,0x39
    sts 0x2fe6,r24
    ldi r24,0x38
    sts 0x2fe7,r24
    ldi r24,0x00
    lds r18,CLRF
    tst r18
    breq SDcl1
    ldi r24,0x50
SDcl1:
    sts 0x2fe8,r24
    lds r24,0x3dd9
    inc r24
    call DIGIT
    sts 0x2fe9,r24
    jmp dispcopy
SDlp0:
    cpi r24,0x0b
    brne SDnum
    lds r24,0x3dd9
    ldi r22,0x01
    call SHOWNUM
    ldi r24,0x38
    sts 0x2fe6,r24
    ldi r24,0x73
    sts 0x2fe7,r24
    jmp dispcopy
SDsc7b:
    lds r18,SCALE
    add r18,r18
    add r18,r18
    ldi r30,lo8(scnames)
    ldi r31,hi8(scnames)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r18,z+
    sts 0x2fe6,r18
    lpm r18,z+
    sts 0x2fe7,r18
    lpm r18,z+
    sts 0x2fe8,r18
    lpm r18,z
    sts 0x2fe9,r18
    sts 0x01ca,r21
    jmp dispcopy
SDnum:
    ldi r25,0x78
    in r18,0x03
    cpi r24,0x02
    brne SD4
    ldi r25,0x54
    lds r18,0x3dd9
SD4:
    cpi r24,0x04
    brne SD5
    ldi r25,0x73
    lds r18,0x3dd9
SD5:
    cpi r24,0x05
    brne SDw
    ldi r25,0x50
    lds r18,0x3dd9
SDw:
    sts 0x2fe6,r25
    mov r24,r18
    ldi r22,0x01
    call SHOWNUM
    jmp dispcopy

; Notenname mit Oktave, z. B. "nC4", "nF.3" (Punkt = Kreuz), MIDI 60 = C4
SDnote:
    lds r18,0x3dd9
    ldi r19,0x00
SDo:
    cpi r18,12
    brcs SDo2
    subi r18,12
    inc r19
    rjmp SDo
SDo2:
    dec r19
    add r18,r18
    ldi r30,lo8(rootdisp)
    ldi r31,hi8(rootdisp)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r24,z+
    lpm r18,z
    sts 0x01ca,r21
    tst r18
    breq SDo3
    ori r24,0x80
SDo3:
    sts 0x2fe7,r24
    ldi r24,0x54
    sts 0x2fe6,r24
    mov r24,r19
    call DIGIT
    sts 0x2fe8,r24
    sts 0x2fe9,r1
    jmp dispcopy

; Oktave der Spur: "oc 0", "oc-2", "oc 3"
SDoct:
    ldi r24,0x5c
    sts 0x2fe6,r24
    ldi r24,0x58
    sts 0x2fe7,r24
    lds r18,0x3dd9
    ldi r19,0x00
    subi r18,0x03
    brcc SDoc2
    neg r18
    ldi r19,0x40
SDoc2:
    sts 0x2fe8,r19
    mov r24,r18
    call DIGIT
    sts 0x2fe9,r24
    jmp dispcopy

; Shuffle: "Sh50" .. "Sh75"
SDswing:
    lds r18,0x3dd9
    ldi r30,lo8(swdisp)
    ldi r31,hi8(swdisp)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r24,z
    sts 0x01ca,r21
    ldi r22,0x01
    call SHOWNUM
    ldi r24,0x6d
    sts 0x2fe6,r24
    ldi r24,0x74
    sts 0x2fe7,r24
    jmp dispcopy

; Wahrscheinlichkeit "P070" bzw. Bedingung "c2-3"
SDprob:
    lds r18,0x3dd9
    cpi r18,0x0a
    brcc SDpc
    inc r18
    ldi r24,0x0a
    mul r18,r24
    mov r24,r0
    clr r1
    ldi r22,0x01
    call SHOWNUM
    ldi r24,0x73
    sts 0x2fe6,r24
    jmp dispcopy
SDpc:
    subi r18,0x0a
    ldi r30,lo8(conda)
    ldi r31,hi8(conda)
    add r30,r18
    adc r31,r1
    call lpmz
    mov r24,r20
    call DIGIT
    sts 0x2fe7,r24
    ldi r30,lo8(condb)
    ldi r31,hi8(condb)
    add r30,r18
    adc r31,r1
    call lpmz
    mov r24,r20
    call DIGIT
    sts 0x2fe9,r24
    ldi r24,0x58
    sts 0x2fe6,r24
    ldi r24,0x40
    sts 0x2fe8,r24
    jmp dispcopy

; Mute der Spur 0x3dd9: "on" / "OFF", Punkt = wartet auf Pattern-Ende
SDmute:
    lds r19,0x3dd9
    ldi r26,lo8(MREQ)
    ldi r27,hi8(MREQ)
    add r26,r19
    adc r27,r1
    ld r18,x
    ldi r26,lo8(MUTE)
    ldi r27,hi8(MUTE)
    add r26,r19
    adc r27,r1
    ld r20,x
    ldi r21,0x00
    cp r18,r20
    breq SDm1
    ldi r21,0x80
SDm1:
    ldi r24,0x5c
    sts 0x2fe6,r24
    tst r18
    brne SDmoff
    ldi r24,0x54
    or r24,r21
    sts 0x2fe7,r24
    sts 0x2fe8,r1
    sts 0x2fe9,r1
    jmp dispcopy
SDmoff:
    ldi r24,0x71
    sts 0x2fe7,r24
    or r24,r21
    sts 0x2fe8,r24
    sts 0x2fe9,r1
    jmp dispcopy

; Textpuffer 0x2FE6..0x2FE9 in den LED-Speicher ab 0x3BF9 umsetzen (wie Firmware bei 0x39B0)
dispcopy:
    ldi r30,0xe6
    ldi r31,0x2f
    ldi r23,0x00
DCdig:
    ld r22,z+
    mov r20,r23
    andi r20,0x02
    subi r20,0xfe
    add r20,r20
    add r20,r20
    add r20,r20
    mov r21,r23
    andi r21,0x01
    add r20,r21
    mov r19,r20
    subi r19,0xf0
    ldi r21,0x01
DCbit:
    cpi r20,0x2f
    breq DCskip
    ldi r18,0x00
    mov r24,r22
    and r24,r21
    breq DCst
    ldi r18,0x03
DCst:
    mov r26,r20
    ldi r27,0x00
    subi r26,0x07
    sbci r27,0xc4
    st x,r18
DCskip:
    add r21,r21
    subi r20,0xfe
    cp r20,r19
    brcs DCbit
    inc r23
    cpi r23,0x04
    brne DCdig
    ret

; ================================================================ Encoder im Spielmodus: Tempo
encw:
    call isseq
    tst r25
    brne Eseq
    lds r24,0x3bf8
    jmp 0x1f7c
Eseq:
    lds r24,0x3bf8
    tst r24
    breq Eret
    sts 0x3bf8,r1
    in r18,0x03
    lds r24,0x213e
    tst r24
    breq Edown
    cpi r18,BPMMAX
    brcc Eset
    inc r18
    rjmp Eset
Edown:
    cpi r18,BPMMIN1
    brcs Eset
    dec r18
Eset:
    out 0x03,r18
    subi r18,BPMMIN
    ldi r30,lo8(pertab)
    ldi r31,hi8(pertab)
    add r30,r18
    adc r31,r1
    add r30,r18
    adc r31,r1
    lds r19,0x01ca
    sts 0x01ca,r1
    lpm r20,z+
    lpm r21,z
    sts 0x01ca,r19
    sts 0x0a36,r20
    sts 0x0a37,r21
    sts 0x3dd8,r1
    ldi r18,0xff
    sts LEDROW,r18
    ldi r18,HOLD
    sts 0x3dd4,r18
Eret:
    ret

; ================================================================ Tasten-Schleife: im SEq-Modus Tasten 1-8 nicht senden
loopend:
    call isseq
    lds r18,0x3a56
    tst r25
    breq LEret
    tst r18
    brne LEret
    ldi r18,0x08
LEret:
    ret

; r25 = 1, wenn SEq aktiv ist und weder Setup- noch Edit-Mode läuft (verändert nur r25)
isseq:
    lds r25,ROUTING
    cpi r25,SEQ
    brne ISno
    lds r25,0x220e
    tst r25
    brne ISno
    lds r25,0x3bf3
    tst r25
    brne ISno
    ldi r25,0x01
    ret
ISno:
    ldi r25,0x00
    ret

; r25 = 1, wenn SEq aktiv ist und die Edit-Seite offen (nicht Setup); verändert nur r25
isedit:
    lds r25,ROUTING
    cpi r25,SEQ
    brne IEno
    lds r25,0x3bf3
    tst r25
    brne IEno
    lds r25,0x220e
    tst r25
    breq IEno
    ldi r25,0x01
    ret
IEno:
    ldi r25,0x00
    ret

; ================================================================ Edit-Seite (statt 0x24E8/0x1686 der Firmware)
seqedit:
    lds r18,ROUTING
    cpi r18,SEQ
    breq SE0
    jmp 0x24e8
SE0:
    ldi r18,0x01
SEb:
    ldi r26,0x0f
    ldi r27,0x22
    add r26,r18
    adc r27,r1
    ld r19,x
    tst r19
    breq SEbn
    st x,r1
    ldi r26,0x0e
    ldi r27,0x23
    add r26,r18
    adc r27,r1
    ld r19,x
    tst r19
    breq SEbn
    cpi r18,0x07
    brne SEb8
    in r19,0x02
    tst r19
    brne SEbn
    push r18
    call seqstart
    pop r18
    rjmp SEbn
SEb8:
    cpi r18,0x08
    brne SEbp
    push r18
    call stopseq
    pop r18
    rjmp SEbn
SEbp:
    sts EDPAR,r18
SEbn:
    inc r18
    cpi r18,0x09
    brne SEb
    lds r24,0x3bf8
    tst r24
    brne SEenc
    ret
SEenc:
    sts 0x3bf8,r1
    lds r25,0x213e
    lds r18,EDPAR
    lds r19,EDTRK
    cpi r18,0x01
    brne SEp2
    ldi r26,lo8(EDTRK)
    ldi r27,hi8(EDTRK)
    ldi r20,0x00
    ldi r21,0x03
    rjmp SEchg
SEp2:
    ldi r20,0x01
    ldi r21,0x10
    ldi r26,lo8(TLEN)
    ldi r27,hi8(TLEN)
    cpi r18,0x02
    breq SEtrk
    ldi r20,0x00
    ldi r21,0x06
    ldi r26,lo8(OCT)
    ldi r27,hi8(OCT)
    cpi r18,0x03
    breq SEtrk
    ldi r26,lo8(SPD)
    ldi r27,hi8(SPD)
    cpi r18,0x04
    breq SEtrk
    ldi r21,0x0f
    ldi r26,lo8(CHN)
    ldi r27,hi8(CHN)
    cpi r18,0x05
    breq SEtrk
    ldi r21,0x03
    ldi r26,lo8(DIR)
    ldi r27,hi8(DIR)
    cpi r18,0x06
    breq SEtrk
    ret
SEtrk:
    add r26,r19
    adc r27,r1
SEchg:
    ld r22,x
    tst r25
    breq SEdn
    cp r22,r21
    brcc SEret
    inc r22
    st x,r22
    ret
SEdn:
    cp r20,r22
    brcc SEret
    dec r22
    st x,r22
SEret:
    ret

seqedit2:
    lds r18,ROUTING
    cpi r18,SEQ
    breq SE2r
    jmp 0x1686
SE2r:
    ret

; Anzeige der Edit-Seite (in 0x3AC0); ohne SEq wie Firmware: Seite 7 anzeigen
edrend:
    lds r18,ROUTING
    cpi r18,SEQ
    breq ERseq
    ldi r22,0x07
    call 0x2fa6
    jmp 0x3e6a
ERseq:
    call edshow
    jmp 0x3e6a

edshow:
    lds r18,EDPAR
    lds r19,EDTRK
    cpi r18,0x01
    brne ES2
    ldi r24,0x78
    sts 0x2fe6,r24
    ldi r24,0x50
    sts 0x2fe7,r24
    sts 0x2fe8,r1
    mov r24,r19
    inc r24
    call DIGIT
    sts 0x2fe9,r24
    jmp dispcopy
ES2:
    cpi r18,0x02
    brne ES3
    ldi r26,lo8(TLEN)
    ldi r27,hi8(TLEN)
    add r26,r19
    adc r27,r1
    ld r24,x
    ldi r22,0x01
    call SHOWNUM
    ldi r24,0x38
    sts 0x2fe6,r24
    ldi r24,0x73
    sts 0x2fe7,r24
    jmp dispcopy
ES3:
    cpi r18,0x03
    brne ES4
    ldi r26,lo8(OCT)
    ldi r27,hi8(OCT)
    add r26,r19
    adc r27,r1
    ld r24,x
    sts 0x3dd9,r24
    jmp SDoct
ES4:
    cpi r18,0x04
    brne ES5
    ldi r26,lo8(SPD)
    ldi r27,hi8(SPD)
    add r26,r19
    adc r27,r1
    ld r18,x
    add r18,r18
    ldi r30,lo8(spdd)
    ldi r31,hi8(spdd)
    add r30,r18
    adc r31,r1
    call lpmz
    mov r24,r20
    call DIGIT
    sts 0x2fe7,r24
    adiw r30,1
    call lpmz
    mov r24,r20
    call DIGIT
    sts 0x2fe9,r24
    sts 0x2fe6,r1
    ldi r24,0x40
    sts 0x2fe8,r24
    jmp dispcopy
ES5:
    cpi r18,0x05
    brne ES6
    ldi r26,lo8(CHN)
    ldi r27,hi8(CHN)
    add r26,r19
    adc r27,r1
    ld r24,x
    inc r24
    ldi r22,0x01
    call SHOWNUM
    ldi r24,0x39
    sts 0x2fe6,r24
    ldi r24,0x74
    sts 0x2fe7,r24
    jmp dispcopy
ES6:
    ldi r26,lo8(DIR)
    ldi r27,hi8(DIR)
    add r26,r19
    adc r27,r1
    ld r18,x
    add r18,r18
    add r18,r18
    ldi r30,lo8(dirn)
    ldi r31,hi8(dirn)
    add r30,r18
    adc r31,r1
    lds r21,0x01ca
    sts 0x01ca,r1
    lpm r24,z+
    sts 0x2fe6,r24
    lpm r24,z+
    sts 0x2fe7,r24
    lpm r24,z+
    sts 0x2fe8,r24
    lpm r24,z
    sts 0x2fe9,r24
    sts 0x01ca,r21
    jmp dispcopy

; ================================================================ Setup Taste 2: Routing-Auswahl mit "SEq"
rinc:
    lds r24,ROUTING
    cpi r24,SEQ
    brcc RIret
    ldi r25,0x01
    cpi r24,0x02
    breq RI2
    cpi r24,0x06
    brne RI1
RI2:
    ldi r25,0x02
RI1:
    sts 0x3aa7,r25
    add r24,r25
    sts ROUTING,r24
RIret:
    ret

rdec:
    lds r24,ROUTING
    tst r24
    breq RDret
    ldi r25,0x01
    cpi r24,0x04
    breq RD2
    cpi r24,SEQ
    brne RD1
RD2:
    ldi r25,0x02
RD1:
    sts 0x3aa7,r25
    sub r24,r25
    sts ROUTING,r24
RDret:
    ret

rdisp:
    lds r24,ROUTING
    cpi r24,SEQ
    brne RDnorm
    ldi r24,0x6d
    sts 0x2fe6,r24
    ldi r24,0x79
    sts 0x2fe7,r24
    ldi r24,0x67
    sts 0x2fe8,r24
    sts 0x2fe9,r1
    jmp 0x3a18
RDnorm:
    ldi r24,0x50
    sts 0x2fe6,r24
    ldi r24,0x5c
    sts 0x2fe7,r24
    ldi r24,0x1c
    sts 0x2fe8,r24
    lds r24,ROUTING
    call DIGIT
    sts 0x2fe9,r24
    jmp 0x3a18

; TCE0-Überlauf: nur Ticks zählen (Hauptschleife arbeitet sie nach)
tce0isr:
    push r24
    in r24,0x3f
    push r24
    lds r24,0x3de0
    inc r24
    sts 0x3de0,r24
    pop r24
    out 0x3f,r24
    pop r24
    reti

; ================================================================ EEPROM
; Abbild-Offset r24:r25 -> X = RAM-Adresse, r22 = Minimum, r23 = Maximum
; (verändert r19,r20,r24,r25,r30,r31)
imgptr:
    ldi r30,lo8(eetab)
    ldi r31,hi8(eetab)
    lds r19,0x01ca
    sts 0x01ca,r1
IPl:
    lpm r26,z+
    lpm r27,z+
    lpm r20,z+
    lpm r22,z+
    lpm r23,z+
    tst r25
    brne IPskip
    cp r24,r20
    brcs IPfound
IPskip:
    sub r24,r20
    sbci r25,0x00
    rjmp IPl
IPfound:
    add r26,r24
    adc r27,r1
    sts 0x01ca,r19
    ret

; Abbild-Byte r24:r25 aus dem RAM -> r18 (r24,r25 bleiben)
eeram:
    push r24
    push r25
    call imgptr
    ld r18,x
    pop r25
    pop r24
    ret

; Beim Einschalten: gültiges Abbild aus dem EEPROM übernehmen (Werte begrenzt)
eeload:
    push r28
    push r29
EL0:
    lds r24,0x01cf
    sbrc r24,7
    rjmp EL0
    lds r24,0x01cc
    ori r24,0x08
    sts 0x01cc,r24
    lds r24,EEMAGA
    cpi r24,MAG0
    brne ELx
    lds r24,EEMAGB
    cpi r24,MAG1
    brne ELx
    clr r28
    clr r29
ELl:
    mov r24,r28
    mov r25,r29
    call imgptr
    mov r30,r28
    mov r31,r29
    ldi r20,lo8(EEMAP)
    ldi r21,hi8(EEMAP)
    add r30,r20
    adc r31,r21
    ld r18,z
    cp r18,r22
    brcc ELc1
    mov r18,r22
ELc1:
    cp r23,r18
    brcc ELc2
    mov r18,r23
ELc2:
    st x,r18
    adiw r28,1
    cpi r28,lo8(EESIZE)
    ldi r24,hi8(EESIZE)
    cpc r29,r24
    brne ELl
    ldi r26,lo8(MREQ)
    ldi r27,hi8(MREQ)
    ldi r30,lo8(MUTE)
    ldi r31,hi8(MUTE)
    ldi r19,0x04
ELm:
    ld r18,x+
    st z+,r18
    dec r19
    brne ELm
    in r18,0x03
    subi r18,BPMMIN
    ldi r30,lo8(pertab)
    ldi r31,hi8(pertab)
    add r30,r18
    adc r31,r1
    add r30,r18
    adc r31,r1
    lds r19,0x01ca
    sts 0x01ca,r1
    lpm r20,z+
    lpm r21,z
    sts 0x01ca,r19
    sts 0x0a26,r20
    sts 0x0a27,r21
ELx:
    pop r29
    pop r28
    ret

; Pro Tick: eine EEPROM-Seite (32 Byte) prüfen. Geschrieben wird nur, wenn sie sich vom
; EEPROM unterscheidet und seit dem letzten Durchlauf (~2 s) unverändert ist.
eetick:
    lds r24,EEWAIT
    tst r24
    breq ETgo
    dec r24
    sts EEWAIT,r24
    ret
ETgo:
    lds r24,0x01cf
    sbrc r24,7
    ret
    push r15
    push r16
    push r17
    push r28
    push r29
    lds r24,0x01cc
    ori r24,0x08
    sts 0x01cc,r24
    lds r17,EEPG
    ldi r24,32
    mul r17,r24
    mov r28,r0
    mov r29,r1
    clr r1
    clr r16
    clr r15
ETl:
    mov r24,r28
    mov r25,r29
    call eeram
    add r16,r16
    adc r16,r1
    add r16,r18
    mov r30,r28
    mov r31,r29
    ldi r20,lo8(EEMAP)
    ldi r21,hi8(EEMAP)
    add r30,r20
    adc r31,r21
    ld r19,z
    cp r19,r18
    breq ETsame
    inc r15
ETsame:
    adiw r28,1
    cpi r28,lo8(EESIZE)
    ldi r24,hi8(EESIZE)
    cpc r29,r24
    breq ETend
    mov r24,r28
    andi r24,0x1f
    brne ETl
ETend:
    ldi r26,lo8(EESUM)
    ldi r27,hi8(EESUM)
    add r26,r17
    adc r27,r1
    ld r24,x
    st x,r16
    cp r24,r16
    brne ETnext
    tst r15
    breq ETnext
    mov r24,r17
    call eewrpage
ETnext:
    inc r17
    cpi r17,EENPG
    brcs ETst
    clr r17
    ldi r24,EEPAUSE
    sts EEWAIT,r24
ETst:
    sts EEPG,r17
    pop r29
    pop r28
    pop r17
    pop r16
    pop r15
    ret

; Seite r24 komplett in den Seitenpuffer laden und mit Löschen+Schreiben starten (wartet nicht)
eewrpage:
    push r16
    push r17
    push r28
    push r29
    ldi r25,32
    mul r24,r25
    mov r28,r0
    mov r29,r1
    clr r1
    lds r24,0x01cc
    andi r24,0xf7
    sts 0x01cc,r24
    lds r24,0x01cf
    sbrs r24,1
    rjmp EWld
    in r16,0x3f
    cli
    lds r17,0x01ca
    ldi r24,0x36
    sts 0x01ca,r24
    ldi r24,0xd8
    ldi r25,0x01
    out 0x34,r24
    sts 0x01cb,r25
    sts 0x01ca,r17
    out 0x3f,r16
EWb:
    lds r24,0x01cf
    sbrc r24,7
    rjmp EWb
EWld:
    ldi r17,32
EWl:
    mov r24,r28
    mov r25,r29
    ldi r18,0xff
    cpi r24,lo8(EESIZE)
    ldi r19,hi8(EESIZE)
    cpc r25,r19
    brcc EWff
    call eeram
EWff:
    ldi r20,lo8(EEBASE)
    ldi r21,hi8(EEBASE)
    add r24,r20
    adc r25,r21
    in r16,0x3f
    cli
    lds r19,0x01ca
    ldi r20,0x33
    sts 0x01ca,r20
    sts 0x01c0,r24
    sts 0x01c1,r25
    sts 0x01c2,r1
    sts 0x01c4,r18
    sts 0x01ca,r19
    out 0x3f,r16
    adiw r28,1
    dec r17
    brne EWl
    in r16,0x3f
    cli
    ldi r24,0x35
    sts 0x01ca,r24
    ldi r24,0xd8
    ldi r25,0x01
    out 0x34,r24
    sts 0x01cb,r25
    out 0x3f,r16
    pop r29
    pop r28
    pop r17
    pop r16
    ret

eetab:
    .byte EETAB
pertab:
    .byte PERTAB
scnames:
    .byte SCNAMES
tunetab:
    .byte TUNETAB
lentab:
    .byte LENTAB
lendisp:
    .byte LENDISP
rootdisp:
    .byte ROOTDISP
swdisp:
    .byte SWDISP
spdt:
    .byte TSPDT
swt:
    .byte TSWT
rint:
    .byte TRINT
pthr:
    .byte TPTHR
conda:
    .byte TCONDA
condb:
    .byte TCONDB
spdd:
    .byte TSPDD
dirn:
    .byte TDIRN
"""


def per(bpm):
    """TCE0, Vorteiler 64: 500 kHz; 12 Ticks pro 16tel (15/BPM s) -> PER = 7500000/(12*BPM) - 1."""
    return 7500000 // (TICKS * bpm) - 1


def main(src, dst):
    self_test()
    hdr, img = decode(open(src, 'rb').read())
    img = bytearray(img)
    assert len(img) == BASE, 'unerwartete Abbildlänge'
    for adr, orig, _ in PATCHES:
        got = img[adr:adr + len(bytes.fromhex(orig))].hex(' ')
        assert got == orig, 'Original an 0x%04X ist %s, erwartet %s' % (adr, got, orig)

    pertab = []
    for b in range(BPM_MIN, BPM_MAX + 1):
        p = per(b)
        assert 0 < p <= 0xFFFF
        pertab += [p & 0xFF, p >> 8]
    consts = dict(
        SEND3=0xA9A, SHOWNUM=0x2F50, DIGIT=0x2E08, ROUTING=0x2218, SEQ=8, HOLD=HOLD,
        TICKS=TICKS, TICKS1=TICKS - 1,
        BPMSTART=BPM_START, BPMMIN=BPM_MIN, BPMMIN1=BPM_MIN + 1, BPMMAX=BPM_MAX,
        PERLO=per(BPM_START) & 0xFF, PERHI=per(BPM_START) >> 8, PERTAB=', '.join(map(str, pertab)),
        G4=RAM['G'] + 4, G8=RAM['G'] + 8, G12=RAM['G'] + 12,
        LN1=RAM['LN'] + 1, LN2=RAM['LN'] + 2, LN3=RAM['LN'] + 3,
        SPD=0x3E60, CHN=0x3E64, DIR=0x3E68, TSUB=0x3E6C, TPAR=0x3E70, PDIR=0x3E74, SCNT=0x3E78,
        LOOP=0x3E7C, MUTE=0x3E80, MREQ=0x3E84, LCH=0x3E88, EDTRK=0x3E8C, EDPAR=0x3E8D,
        SPDDEF=SPD_DEFAULT, PROBDEF=PROB_DEFAULT, NPROB=NPROB,
        **{'T' + k: ', '.join(map(str, v)) for k, v in seqtables().items()},
        RAWVAL=0x3DF6, RAWLAST=0x3E10, POS=0x3DEE, TLEN=0x3DF2, TLEN1=0x3DF3, TLEN2=0x3DF4, TLEN3=0x3DF5,
        SWING=0x3DED, POTSWING=64, SWDISP='50, 54, 58, 62, 67, 71, 75',
        OCT=0x3DE9, OCT1=0x3DEA, OCT2=0x3DEB, OCT3=0x3DEC,
        POTSCALE=POT_SCALE, POTROOT=POT_ROOT, ROOT=0x3DE8, LENDEF=LEN_DEFAULT,
        OFF1=RAM['OFF'] + 1, OFF2=RAM['OFF'] + 2, OFF3=RAM['OFF'] + 3,
        LENTAB=', '.join(str(t) for t, _, _ in LENGTHS),
        LENDISP=', '.join('%d, %d' % (d, p) for _, d, p in LENGTHS),
        ROOTDISP=', '.join('%d, %d' % r for r in ROOTS),
        TUNEDEF=TUNE_DEFAULT, NSCALES=len(SCALES), SCALE=0x3DE2, LEDROW=0x3DE3,
        V4=RAM['V'] + 4, V8=RAM['V'] + 8, V12=RAM['V'] + 12,
        SCNAMES=', '.join(str(c) for n, _ in SCALES for c in n),
        TUNETAB=', '.join(map(str, tunetable())),
        ACT1=RAM['ACT'] + 1, ACT2=RAM['ACT'] + 2, ACT3=RAM['ACT'] + 3,
        EEBASE=EEBASE, EEMAP=0x1000 + EEBASE, EESIZE=EESIZE, EENPG=EENPG, EEPAUSE=EEPAUSE,
        EEMAGA=0x1000 + EEBASE + EESIZE - 2, EEMAGB=0x1000 + EEBASE + EESIZE - 1,
        MAG0=MAGIC[0], MAG1=MAGIC[1], MAGIC=0x3E04, MAGIC1=0x3E05, CLRF=0x3E06,
        EEPG=0x3DF7, EEWAIT=0x3E03, EESUM=0x3DF8,
        EETAB=', '.join('%d, %d, %d, %d, %d' % (a & 0xFF, a >> 8, n, lo, hi) for a, n, lo, hi in EEREGIONS),
        **RAM)
    assert EENPG <= 11 and EEBASE + EENPG * 32 <= 0x800
    code, labels = assemble(ASM, BASE, consts)
    print('Neuer Code + Tabellen: %d Bytes ab 0x%04X' % (len(code), BASE))

    for adr, orig, line in PATCHES:
        op, _, args = line.partition(' ')
        new = encode_line(op, args, adr, labels)
        assert len(new) == len(bytes.fromhex(orig))
        img[adr:adr + len(new)] = new

    img += code
    img += b'\xff' * (-len(img) % 256)
    open(dst, 'wb').write(encode(bytes(img), hdr))
    print('geschrieben:', dst, '(%d Seiten)' % (len(img) // 256))
    return labels


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
