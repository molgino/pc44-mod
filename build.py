#!/usr/bin/env python3
"""PC44-Sequencer v26: A/B-Patterns mit bar-quantisiertem Wechsel.

  python build.py PC44_V0101.syx PC44_seq.syx

Spielmodus (Start direkt in "SEq"):
  Poti-Reihen 1+2 = Spur 1, 3+4 = Spur 2, 5+6 = Spur 3, 7+8 = Spur 4 (je 16 Steps)
  Poti allein:            Velocity, ganz links = Step aus          "u100" / "oFF"
  Taste 1 + Poti:         Tonhöhe in der Skala                     "nC4", "nF.3"
  Taste 2 + Poti:         Notenlänge 0.08..16 Steps                "L0.50" / "L004"
  Taste 3 + Poti:         Wahrscheinlichkeit 10..100 %, dann Bedingung 1:2..8:8   "P070" / "c2-3"
  Taste 4 + Poti:         Ratchet 1..4 "r002"; in Chord-Spuren Akkordart  "tri", "SuS2", "7th" ...
  Taste 5 + Poti:         Nudge: Step -6..+6 Zwölftel eines Steps früher/später   "nd-3" / "nd 0" / "nd 3"
  Snap (Poti-Modus der Firmware): Wert wird erst übernommen, wenn das Poti den aktuellen Wert des Steps überfährt
  Lock halten oder kurz antippen: Ctrl All; Poti verschiebt den Parameter der aktiven Steps relativ
  Taste 6 + Poti:         Spur löschen: Poti einer Spur ganz nach rechts  "CL 1" -> "CLr1"
  Taste 7 / 8:            Start (FA) / Stopp (FC), Clock nur während der Wiedergabe
  Grosse Potis:           Velocity-Trim der Spuren 1–4; bei null verstummt die Spur
  Shift + Poti 65/66:     Grundton / Skala des Edit-Patterns
  Encoder:                Tempo 30..250 BPM ("t120"), doppelter Druck wechselt A/B
Edit-Seite (Shift + Edit im SEq-Modus):
  Poti einer Spur bewegen = Spur wählen;  Taste 1..6 = Parameter wählen, Encoder = Wert
  1 Spur "tr 1"   2 Länge "LP16"   3 Oktave "oc 0"   4 Speed "1-8".."2-1"   5 Kanal "Ch01"   6 Richtung "For/rEu/PinG/rnd"
  7 Modus "nOtE" / "Chrd" / "PAd"
  Encoder drücken und drehen = Swing.
  Taste 8 = Start/Stopp umschalten. Tasten-LED zeigt den gewählten Parameter.
Externe Clock: kommt MIDI-Clock (USB oder DIN), läuft der Sequencer synchron dazu,
  Start/Continue/Stop werden befolgt, Encoder zeigt "E120" (gemessen). Ohne Clock: interner Takt.
Bedingung A:B = Step spielt nur im A-ten von je B Durchläufen der Spur.
Shift + Taste 1/2: A/B bearbeiten, 3: wechseln, 4: kopieren, 5: speichern, 6: Ctrl All rückgängig.
Gesichert: alle Steps, Spur-Einstellungen und gemeinsame Einstellungen.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pc44tool import decode, encode                       # noqa: E402
import monitor
import patterns
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
POT_SCALE, POT_ROOT = 65, 64   # interne Poti-Nummern (0-basiert) der großen Potis
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
MAGIC = (0x53, 20)
EEREGIONS = [  # RAM-Adresse, Länge, Minimum, Maximum, Ersatzwert (ausserhalb -> Ersatzwert)
    (0x3C80, 64, 0, 127, 62),   # N Tonhöhe
    (0x3CC0, 64, 0, 127, 0),    # V Velocity
    (0x3D00, 64, 0, 44, 9),     # P Wahrscheinlichkeit/Bedingung
    (0x3D40, 64, 1, 4, 1),      # R Ratchet
    (0x3D88, 64, 0, 15, 2),     # L Notenlänge
    (0x3DE2, 1, 0, 10, 0),      # Skala
    (0x3DE8, 1, 0, 11, 0),      # Grundton
    (0x3DE9, 4, 0, 6, 3),       # Oktave pro Spur
    (0x3DED, 1, 0, 6, 0),       # Shuffle
    (0x3DF2, 4, 1, 16, 16),     # Pattern-Länge
    (0x3E60, 4, 0, 6, 4),       # Speed
    (0x3E64, 1, 0, 15, 0),      # Kanal Spur 1 (Ersatzwerte wie beim Einschalten: Kanal 1-4)
    (0x3E65, 1, 0, 15, 1),      # Kanal Spur 2
    (0x3E66, 1, 0, 15, 2),      # Kanal Spur 3
    (0x3E67, 1, 0, 15, 3),      # Kanal Spur 4
    (0x3E68, 4, 0, 3, 0),       # Richtung
    (0x3E84, 4, 0, 0, 0),       # reservierte Mute-Bytes
    (0x0003, 1, 30, 250, 120),  # Tempo (GPIOR3)
    (0x3E04, 2, 0, 255, 0),    # Kennung (Offset 348 wie in v20, damit gespeicherte Patterns bleiben)
    (0x3DC8, 4, 0, 2, 0),      # Modus pro Spur (neu in v21)
    (0x3E90, 64, 0, 7, 0),     # Akkordart pro Step (neu in v21)
    (0x3EE0, 64, 0, 12, 6),    # Nudge pro Step, 6 = 0 (neu in v24)
]
EESIZE = sum(r[1] for r in EEREGIONS)
MAGOFF = 348
assert sum(r[1] for r in EEREGIONS[:18]) == MAGOFF


MODENAMES = [(0x54, 0x5c, 0x78, 0x79), (0x39, 0x74, 0x50, 0x5e), (0x73, 0x77, 0x5e, 0x00)]  # nOtE Chrd PAd
CHORDNAMES = [(0x78, 0x50, 0x10, 0), (0x6d, 0x1c, 0x6d, 0x5b), (0x6d, 0x1c, 0x6d, 0x66), (0x07, 0x78, 0x74, 0),
              (0x77, 0x5e, 0x5e, 0x6f), (0x7d, 0x78, 0x74, 0), (0x3f, 0x73, 0x79, 0x54), (0x06, 0x40, 0x6d, 0)]
# Zusatztöne pro Akkordart: Stufen in der Skala, 0x80+n = n Halbtöne über dem Grundton, 0 = keiner
CHORD_SCALE = [(2, 4, 0), (1, 4, 0), (3, 4, 0), (2, 4, 6), (2, 4, 8), (2, 4, 5), (4, 9, 0), (0x87, 0x8C, 0)]
CHORD_CHROM = [(0x84, 0x87, 0), (0x82, 0x87, 0), (0x85, 0x87, 0), (0x84, 0x87, 0x8A), (0x84, 0x87, 0x8E),
               (0x84, 0x87, 0x89), (0x87, 0x90, 0), (0x87, 0x8C, 0)]
PAD_SHIFT = 26            # Pad-Modus: Note = Poti - 26 (Grundstellung 62 -> 36 = C1)
DEGW = 40                 # Breite der Stufentabelle pro Skala


def degtables():
    degt, nt = [], []
    for _, iv in SCALES:
        n = len(iv)
        degt += [12 * (j // n) + iv[j % n] for j in range(DEGW)]
        nt.append(2 * n + 1)
    return degt, nt


NUDGE_DEFAULT = 6         # gespeichert 0..12, 6 = genau auf dem Raster


def nofftab():
    """Verschiebung in Ticks je Speed (Steplänge t) und Betrag 0..6 Zwölftel."""
    out = [int(n * t / 12 + 0.5) for _, _, t in SPEEDS for n in range(7)]
    return out + [0] * (len(out) % 2)


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
    (0x4156, '90 91 07 3a', 'jmp load_seq_routing'),
    (0x5B00, '86 e0', 'ldi r24,0x08'),
    (0x5CA4, '90 91 18 22', 'jmp lock_seq_routing'),
    (0x5CB4, '80 91 18 22', 'jmp lock_seq_routing'),
    (0x5DA8, '80 91 18 22', 'jmp 0x5dba'),
    (0x5E60, '80 91 18 22', 'jmp 0x5e72'),
    (0x5BB2, '80 91 18 22', 'jmp lock_seq_routing'),
    (0x5BCE, '80 91 18 22', 'jmp lock_seq_routing'),
    (0x30E0, '80 e5 80 93', 'jmp rdisp'),
    (0x1F78, '80 91 f8 3b', 'jmp encw'),
    (0x2DE4, '20 91 56 3a', 'call loopend'),
    (0x135E, '60 91 84 22', 'jmp potisend'),
    (0x3C2C, '20 91 e3 2f', 'jmp rendhook'),
    (0x3BF8, 'f0 92 a8 31', 'jmp ledhook'),
    (0x3E9A, '80 91 2f 21', 'call lock_indicator'),
    (0x00BC, '6b c0 00 00', 'jmp tce0isr'),
    (0x1074, '20 93 a7 3a', 'call rawsave'),
    (0x1336, '40 91 a7 3a', 'jmp rawcmp'),
    (0x69B0, '0e 94 74 12', 'call seqedit'),
    (0x69B4, '0e 94 43 0b', 'call seqedit2'),
    (0x3C10, '67 e0 c9 d9', 'jmp edrend'),
    (0x6856, '0e 94 3f 20', 'call init'),
    (0x69CE, '0e 94 60 1d', 'call hook'),
    (0x00C4, '67 c0 00 00', 'jmp tceccaisr'),
    (0x5090, 'c0 91 a0 08', 'call rxc0'),
    (0x4ACE, 'c0 91 a0 09', 'call rxd0'),
    (0x11E8, 'a1 10 04 c0', 'jmp seqpoti'),
    (0x5E20, '81 e0 90 91', 'jmp locktog'),
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
    ldi r18,PERLO
    sts INTPER,r18
    ldi r18,PERHI
    sts INTPER1,r18
    sts EXT,r1
    sts EXTFIRST,r1
    sts EXTCMD,r1
    sts EXTN,r1
    sts EXTSUM,r1
    sts EXTSUM1,r1
    sts EXTTOT,r1
    sts EXTTOT1,r1
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    st x+,r1
    st x+,r1
    st x+,r1
    st x+,r1
    ldi r26,lo8(CT)
    ldi r27,hi8(CT)
    ldi r18,0x00
    call fill64
    ldi r26,lo8(NUDGE)
    ldi r27,hi8(NUDGE)
    ldi r18,NUDGEDEF
    call fill64
    ldi r26,lo8(LNX)
    ldi r27,hi8(LNX)
    ldi r18,0xff
    ldi r19,12
INlx:
    st x+,r18
    dec r19
    brne INlx
    call eeload
    call pattern_init
    MONITOR_INIT_HOOK
    ldi r22,1
    clr r24
    clr r25
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
    call ctrl_update
    tst r25
    brne Hplay
    sts ENC_WINDOW,r1
    rjmp Htick
Hplay:
    call pattern_keys
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
    lds r25,TEMPO_KEY
    sts TEMPO_KEY,r24
    lds r18,0x2283
    tst r18
    breq Hpress
    sts ENC_WINDOW,r1
    rjmp Htick
Hpress:
    tst r24
    breq Htick
    tst r25
    brne Htick
    lds r18,ENC_WINDOW
    tst r18
    breq Htempo
    cpi r18,ENC_DEBOUNCE_LIMIT
    brcc Htick
    sts ENC_WINDOW,r1
    call pattern_request_switch
    rjmp Htick
Htempo:
    ldi r18,ENC_DOUBLE_TICKS
    sts ENC_WINDOW,r18
    sts 0x3dd8,r1
    ldi r24,0xff
    sts LEDROW,r24
    ldi r24,HOLD
    sts 0x3dd4,r24
Htick:
    call extcmd
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
    lds r24,EXT
    tst r24
    brne Hrun
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
    call pattern_tick
Hnext:
    MONITOR_TICK_HOOK
    rjmp Htick
Hdisp:
    call pattern_write_tick
    jmp 0x3ac0

; Display-Aufbau der Firmware (in 0x3AC0, Spielmodus): im SEq-Modus eigene Anzeige statt Wert
rendhook:
    call isseq
    tst r25
    breq RHorig
    lds r24,SAVEPH
    tst r24
    brne RHpattern
    lds r24,0x3dd4
    tst r24
    breq RHpattern
    call showdisp
    jmp 0x3e6a
RHpattern:
    call pattern_display
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

; Spur r24: Sub-Tick weiterzählen. Bei neuem Step: vorheriger <- aktueller <- nächster, dann den
; nächsten Step vorausberechnen (Position, Durchlauf, Wahrscheinlichkeit).
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
    call compnext
    rjmp TSnew
TSa:
    inc r18
    push r18
    call curlen
    pop r18
    cp r18,r20
    brcc TSnw0
    ldi r26,lo8(TSUB)
    ldi r27,hi8(TSUB)
    add r26,r17
    adc r27,r1
    st x,r18
    ret
TSnw0:
    ldi r26,lo8(STF)
    ldi r27,hi8(STF)
    add r26,r17
    adc r27,r1
    st x,r1
TSnew:
    ldi r26,lo8(TSUB)
    ldi r27,hi8(TSUB)
    add r26,r17
    adc r27,r1
    st x,r1
    ldi r30,lo8(TPAR)
    ldi r31,hi8(TPAR)
    add r30,r17
    adc r31,r1
    ld r19,z
    ldi r20,0x01
    eor r19,r20
    st z,r19
    ldi r26,lo8(CPOS)
    ldi r27,hi8(CPOS)
    add r26,r17
    adc r27,r1
    ld r18,x
    ldi r30,lo8(PPOS)
    ldi r31,hi8(PPOS)
    add r30,r17
    adc r31,r1
    st z,r18
    ldi r30,lo8(POS)
    ldi r31,hi8(POS)
    add r30,r17
    adc r31,r1
    ld r18,z
    st x,r18
    ldi r26,lo8(CACT)
    ldi r27,hi8(CACT)
    add r26,r17
    adc r27,r1
    ld r18,x
    ldi r30,lo8(PACT)
    ldi r31,hi8(PACT)
    add r30,r17
    adc r31,r1
    st z,r18
    ldi r30,lo8(ACT)
    ldi r31,hi8(ACT)
    add r30,r17
    adc r31,r1
    ld r18,z
    st x,r18
    ldi r26,lo8(FLG)
    ldi r27,hi8(FLG)
    add r26,r17
    adc r27,r1
    ld r18,x
    andi r18,0xf3
    st x,r18

; nächsten Step der Spur r17 bestimmen -> POS, ACT (Durchlauf zählt beim ersten Step des neuen Durchlaufs)
compnext:
    call advpos
    ldi r30,lo8(SCNT)
    ldi r31,hi8(SCNT)
    add r30,r17
    adc r31,r1
    ld r19,z
    ldi r26,lo8(TLEN)
    ldi r27,hi8(TLEN)
    add r26,r17
    adc r27,r1
    ld r20,x
    cp r19,r20
    brcs TSc1
    ldi r19,0x00
    ldi r26,lo8(LOOP)
    ldi r27,hi8(LOOP)
    add r26,r17
    adc r27,r1
    ld r18,x
    inc r18
    st x,r18
    ldi r26,lo8(FLG)
    ldi r27,hi8(FLG)
    add r26,r17
    adc r27,r1
    ld r18,x
    ori r18,0x01
    st x,r18
    rjmp TSc1b
TSc1:
    ldi r26,lo8(FLG)
    ldi r27,hi8(FLG)
    add r26,r17
    adc r27,r1
    ld r18,x
    andi r18,0xfe
    st x,r18
TSc1b:
    inc r19
    st z,r19
    ldi r20,0x00
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
    ldi r26,lo8(VTRIM)
    ldi r27,hi8(VTRIM)
    add r26,r17
    adc r27,r1
    ld r18,x
    tst r18
    brne TEoff
    ; Retry any Note Off that could not queue when the trim first hit zero.
    mov r24,r17
    jmp trim_silence
TEoff:
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
; --- aktueller Step: d = TSUB - Verschiebung
    ldi r26,lo8(CACT)
    ldi r27,hi8(CACT)
    add r26,r17
    adc r27,r1
    ld r18,x
    tst r18
    breq TEnx
    ldi r26,lo8(CPOS)
    ldi r27,hi8(CPOS)
    call stepof
    call noff
    tst r23
    breq TEc0
    ldi r26,lo8(STF)
    ldi r27,hi8(STF)
    add r26,r17
    adc r27,r1
    ld r20,x
    tst r20
    breq TEc0
    ldi r23,0x00
    ldi r22,0x00
TEc0:
    call tsub
    tst r23
    brne TEc1
    sub r18,r22
    brcs TEnx
    rjmp TEc2
TEc1:
    add r18,r22
TEc2:
    call hitchk
    tst r20
    breq TEnx
    jmp TEon
; --- nächster Step, vorgezogen: ab TSUB = Steplänge - Verschiebung
TEnx:
    ldi r26,lo8(ACT)
    ldi r27,hi8(ACT)
    add r26,r17
    adc r27,r1
    ld r18,x
    tst r18
    breq TEpv
    ldi r26,lo8(POS)
    ldi r27,hi8(POS)
    call stepof
    call noff
    tst r23
    breq TEpv
    push r19
    push r22
    call curlen
    pop r22
    pop r19
    sub r20,r22
    brcs TEpv
    call tsub
    sub r18,r20
    brcs TEpv
    call hitchk
    tst r20
    breq TEpv
    jmp TEon
; --- vorheriger Step, verzögert: d = TSUB + Länge des vorherigen Steps - Verschiebung
TEpv:
    ldi r26,lo8(PACT)
    ldi r27,hi8(PACT)
    add r26,r17
    adc r27,r1
    ld r18,x
    tst r18
    breq TEret0
    ldi r26,lo8(PPOS)
    ldi r27,hi8(PPOS)
    call stepof
    call noff
    tst r23
    brne TEret0
    tst r22
    breq TEret0
    push r19
    push r22
    call prevlen
    pop r22
    pop r19
    sub r20,r22
    brcs TEret0
    call tsub
    add r18,r20
    brcs TEret0
    call hitchk
    tst r20
    breq TEret0
    jmp TEon
TEret0:
    ret

; X = Positions-Feld (POS/CPOS/PPOS): Step-Index der Spur r17 -> r19
stepof:
    add r26,r17
    adc r27,r1
    ld r19,x
    mov r18,r17
    swap r18
    add r19,r18
    ret

; TSUB der Spur r17 -> r18
tsub:
    ldi r26,lo8(TSUB)
    ldi r27,hi8(TSUB)
    add r26,r17
    adc r27,r1
    ld r18,x
    ret

; Nudge von Step r19 (Spur r17) -> r22 = Betrag in Ticks, r23 = 1 wenn früher (verändert r20,r21,r30,r31)
noff:
    ldi r26,lo8(NUDGE)
    ldi r27,hi8(NUDGE)
    add r26,r19
    adc r27,r1
    ld r22,x
    ldi r23,0x00
    subi r22,NUDGEDEF
    brcc NO1
    neg r22
    ldi r23,0x01
NO1:
    ldi r30,lo8(SPD)
    ldi r31,hi8(SPD)
    add r30,r17
    adc r31,r1
    ld r20,z
    ldi r21,0x07
    mul r20,r21
    mov r20,r0
    clr r1
    add r20,r22
    ldi r30,lo8(nofft)
    ldi r31,hi8(nofft)
    add r30,r20
    adc r31,r1
    call lpmz
    mov r22,r20
    ret

; Treffer? d = r18 Ticks seit Beginn von Step r19 (Spur r17): innerhalb der Grundlänge, auf dem Ratchet-Raster
; und weniger als R Wiederholungen -> r20 = 1 (erhält r17, r19)
hitchk:
    mov r22,r18
    call spdbase
    cp r22,r20
    brcc HCno
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    add r26,r19
    adc r27,r1
    ld r18,x
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
    ldi r21,0x00
HCk:
    cp r22,r20
    brcs HCk2
    sub r22,r20
    inc r21
    rjmp HCk
HCk2:
    tst r22
    brne HCno
    cp r21,r18
    brcc HCno
    ldi r20,0x01
    ret
HCno:
    ldi r20,0x00
    ret

; Länge des vorherigen Steps der Spur r17 (andere Shuffle-Parität) -> r20
prevlen:
    ldi r30,lo8(TPAR)
    ldi r31,hi8(TPAR)
    add r30,r17
    adc r31,r1
    ld r18,z
    ldi r20,0x01
    eor r18,r20
    st z,r18
    push r30
    push r31
    push r18
    call curlen
    pop r18
    pop r31
    pop r30
    ldi r21,0x01
    eor r18,r21
    st z,r18
    ret

TEon:
    sts FSTEP,r19
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    add r26,r19
    adc r27,r1
    ld r18,x
    mov r25,r17
    call stepnote
    push r18
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    add r26,r19
    adc r27,r1
    ld r18,x
    tst r18
    brne TEvel
    pop r18
    ret
TEvel:
    call trim_velocity
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
    jmp chordon
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
    push r16
    ldi r16,0x00
NOc:
    mov r18,r17
    add r18,r17
    add r18,r17
    add r18,r16
    ldi r26,lo8(LNX)
    ldi r27,hi8(LNX)
    add r26,r18
    adc r27,r1
    ld r22,x
    cpi r22,0xff
    breq NOcn
    ldi r30,lo8(LCH)
    ldi r31,hi8(LCH)
    add r30,r17
    adc r31,r1
    ld r24,z
    subi r24,0x80
    ldi r20,0x40
    call SEND3
    tst r24
    breq NOcn
    mov r18,r17
    add r18,r17
    add r18,r17
    add r18,r16
    ldi r26,lo8(LNX)
    ldi r27,hi8(LNX)
    add r26,r18
    adc r27,r1
    ldi r22,0xff
    st x,r22
NOcn:
    inc r16
    cpi r16,0x03
    brne NOc
    pop r16
    pop r17
    ret

stopseq:
    in r24,0x02
    tst r24
    breq SPnc
    lds r24,EXT
    tst r24
    brne SPnc
    ldi r24,0xfc
    call SEND3
SPnc:
    out 0x02,r1
    jmp flushnotes

flushnotes:
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
    ret

; Start: FA senden, alle Spuren auf Anfang, Wiedergabe an
seqstart:
    lds r24,EXT
    tst r24
    brne SSq
    ldi r24,0xfa
    call SEND3
SSq:
    sts BARPOS,r1
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
    inc r18
    cpi r18,0x04
    brne TIl
    sts EDTRK,r1
    ldi r18,0x01
    sts EDPAR,r18
    jmp posreset

; ================================================================ Poti: Taste halten + drehen = Step bearbeiten
potisend:
    ; The stock fallback uses the same raw history and pickup as the
    ; early scanner hook. Never consume a movement before Ctrl All sees it.
    call isseq
    tst r25
    breq PSed1
    lds r24,0x2b1a
    cpi r24,2
    brne PSmode
    lds r26,0x3a56
    ldi r27,0
    subi r26,0x7b
    sbci r27,0xdd
    ld r24,x
PSmode:
    jmp SQ2
PSed1:
    call isedit
    tst r25
    brne PSed
    rjmp PSorig
PSed:
    lds r24,0x3a56
    cpi r24,64
    brcs PSedtrack
    jmp PStrim
PSedtrack:
    swap r24
    andi r24,0x0f
    sts EDTRK,r24
    jmp PSend
PSplay:
    lds r24,0x3a56
    cpi r24,64
    brcs PSeditable
    lds r20,0x2283
    tst r20
    brne PSeditable
    jmp PStrim
PSeditable:
    lds r20,SAVEPH
    tst r20
    breq PSroute
    cpi r20,PPROMOTE
    brcc PSroute
    jmp PSend
PSroute:
    lds r20,0x2283
    tst r20
    brne PSglobals
    push r24
    call ctrl_active
    mov r20,r24
    pop r24
    tst r20
    breq PSseq
    jmp PSall
PSglobals:
    cpi r24,POTROOT
    brne PSn0
    jmp PSroot
PSn0:
    cpi r24,POTSCALE
    brne PSn1
    jmp PSscale
PSn1:
    jmp PSend
PSorig:
    lds r22,0x2284
    jmp 0x1362
PSseq:
    lds r18,RAWVAL
    mov r19,r24
    andi r19,0xf8
    sts LEDROW,r19
    sts LASTROW,r19
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
    ldi r25,0x0f
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
    call snapgate
    tst r19
    brne PSgo
    jmp PSend
PSgo:
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
    mov r25,r24
    swap r25
    andi r25,0x0f
    push r24
    call stepnote
    pop r24
    sts 0x3dd9,r18
    lds r18,RAWVAL
    mov r20,r18
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    add r26,r24
    adc r27,r1
    st x,r20
    MONITOR_STEP_HOOK
    jmp PSend
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
    breq PS5a
    jmp PS9
PS5a:
    mov r21,r24
    swap r21
    andi r21,0x0f
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    add r26,r21
    adc r27,r1
    ld r20,x
    cpi r20,0x01
    brne PS5r
    ldi r20,0x0e
    sts 0x3dd8,r20
    mov r20,r18
    swap r20
    andi r20,0x07
    ldi r26,lo8(CT)
    ldi r27,hi8(CT)
    jmp PSstore
PS5r:
    mov r20,r18
    swap r20
    lsr r20
    andi r20,0x03
    inc r20
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    rjmp PSstore
PS9:
    cpi r25,0x0d
    breq PS9c
    cpi r25,0x0f
    breq PS9n
    jmp PS6
PS9c:
    jmp PSclr
PS9n:
    ldi r20,13
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    ldi r26,lo8(NUDGE)
    ldi r27,hi8(NUDGE)
    jmp PSstore
PS6:
    mov r20,r18
    lsr r20
    lsr r20
    lsr r20
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    rjmp PSstore
PStrim:
    subi r24,64
    lds r18,RAWVAL
    MONITOR_TRIM_HOOK
    call trim_store
    lds r18,RAWVAL
    sts 0x3dd9,r18
    ldi r20,0x10
    sts 0x3dd8,r20
    ldi r20,0xff
    sts LEDROW,r20
    ldi r20,HOLD
    sts 0x3dd4,r20
    jmp PSend
PSscale:
    lds r18,RAWVAL
    ldi r20,0x07
    sts 0x3dd8,r20
    ldi r20,0xff
    sts LEDROW,r20
    ldi r20,HOLD
    sts 0x3dd4,r20
    ldi r25,0x07
    call snapgate
    tst r19
    brne PSscaleg
    jmp PSend
PSscaleg:
    ldi r20,NSCALES
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    sts SCALE,r20
    sts 0x3dd9,r20
    MONITOR_HEADER_HOOK
    jmp PSend
PSroot:
    lds r18,RAWVAL
    ldi r20,0x08
    sts 0x3dd8,r20
    ldi r20,0xff
    sts LEDROW,r20
    ldi r20,HOLD
    sts 0x3dd4,r20
    ldi r25,0x08
    call snapgate
    tst r19
    brne PSrootg
    jmp PSend
PSrootg:
    ldi r20,12
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    sts ROOT,r20
    sts 0x3dd9,r20
    MONITOR_HEADER_HOOK
    jmp PSend
; Taste 6: Spur der Poti-Reihe löschen, sobald das Poti ganz rechts ist
PSclr:
    mov r21,r24
    swap r21
    andi r21,0x0f
    sts 0x3dd9,r21
    cpi r18,120
    brcc PSclgo
    sts CLRF,r1
    jmp PSend
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
    ldi r26,lo8(CT)
    ldi r27,hi8(CT)
    ldi r18,0x00
    call fill16
    ldi r26,lo8(NUDGE)
    ldi r27,hi8(NUDGE)
    ldi r18,NUDGEDEF
    call fill16
    MONITOR_CLEAR_HOOK
    jmp PSend

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
    MONITOR_STEP_HOOK
    jmp PSend

PSend:
    jmp 0x1466

; ================================================================ Ctrl all (Lock gehalten)
; Poti r24 einer Spur: Parameter (Taste 1-5, sonst Velocity) aller aktiven Steps dieser Spur um die
; Poti-Bewegung verschieben, an den Grenzen begrenzen. Ausgeschaltete Steps bleiben unverändert.
PSall:
    ; A turn during a held Lock gesture keeps the previous latch on release.
    lds r20,0x3a57
    tst r20
    breq PAselect
    lds r20,CTRLSTATE
    ori r20,6
    sts CTRLSTATE,r20
PAselect:
    mov r21,r24
    ldi r25,0x01
    lds r20,0x230f
    tst r20
    breq PA2
    ldi r25,0x02
    rjmp PAm
PA2:
    lds r20,0x2310
    tst r20
    breq PA3
    ldi r25,0x06
    rjmp PAm
PA3:
    lds r20,0x2311
    tst r20
    breq PA4
    ldi r25,0x04
    rjmp PAm
PA4:
    lds r20,0x2312
    tst r20
    breq PA5
    ldi r25,0x05
    rjmp PAm
PA5:
    lds r20,0x2313
    tst r20
    breq PA6
    ldi r25,0x0f
    rjmp PAm
PA6:
    lds r20,0x2314
    tst r20
    breq PAm
    jmp PSend
PAm:
    cpi r25,0x05
    brne PAm2
    mov r20,r21
    swap r20
    andi r20,0x0f
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    add r26,r20
    adc r27,r1
    ld r20,x
    cpi r20,0x01
    brne PAm2
    ldi r25,0x0e
PAm2:
    sts 0x3dd8,r25
    ldi r20,HOLD
    sts 0x3dd4,r20
    mov r20,r21
    andi r20,0xf8
    sts LEDROW,r20
    sts LASTROW,r20
    mov r23,r25
    cpi r23,0x01
    brne PAq0
    ldi r23,0x02
PAq0:
    lds r24,RAWVAL
    call quant
    mov r18,r24
    lds r24,PREV
    cpi r24,0xff
    brne PAq1
    mov r24,r18
    rjmp PAq2
PAq1:
    call quant
PAq2:
    ldi r19,0x00
    sub r18,r24
    brcc PAb
    neg r18
    ldi r19,0x01
PAb:
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    ldi r22,0x01
    ldi r23,127
    cpi r25,0x01
    breq PAgo
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    ldi r22,0x00
    cpi r25,0x02
    breq PAgo
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    ldi r23,15
    cpi r25,0x06
    breq PAgo
    ldi r26,lo8(P)
    ldi r27,hi8(P)
    ldi r23,NPROBMAX
    cpi r25,0x04
    breq PAgo
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    ldi r22,0x01
    ldi r23,0x04
    cpi r25,0x05
    breq PAgo
    ldi r26,lo8(CT)
    ldi r27,hi8(CT)
    ldi r22,0x00
    ldi r23,0x07
    cpi r25,0x0e
    breq PAgo
    ldi r26,lo8(NUDGE)
    ldi r27,hi8(NUDGE)
    ldi r23,12
PAgo:
    mov r20,r21
    andi r20,0xf0
    add r26,r20
    adc r27,r1
    call pattern_undo_capture
    ldi r30,lo8(V)
    ldi r31,hi8(V)
    add r30,r20
    adc r31,r1
    ldi r24,16
PAl:
    ld r20,z+
    tst r20
    breq PAskip
    ld r20,x
    tst r19
    brne PAneg
    add r20,r18
    cp r23,r20
    brcc PAst
    mov r20,r23
    rjmp PAst
PAneg:
    sub r20,r18
    brcs PAmin
    cp r20,r22
    brcc PAst
PAmin:
    mov r20,r22
PAst:
    st x,r20
PAskip:
    adiw r26,1
    dec r24
    brne PAl
    subi r26,16
    sbci r27,0x00
    mov r20,r21
    andi r20,0x0f
    add r26,r20
    adc r27,r1
    ld r18,x
    sts 0x3dd9,r18
    cpi r25,0x02
    brne PAe
    mov r25,r21
    swap r25
    andi r25,0x0f
    push r21
    call stepnote
    pop r21
    sts 0x3dd9,r18
PAe:
    mov r24,r21
    MONITOR_STEP_HOOK
    jmp PSend

; Lock-Taste (Firmware 0x5E20): im SEq-Spielmodus keine Anzeige-Verriegelung, sonst wie original umschalten
locktog:
    call isseq
    tst r25
    breq LTorig
    sts 0x212f,r1
    jmp 0x5eba
LTorig:
    ldi r24,0x01
    lds r25,0x212f
    tst r25
    breq LT1
    ldi r24,0x00
LT1:
    sts 0x212f,r24
    jmp 0x5eba

; The stock Lock LED uses the display latch. In sequencer play mode it
; follows the physical Lock button used for Ctrl All.
lock_indicator:
    call isseq
    tst r25
    breq LIstock
    rjmp ctrl_active
LIstock:
    lds r24,0x212f
    ret

; Read the stock pot mode at the early scanner hook (zero = Jump).
seqpoti:
    tst r10
    breq SQ1
    jmp 0x11f4
SQ1:
    push r25
    call isseq
    mov r21,r25
    pop r25
    tst r21
    brne SQ2
    push r25
    call isedit
    mov r21,r25
    pop r25
    tst r21
    brne SQed
    jmp 0x11ec
SQed:
    lds r24,0x3a56
    jmp PSed
SQ2:
    lds r21,0x3a56
    cpi r21,68
    brcs SQhistory
    jmp 0x11ec
SQhistory:
    sts SNAPF,r24
    ldi r26,lo8(RAWLAST)
    ldi r27,hi8(RAWLAST)
    add r26,r21
    adc r27,r1
    ld r23,x
    lds r18,RAWVAL
    cp r23,r18
    breq SQend
    st x,r18
    sts PREV,r23
    jmp PSplay
SQend:
    jmp 0x1466

; Snap: r24 = Poti, r25 = Anzeige-Modus, r18 = Rohwert. r19 = 1 übernehmen, 0 = noch nicht eingefangen
; (dann zeigt die Anzeige den aktuellen Wert). Erhält r18 (wenn r19 = 1), r24, r25.
snapgate:
    ldi r19,0x01
    lds r20,SNAPF
    tst r20
    brne SGgo
    ret
SGgo:
    mov r23,r25
    cpi r25,0x01
    brne SG2
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    rjmp SGstep
SG2:
    cpi r25,0x02
    brne SG6
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    rjmp SGstep
SG6:
    cpi r25,0x06
    brne SG4
    ldi r26,lo8(L)
    ldi r27,hi8(L)
    rjmp SGstep
SG4:
    cpi r25,0x0f
    brne SG4b
    ldi r26,lo8(NUDGE)
    ldi r27,hi8(NUDGE)
    rjmp SGstep
SG4b:
    cpi r25,0x04
    brne SG5
    ldi r26,lo8(P)
    ldi r27,hi8(P)
    rjmp SGstep
SG5:
    cpi r25,0x05
    brne SGa
    mov r21,r24
    swap r21
    andi r21,0x0f
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    add r26,r21
    adc r27,r1
    ld r20,x
    ldi r26,lo8(R)
    ldi r27,hi8(R)
    cpi r20,0x01
    brne SGstep
    ldi r23,0x0e
    sts 0x3dd8,r23
    ldi r26,lo8(CT)
    ldi r27,hi8(CT)
    rjmp SGstep
SGa:
    ldi r26,lo8(ROOT)
    ldi r27,hi8(ROOT)
    cpi r25,0x08
    breq SGcell
    ldi r26,lo8(SCALE)
    ldi r27,hi8(SCALE)
    cpi r25,0x07
    breq SGcell
    ret
SGstep:
    add r26,r24
    adc r27,r1
SGcell:
    ld r22,x
    push r24
    mov r24,r18
    call quant
    mov r20,r24
    lds r24,PREV
    cpi r24,0xff
    brne SGq
    mov r24,r20
    rjmp SGq2
SGq:
    call quant
SGq2:
    mov r21,r24
    pop r24
    cp r20,r22
    breq SGok
    cp r21,r22
    breq SGok
    ldi r19,0x00
    cp r20,r22
    brcc SGc1
    ldi r19,0x01
SGc1:
    ldi r23,0x00
    cp r21,r22
    brcc SGc2
    ldi r23,0x01
SGc2:
    cp r19,r23
    brne SGok
    ldi r19,0x00
    sts 0x3dd9,r22
    cpi r25,0x02
    brne SGr
    mov r18,r22
    mov r25,r24
    swap r25
    andi r25,0x0f
    call stepnote
    sts 0x3dd9,r18
    ldi r19,0x00
SGr:
    ret
SGok:
    ldi r19,0x01
    ret

; Rohwert r24 (0..127) -> Parameterwert für Modus r23 (wie bei der Übernahme); verändert r0, r24
quant:
    push r25
    cpi r23,0x01
    brne Q2
    cpi r24,0x02
    brcc Qr
    ldi r24,0x00
    rjmp Qr
Q2:
    cpi r23,0x02
    breq Qr
    cpi r23,0x06
    brne Q4
    lsr r24
    lsr r24
    lsr r24
    rjmp Qr
Q4:
    ldi r25,NPROB
    cpi r23,0x04
    breq Qmul
    cpi r23,0x05
    brne Qe
    swap r24
    lsr r24
    andi r24,0x03
    inc r24
    rjmp Qr
Qe:
    cpi r23,0x0e
    brne Qa
    swap r24
    andi r24,0x07
    rjmp Qr
Qa:
    ldi r25,13
    cpi r23,0x0f
    breq Qmul
    ldi r25,12
    cpi r23,0x08
    breq Qmul
    ldi r25,NSCALES
Qmul:
    mul r24,r25
    add r0,r0
    adc r1,r1
    mov r24,r1
    clr r1
Qr:
    pop r25
    ret

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
    ldi r26,lo8(RAWLAST)
    ldi r27,hi8(RAWLAST)
    add r26,r24
    adc r27,r1
    ld r18,x
    lds r19,RAWVAL
    cp r18,r19
    breq RCorig
    ldi r25,0x00
    jmp 0x135e
RCorig:
    ldi r25,0x00
    lds r20,0x3aa7
    jmp 0x133a

; Shared quantizer: raw pot r18 -> scale degree r20, preserving r18.
note_degree:
    ldi r30,lo8(ntab)
    ldi r31,hi8(ntab)
    lds r20,SCALE
    add r30,r20
    adc r31,r1
    call lpmz
    mul r18,r20
    add r0,r0
    adc r1,r1
    mov r20,r1
    clr r1
    ret

; Convert the degree through the same interval table used for chords.
tunenote:
    call note_degree
    lds r21,SCALE
    ldi r30,DEGW
    mul r21,r30
    ldi r30,lo8(degtab)
    ldi r31,hi8(degtab)
    add r30,r0
    adc r31,r1
    clr r1
    add r30,r20
    adc r31,r1
    call lpmz
    lds r18,ROOT
    add r18,r20
    subi r18,BASE_NOTE_NEG
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
    ldi r26,lo8(CACT)
    ldi r27,hi8(CACT)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(PACT)
    ldi r27,hi8(PACT)
    add r26,r18
    adc r27,r1
    st x,r1
    ldi r26,lo8(STF)
    ldi r27,hi8(STF)
    add r26,r18
    adc r27,r1
    ldi r19,0x01
    st x,r19
    ldi r26,lo8(FLG)
    ldi r27,hi8(FLG)
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
    brne LHedit
    rjmp LHorig
LHedit:
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
    rjmp LHheld
LHplay:
    lds r24,0x2283
    tst r24
    brne LHpatterns
    lds r24,0x3dd4
    tst r24
    breq LHrun
    lds r24,LEDROW
    cpi r24,0xff
    breq LHrun
LHrow:
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
    rjmp LHheld
LHrun:
    in r24,0x02
    tst r24
    brne LHplayhead
    lds r24,LASTROW
    rjmp LHrow
LHplayhead:
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
    rjmp LHheld
; While Shift is held, LEDs 1/2 show the playing slot (bright) and edit
; slot (dim if different). LED 3 lights while a switch is queued.
LHpatterns:
    ldi r26,0xf9
    ldi r27,0x3b
    ldi r21,8
LHclear:
    st x+,r1
    dec r21
    brne LHclear
    ldi r27,0x3b
    lds r26,EDITPAT
    subi r26,7
    ldi r24,1
    st x,r24
    lds r26,PLAYPAT
    subi r26,7
    ldi r24,3
    st x,r24
    lds r25,QUEUEPAT
    cpi r25,0xff
    breq LHheld
    sts 0x3bfb,r24
LHheld:
    ; Show pressed keys over the pattern, step, and track-edit indicators.
    ldi r26,0xf9
    ldi r27,0x3b
    ldi r30,0x0f
    ldi r31,0x23
    ldi r21,8
    ldi r24,3
LHkey:
    ld r18,z+
    tst r18
    breq LHknext
    st x,r24
LHknext:
    adiw r26,1
    dec r21
    brne LHkey
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
    brne SDsc7n
    jmp SDsc7b
SDsc7n:
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
    brne SDcl0
    jmp SDprob
SDcl0:
    cpi r24,0x0f
    brne SDcl0a
    ldi r24,0x54
    sts 0x2fe6,r24
    ldi r24,0x5e
    sts 0x2fe7,r24
    lds r18,0x3dd9
    ldi r19,0x00
    subi r18,NUDGEDEF
    brcc SDnd1
    neg r18
    ldi r19,0x40
SDnd1:
    sts 0x2fe8,r19
    mov r24,r18
    call DIGIT
    sts 0x2fe9,r24
    jmp dispcopy
SDcl0a:
    cpi r24,0x0d
    breq SDcl0b
    cpi r24,0x0e
    brne SDlp0
    lds r18,0x3dd9
    add r18,r18
    add r18,r18
    ldi r30,lo8(chnames)
    ldi r31,hi8(chnames)
    add r30,r18
    adc r31,r1
    jmp show4
SDcl0b:
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
    tst r24
    brne SDn1
    lds r20,EXT
    tst r20
    breq SDn1
    push r24
    call extbpm
    pop r24
    ldi r25,0x79
SDn1:
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
    brne SDtrim
    ldi r25,0x50
    lds r18,0x3dd9
    rjmp SDw
SDtrim:
    cpi r24,0x10
    brne SDw
    ldi r25,0x3d
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
    brne Epressed
    ret
Epressed:
    sts 0x3bf8,r1
    sts ENC_WINDOW,r1
    lds r24,SAVEPH
    cpi r24,1
    brcs Etempo
    cpi r24,PPROMOTE
    brcs Eret
Etempo:
    lds r24,EXT
    tst r24
    brne Eshow
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
    sts INTPER,r20
    sts INTPER1,r21
    in r19,0x3f
    cli
    lds r24,EXT
    tst r24
    brne Eskip
    sts 0x0a36,r20
    sts 0x0a37,r21
Eskip:
    out 0x3f,r19
    MONITOR_HEADER_HOOK
Eshow:
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
    ; The stock loop only publishes 0x230e in play/setup. In Track Edit
    ; read the encoder push from its ADC sample using the same threshold.
    lds r19,0x2fa3
    clr r18
    sbrs r19,7
    inc r18
    lds r19,TEMPO_KEY
    sts TEMPO_KEY,r18
    tst r18
    breq SEbuttons
    tst r19
    brne SEbuttons
    ldi r18,9
    sts EDPAR,r18
SEbuttons:
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
    cpi r18,0x08
    brne SEbp
    push r18
    in r19,0x02
    tst r19
    brne SEb8s
    call seqstart
    pop r18
    rjmp SEbn
SEb8s:
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
    lds r24,SAVEPH
    cpi r24,1
    brcs SEeditable
    cpi r24,PPROMOTE
    brcc SEeditable
    ret
SEeditable:
    lds r25,0x213e
    lds r18,EDPAR
    lds r19,EDTRK
    cpi r18,9
    brne SEtrack
    ldi r26,lo8(SWING)
    ldi r27,hi8(SWING)
    clr r20
    ldi r21,6
    rjmp SEchg
SEtrack:
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
    ldi r21,0x02
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    cpi r18,0x07
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
    rjmp SEnotify
SEdn:
    cp r20,r22
    brcc SEret
    dec r22
    st x,r22
SEnotify:
    MONITOR_HEADER_HOOK
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
    cpi r18,9
    brne ESnormal
    lds r24,SWING
    sts 0x3dd9,r24
    jmp SDswing
ESnormal:
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
    cpi r18,0x07
    brne ES6d
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    add r26,r19
    adc r27,r1
    ld r18,x
    add r18,r18
    add r18,r18
    ldi r30,lo8(modenames)
    ldi r31,hi8(modenames)
    add r30,r18
    adc r31,r1
    jmp show4
ES6d:
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

; Keep SEq in RAM across setup loads and encoder changes. The two setup
; exits skip the stock route write so reflashing restores the user's choice.
load_seq_routing:
    call lock_seq_routing
    jmp 0x416a

lock_seq_routing:
    ldi r24,SEQ
    sts ROUTING,r24
    ret

rdisp:
    ldi r24,0x6d
    sts 0x2fe6,r24
    ldi r24,0x79
    sts 0x2fe7,r24
    ldi r24,0x67
    sts 0x2fe8,r24
    sts 0x2fe9,r1
    jmp 0x3a18

; TCE0-Überlauf: nur Ticks zählen (Hauptschleife arbeitet sie nach)
tce0isr:
    push r24
    in r24,0x3f
    push r24
    cli
    lds r24,EXT
    tst r24
    brne TOext
    lds r24,0x3de0
    inc r24
    sts 0x3de0,r24
    rjmp TOend
; externe Clock ausgeblieben (>131 ms ohne F8): zurück zum internen Takt, laufenden Sequencer stoppen
TOext:
    ldi r24,0x00
    sts EXT,r24
    sts 0x0a07,r24
    lds r24,INTPER
    sts 0x0a26,r24
    lds r24,INTPER1
    sts 0x0a27,r24
    lds r24,INTPER
    sts 0x0a36,r24
    lds r24,INTPER1
    sts 0x0a37,r24
    in r24,0x02
    tst r24
    breq TOend
    ldi r24,0x02
    sts EXTCMD,r24
TOend:
    pop r24
    out 0x3f,r24
    pop r24
    reti

; TCE0 Vergleich A: zweiter Tick zwischen zwei F8 (einmalig, schaltet sich ab)
tceccaisr:
    push r24
    in r24,0x3f
    push r24
    cli
    ldi r24,0x00
    sts 0x0a07,r24
    lds r24,0x3de0
    inc r24
    sts 0x3de0,r24
    pop r24
    out 0x3f,r24
    pop r24
    reti

; ================================================================ MIDI-Eingang (im Empfangs-Interrupt der Firmware)
; Byte lesen wie die Firmware (r28), Echtzeit-Bytes im SEq-Modus auswerten. Alle Register ausser r2..r15
; hat der Firmware-Interrupt schon gesichert.
rxc0:
    lds r28,0x08a0
    ldi r25,0x01
    MONITOR_RX_HOOK
    rjmp rxrt
rxd0:
    lds r28,0x09a0
    ldi r25,0x02
rxrt:
    cpi r28,0xf8
    brcs RXr
    lds r24,ROUTING
    cpi r24,SEQ
    brne RXr
    lds r24,EXT
    tst r24
    breq RXany
    cp r24,r25
    brne RXr
RXany:
    cpi r28,0xf8
    breq RXclk
    cpi r28,0xfa
    breq RXstart
    cpi r28,0xfb
    breq RXcont
    cpi r28,0xfc
    breq RXstop
RXr:
    ret
RXstop:
    ldi r24,0x02
    sts EXTCMD,r24
    ret
RXcont:
    ldi r24,0x03
    rjmp RXcmd
RXstart:
    ldi r24,0x01
RXcmd:
    sts EXTCMD,r24
    lds r24,0x3de0
    sts EXTSYNC,r24
    sts 0x0a07,r1
    lds r24,EXT
    tst r24
    brne RXr
    jmp extenter
RXclk:
    lds r24,EXT
    tst r24
    brne RXc2
    call extenter
RXc2:
    lds r24,EXTFIRST
    tst r24
    breq RXc3
    sts EXTFIRST,r1
    sts 0x0a20,r1
    sts 0x0a21,r1
    ldi r25,0x02
    rjmp RXadd
RXc3:
    ldi r25,0x01
    lds r24,0x0a07
    tst r24
    breq RXc4
    sts 0x0a07,r1
    inc r25
RXc4:
    lds r20,0x0a20
    lds r21,0x0a21
    sts 0x0a20,r1
    sts 0x0a21,r1
    mov r22,r20
    mov r23,r21
    lsr r23
    ror r22
    sts 0x0a28,r22
    sts 0x0a29,r23
    ldi r24,0x10
    sts 0x0a0c,r24
    ldi r24,0x01
    sts 0x0a07,r24
    ldi r24,0x05
RXsh:
    lsr r21
    ror r20
    dec r24
    brne RXsh
    lds r22,EXTSUM
    lds r23,EXTSUM1
    add r22,r20
    adc r23,r21
    lds r24,EXTN
    inc r24
    cpi r24,24
    brcs RXs
    sts EXTTOT,r22
    sts EXTTOT1,r23
    clr r22
    clr r23
    clr r24
RXs:
    sts EXTN,r24
    sts EXTSUM,r22
    sts EXTSUM1,r23
RXadd:
    lds r24,0x3de0
    add r24,r25
    sts 0x3de0,r24
    ret

; Umschalten auf externe Clock (Quelle r25): Timer misst nur noch die F8-Abstände
extenter:
    sts EXT,r25
    ldi r24,0x01
    sts EXTFIRST,r24
    ldi r24,0xff
    sts 0x0a36,r24
    sts 0x0a37,r24
    sts 0x0a26,r24
    sts 0x0a27,r24
    sts 0x0a20,r1
    sts 0x0a21,r1
    sts EXTN,r1
    sts EXTSUM,r1
    sts EXTSUM1,r1
    sts EXTTOT,r1
    sts EXTTOT1,r1
    ret

; Hauptschleife: Start/Stopp/Continue von aussen ausführen
extcmd:
    lds r24,EXTCMD
    tst r24
    brne XC1
    ret
XC1:
    sts EXTCMD,r1
    cpi r24,0x02
    brne XC2
    jmp stopseq
XC2:
    cpi r24,0x03
    brne XC3
    ldi r24,0x01
    out 0x02,r24
    ret
XC3:
    lds r24,EXTSYNC
    sts 0x3de1,r24
    in r24,0x02
    tst r24
    breq XC4
    call stopseq
XC4:
    jmp seqstart

; gemessenes Tempo der externen Clock -> r18 (0 = noch unbekannt)
extbpm:
    in r19,0x3f
    cli
    lds r22,EXTTOT
    lds r23,EXTTOT1
    out 0x3f,r19
    ldi r24,0x04
XB1:
    lsr r23
    ror r22
    dec r24
    brne XB1
    ldi r18,0x00
    mov r24,r22
    or r24,r23
    breq XBr
    ldi r24,lo8(BPMK)
    ldi r25,hi8(BPMK)
    call 0x6bcc
    ldi r18,0xff
    tst r23
    brne XBr
    mov r18,r22
XBr:
    ret

; ================================================================ Spur-Modi
; Note für Poti-Wert r18 der Spur r25 -> r18 (Note: Skala+Grundton, Chord: ebenso, Pad: chromatisch)
; verändert r0,r20,r21,r26,r27,r30,r31
stepnote:
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    add r26,r25
    adc r27,r1
    ld r20,x
    cpi r20,0x02
    brne SNsc
    subi r18,PADSHIFT
    brcc SNoct
    ldi r18,0x00
    rjmp SNoct
SNsc:
    call tunenote
SNoct:
    jmp addoct

; Nach dem Grundton (LN der Spur r17): in Chord-Spuren bis zu 3 weitere Töne aus der Skala
chordon:
    ldi r26,lo8(MODE)
    ldi r27,hi8(MODE)
    add r26,r17
    adc r27,r1
    ld r20,x
    cpi r20,0x01
    breq COgo
    ret
COgo:
    push r14
    push r15
    push r16
    push r28
    push r29
    lds r29,FSTEP
    ldi r26,lo8(LN)
    ldi r27,hi8(LN)
    add r26,r17
    adc r27,r1
    ld r15,x
    ldi r26,lo8(CT)
    ldi r27,hi8(CT)
    add r26,r29
    adc r27,r1
    ld r18,x
    mov r14,r18
    add r14,r18
    add r14,r18
    lds r18,SCALE
    tst r18
    brne COk
    ldi r18,24
    add r14,r18
COk:
    ldi r26,lo8(N)
    ldi r27,hi8(N)
    add r26,r29
    adc r27,r1
    ld r18,x
    call note_degree
    mov r28,r20
    clr r16
COl:
    ldi r30,lo8(chotab)
    ldi r31,hi8(chotab)
    add r30,r14
    adc r31,r1
    add r30,r16
    adc r31,r1
    call lpmz
    tst r20
    breq COnx
    sbrs r20,7
    rjmp COdeg
    andi r20,0x7f
    mov r22,r15
    add r22,r20
    rjmp COsend
COdeg:
    mov r23,r20
    lds r18,SCALE
    ldi r19,DEGW
    mul r18,r19
    ldi r30,lo8(degtab)
    ldi r31,hi8(degtab)
    add r30,r0
    adc r31,r1
    clr r1
    add r30,r28
    adc r31,r1
    call lpmz
    mov r19,r20
    add r30,r23
    adc r31,r1
    call lpmz
    sub r20,r19
    mov r22,r15
    add r22,r20
COsend:
    cpi r22,0x80
    brcc COnx
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    add r26,r29
    adc r27,r1
    ld r18,x
    call trim_velocity
    mov r20,r18
    ldi r30,lo8(CHN)
    ldi r31,hi8(CHN)
    add r30,r17
    adc r31,r1
    ld r24,z
    subi r24,0x70
    push r22
    call SEND3
    pop r22
    tst r24
    breq COnx
    mov r18,r17
    add r18,r17
    add r18,r17
    add r18,r16
    ldi r26,lo8(LNX)
    ldi r27,hi8(LNX)
    add r26,r18
    adc r27,r1
    st x,r22
COnx:
    inc r16
    cpi r16,0x03
    breq COend
    rjmp COl
COend:
    pop r29
    pop r28
    pop r16
    pop r15
    pop r14
    ret

; 4 Zeichen ab Z (Flash) in die Anzeige
show4:
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

nofft:
    .byte NOFFT
modenames:
    .byte MODENAMES
chnames:
    .byte CHNAMES
chotab:
    .byte CHOTAB
ntab:
    .byte NTAB
degtab:
    .byte DEGTAB

; ================================================================ EEPROM
; Abbild-Offset r24:r25 -> X = RAM-Adresse, r22 = Minimum, r23 = Maximum, r21 = Ersatzwert
; (verändert r19,r20,r21,r24,r25,r30,r31)
imgptr:
    ldi r30,lo8(eetab)
    ldi r31,hi8(eetab)
    rjmp region_addr
pattern_addr:
    ldi r30,lo8(pattern_regions)
    ldi r31,hi8(pattern_regions)
region_addr:
    lds r19,0x01ca
    sts 0x01ca,r1
IPl:
    lpm r26,z+
    lpm r27,z+
    lpm r20,z+
    lpm r22,z+
    lpm r23,z+
    lpm r21,z+
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
    ldi r19,hi8(EEMAP)
    add r30,r20
    adc r31,r19
    ld r18,z
    cp r18,r22
    brcs ELdef
    cp r23,r18
    brcc ELok
ELdef:
    mov r18,r21
ELok:
    st x,r18
    adiw r28,1
    cpi r28,lo8(EESIZE)
    ldi r24,hi8(EESIZE)
    cpc r29,r24
    brne ELl
    call apply_settings
ELx:
    pop r29
    pop r28
    ret

apply_settings:
    ; The four legacy mute bytes remain reserved in the EEPROM format.
    sts MREQ,r1
    sts MREQ1,r1
    sts MREQ2,r1
    sts MREQ3,r1
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
    sts INTPER,r20
    sts INTPER1,r21
    ret

eetab:
    .byte EETAB
pertab:
    .byte PERTAB
scnames:
    .byte SCNAMES
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


def main(src, dst, enable_monitor=False):
    self_test()
    hdr, img = decode(open(src, 'rb').read())
    img = bytearray(img)
    if len(img) != BASE:
        raise ValueError('Unexpected firmware image length')
    patches = PATCHES + patterns.PATCHES
    for adr, orig, _ in patches:
        got = img[adr:adr + len(bytes.fromhex(orig))].hex(' ')
        if got != orig:
            raise ValueError(f'Firmware bytes at 0x{adr:04X}: got {got}, expected {orig}')

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
        LOOP=0x3E7C, MREQ=0x3E84, MREQ1=0x3E85, MREQ2=0x3E86, MREQ3=0x3E87, LCH=0x3E88, EDTRK=0x3E8C, EDPAR=0x3E8D,
        SPDDEF=SPD_DEFAULT, PROBDEF=PROB_DEFAULT, NPROB=NPROB,
        **{'T' + k: ', '.join(map(str, v)) for k, v in seqtables().items()},
        RAWVAL=0x3DF6, RAWLAST=0x3E10, POS=0x3DEE, TLEN=0x3DF2, TLEN1=0x3DF3, TLEN2=0x3DF4, TLEN3=0x3DF5,
        SWING=0x3DED, SWDISP='50, 54, 58, 62, 67, 71, 75',
        OCT=0x3DE9, OCT1=0x3DEA, OCT2=0x3DEB, OCT3=0x3DEC,
        POTSCALE=POT_SCALE, POTROOT=POT_ROOT, ROOT=0x3DE8, LENDEF=LEN_DEFAULT,
        OFF1=RAM['OFF'] + 1, OFF2=RAM['OFF'] + 2, OFF3=RAM['OFF'] + 3,
        LENTAB=', '.join(str(t) for t, _, _ in LENGTHS),
        LENDISP=', '.join('%d, %d' % (d, p) for _, d, p in LENGTHS),
        ROOTDISP=', '.join('%d, %d' % r for r in ROOTS),
        TUNEDEF=TUNE_DEFAULT, NSCALES=len(SCALES), SCALE=0x3DE2, LEDROW=0x3DE3,
        V4=RAM['V'] + 4, V8=RAM['V'] + 8, V12=RAM['V'] + 12,
        SCNAMES=', '.join(str(c) for n, _ in SCALES for c in n),
        BASE_NOTE_NEG=256 - BASE_NOTE,
        ACT1=RAM['ACT'] + 1, ACT2=RAM['ACT'] + 2, ACT3=RAM['ACT'] + 3,
        EEBASE=EEBASE, EEMAP=0x1000 + EEBASE, EESIZE=EESIZE,
        EEMAGA=0x1000 + EEBASE + MAGOFF, EEMAGB=0x1000 + EEBASE + MAGOFF + 1,
        MAG0=MAGIC[0], MAG1=MAGIC[1], MAGIC=0x3E04, MAGIC1=0x3E05, CLRF=0x3E06,
        EETAB=', '.join('%d, %d, %d, %d, %d, %d' % (a & 0xFF, a >> 8, n, lo, hi, d) for a, n, lo, hi, d in EEREGIONS),
        MODE=0x3DC8, EXT=0x3DCC, EXTFIRST=0x3DCD, EXTCMD=0x3DCE, EXTSYNC=0x3DCF, EXTN=0x3DD0,
        EXTSUM=0x3DD1, EXTSUM1=0x3DD2, EXTTOT=0x3E08, EXTTOT1=0x3E09, INTPER=0x3E0A, INTPER1=0x3E0B,
        LNX=0x3E54, CT=0x3E90, SNAPF=0x3E0C, PREV=0x3E0D, NUDGE=0x3EE0, NUDGEDEF=NUDGE_DEFAULT, NPROBMAX=NPROB - 1,
        CPOS=0x3DF8, CACT=0x3DFC, PPOS=0x3E00, PACT=0x3F20, STF=0x3F24, FLG=0x3F28, FSTEP=0x3E0E,
        NOFFT=', '.join(map(str, nofftab())), BPMK=58593, PADSHIFT=PAD_SHIFT, DEGW=DEGW,
        MODENAMES=', '.join(str(c) for n in MODENAMES for c in n),
        CHNAMES=', '.join(str(c) for n in CHORDNAMES for c in n),
        CHOTAB=', '.join(str(c) for t in CHORD_SCALE + CHORD_CHROM for c in t),
        NTAB=', '.join(map(str, degtables()[1] + [0] * (len(degtables()[1]) % 2))), DEGTAB=', '.join(map(str, degtables()[0])),
        **RAM)
    consts.update(patterns.CONSTS)
    consts.update({
        'MONITOR_INIT_HOOK': 'call monitor_init' if enable_monitor else '',
        'MONITOR_TICK_HOOK': 'call monitor_tick' if enable_monitor else '',
        'MONITOR_RX_HOOK': 'call monitor_rx' if enable_monitor else '',
        'MONITOR_STEP_HOOK': 'call monitor_queue_step' if enable_monitor else '',
        'MONITOR_TRIM_HOOK': 'call monitor_queue_trim' if enable_monitor else '',
        'MONITOR_HEADER_HOOK': 'call monitor_queue_header' if enable_monitor else '',
        'MONITOR_CLEAR_HOOK': 'call monitor_queue_clear' if enable_monitor else '',
        'MONITOR_PATTERN_HOOK': 'call monitor_resync' if enable_monitor else '',
        'MONITOR_UNDO_HOOK': 'call monitor_undo' if enable_monitor else '',
    })
    if enable_monitor:
        consts.update(monitor.constants(consts))
    extra_asm = monitor.ASM if enable_monitor else ''
    code, labels = assemble(extra_asm + patterns.ASM + ASM, BASE, consts)
    print('Neuer Code + Tabellen: %d Bytes ab 0x%04X' % (len(code), BASE))

    for adr, orig, line in patches:
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
    parser = argparse.ArgumentParser(description='Build the PC44 A/B sequencer firmware.')
    parser.add_argument('source', help='Original Faderfox V01.01 SysEx image')
    parser.add_argument('output', help='Destination SysEx image')
    parser.add_argument('--monitor', action='store_true', help='Enable the PC44 Monitor preview protocol')
    args = parser.parse_args()
    main(args.source, args.output, enable_monitor=args.monitor)
