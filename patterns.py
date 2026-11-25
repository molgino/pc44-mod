"""A/B sequencer controls, working memory and EEPROM layout."""

# Firmware V01.01 stores 68 eight-bit ADC histories starting at 0x2b63.
# The patched scanner uses eight samples per pot, leaving the second half free.
# The encoder switch uses the following ADC channel at its original address.
SHADOW = 0x2B63 + 68 * 8
ADC_END = 0x2FA3

PATTERN_REGIONS = [
    (0x3C80, 64, 0, 127, 62),  # pitch
    (0x3CC0, 64, 0, 127, 0),   # velocity
    (0x3D00, 64, 0, 44, 9),    # probability or condition
    (0x3D40, 64, 1, 4, 1),     # ratchets
    (0x3D88, 64, 0, 15, 2),    # gate
    (0x3E90, 64, 0, 7, 0),     # chord
    (0x3EE0, 64, 0, 12, 6),    # nudge
    (0x3DE9, 4, 0, 6, 3),     # octave
    (0x3DF2, 4, 1, 16, 16),   # length
    (0x3E60, 4, 0, 6, 4),     # division
    (0x3E64, 1, 0, 15, 0),    # channels 1–4
    (0x3E65, 1, 0, 15, 1),
    (0x3E66, 1, 0, 15, 2),
    (0x3E67, 1, 0, 15, 3),
    (0x3E68, 4, 0, 3, 0),     # direction
    (0x3DC8, 4, 0, 2, 0),     # mode
    # Keep these at their original offsets so saved A/B images still load.
    (0x3DE2, 1, 0, 10, 0),    # scale
    (0x3DE8, 1, 0, 11, 0),    # root
]
GLOBALS = [
    (0x3DED, 1, 0, 6, 0),     # shuffle
    (0x0003, 1, 30, 250, 120),  # internal tempo
    (0x3E84, 4, 0, 0, 0),     # reserved legacy mute bytes
]
PATTERN_SIZE = sum(region[1] for region in PATTERN_REGIONS)
PAYLOAD_SIZE = PATTERN_SIZE + sum(region[1] for region in GLOBALS)
JOURNAL = 0x200
SLOTS = (0x400, 0x600)
PAYLOAD_PAGES = PAYLOAD_SIZE // 32
HEADER_OFFSET = PAYLOAD_SIZE
assert PAYLOAD_SIZE == 480
assert SHADOW + PATTERN_SIZE + 69 <= ADC_END

CONSTS = dict(
    PSHADOW=SHADOW, PSIZE=PATTERN_SIZE, PSAVED=PAYLOAD_SIZE,
    PREGIONS=len(PATTERN_REGIONS), PBARLEN=192,
    PSLOTA=SLOTS[0], PSLOTB=SLOTS[1],
    PHEADER=HEADER_OFFSET, PHEADER_READ=HEADER_OFFSET + 4,
    PWRITE=2, PJCOMMIT=PAYLOAD_PAGES + 2, PPROMOTE=PAYLOAD_PAGES + 3,
    PSCOMMIT=2 * PAYLOAD_PAGES + 3, PFINISHED=2 * PAYLOAD_PAGES + 5,
    PJHDR=JOURNAL + HEADER_OFFSET, PMAPJHDR=0x1000 + JOURNAL + HEADER_OFFSET,
    PMAPAHDR=0x1000 + SLOTS[0] + HEADER_OFFSET, PMAPBHDR=0x1000 + SLOTS[1] + HEADER_OFFSET,
    PJHIGH_NEG=(-JOURNAL >> 8) & 255, PMAPJHIGH_NEG=(-(0x1000 + JOURNAL) >> 8) & 255,
    PLAYPAT=SHADOW + PATTERN_SIZE, EDITPAT=SHADOW + PATTERN_SIZE + 1,
    QUEUEPAT=SHADOW + PATTERN_SIZE + 2, BARPOS=SHADOW + PATTERN_SIZE + 3,
    SAVEPH=SHADOW + PATTERN_SIZE + 4, SAVESLOT=SHADOW + PATTERN_SIZE + 5,
    PATKEY=SHADOW + PATTERN_SIZE + 6, CTRLSTATE=SHADOW + PATTERN_SIZE + 7,
    SAVEGEN=SHADOW + PATTERN_SIZE + 8,
    SAVEGENHI=SHADOW + PATTERN_SIZE + 9,
    PAGEBUF=SHADOW + PATTERN_SIZE + 10,
    VTRIM=SHADOW + PATTERN_SIZE + 42, VTRIM1=SHADOW + PATTERN_SIZE + 43,
    VTRIM2=SHADOW + PATTERN_SIZE + 44, VTRIM3=SHADOW + PATTERN_SIZE + 45,
    UNDOPTR=SHADOW + PATTERN_SIZE + 46, UNDOPTRHI=SHADOW + PATTERN_SIZE + 47,
    UNDOEDIT=SHADOW + PATTERN_SIZE + 48, UNDOHELD=SHADOW + PATTERN_SIZE + 49,
    UNDOBUF=SHADOW + PATTERN_SIZE + 50,
    TEMPO_KEY=SHADOW + PATTERN_SIZE + 66, LASTROW=SHADOW + PATTERN_SIZE + 67,
    ENC_WINDOW=SHADOW + PATTERN_SIZE + 68,
    ENC_DOUBLE_TICKS=160, ENC_DEBOUNCE_LIMIT=147,
    PREGTAB=', '.join(
        str(value) for addr, size, low, high, default in PATTERN_REGIONS + GLOBALS
        for value in (addr & 255, addr >> 8, size, low, high, default)
    ),
)

PATCHES = [
    (0x687A, '0e 94 87 1f', 'call pattern_boot'),
    (0x05D6, '80 93 9d 3a', 'call pattern_panel_clock'),
    (0x07D4, 'e2 95 f2 95', 'jmp adc_sample_12'),
    (0x083A, 'e2 95 f2 95', 'jmp adc_sample_11'),
    (0x08B2, 'e2 95 f2 95', 'jmp adc_sample_4_10'),
    (0x0EF0, '30 e1', 'ldi r19,8'),
    (0x0F20, '80 31', 'cpi r24,8'),
    (0x0F3C, 'e0 92 a4 31', 'jmp adc_scan_scale'),
    (0x6906, '90 e1', 'ldi r25,8'),
    (0x6934, '80 31', 'cpi r24,8'),
    (0x694C, '80 93 a4 31', 'jmp adc_init_scale'),
]

ASM = r"""
; The firmware cursor still runs through 16 slots. Keep the low three bits,
; use an eight-byte stride, and preserve the original average scaling.
adc_sample_12:
    cpi r30,68
    brcs ADC12valid
    ; The encoder push switch is read from the stock ADC buffer at 0x2fa3.
    ; Keep the original stride and store path for the non-pot channels.
    swap r30
    swap r31
    jmp 0x07d8
ADC12valid:
    call adc_addr
    jmp 0x07e8
adc_sample_11:
    call adc_addr
    jmp 0x084e
adc_sample_4_10:
    call adc_addr
    jmp 0x08c6
adc_addr:
    add r30,r30
    adc r31,r31
    add r30,r30
    adc r31,r31
    add r30,r30
    adc r31,r31
    andi r24,7
    add r30,r24
    adc r31,r1
    subi r30,0x9d
    sbci r31,0xd4
    ret
adc_scan_scale:
    add r14,r14
    adc r15,r15
    sts 0x31a4,r14
    sts 0x31a5,r15
    jmp 0x0f44
adc_init_scale:
    add r24,r24
    adc r25,r25
    sts 0x31a4,r24
    sts 0x31a5,r25
    jmp 0x6954

pattern_boot:
    ldi r24,SEQ
    sts ROUTING,r24
    jmp 0x3f0e

; The usual sequencer arrays always hold the pattern being edited. PSHADOW
; holds the other slot. Only the main thread reads or swaps the pattern data.
; r24 = 0: exchange slots, 1: overwrite the shadow with the editing pattern.
pattern_buffer:
    push r28
    push r29
    ldi r28,lo8(PSHADOW)
    ldi r29,hi8(PSHADOW)
    ldi r30,lo8(pattern_regions)
    ldi r31,hi8(pattern_regions)
    lds r23,0x01ca
    sts 0x01ca,r1
    ldi r22,PREGIONS
PBregion:
    lpm r26,z+
    lpm r27,z+
    lpm r21,z+
    adiw r30,3
PBbyte:
    ld r18,x
    ld r19,y
    st y+,r18
    tst r24
    brne PBcopy
    st x,r19
PBcopy:
    adiw r26,1
    dec r21
    brne PBbyte
    dec r22
    brne PBregion
    sts 0x01ca,r23
    pop r29
    pop r28
    ret

; The original panel ISR advances its scan byte every 5,001 CPU
; cycles. Count down at every 16th scan (about 2.5 ms). Preserve the
; original STS result and flags. Only touch the timer on those scans.
pattern_panel_clock:
    sts 0x3a9d,r24
    sbrc r24,0
    ret
    sbrc r24,1
    ret
    sbrc r24,2
    ret
    sbrc r24,3
    ret
    push r0
    in r0,0x3f
    push r24
    lds r24,ENC_WINDOW
    tst r24
    breq PPCrestore
    dec r24
    sts ENC_WINDOW,r24
PPCrestore:
    pop r24
    out 0x3f,r0
    pop r0
    ret

; Shift + 1/2 edit A/B, 3 switches playback, 4 copies, 5 saves, 6 reverts.
; Track held keys independently so a new press works while another is held.
pattern_keys:
    lds r18,0x2283
    tst r18
    breq PKrelease
    ldi r26,0x0f
    ldi r27,0x23
    lds r18,PATKEY
    ldi r20,1
    clr r21
    clr r22
    ldi r24,1
PKscan:
    ld r19,x+
    tst r19
    breq PKnext
    or r21,r20
    mov r19,r18
    and r19,r20
    brne PKnext
    tst r22
    brne PKnext
    mov r22,r24
    or r18,r20
PKnext:
    add r20,r20
    inc r24
    cpi r24,7
    brne PKscan
    and r18,r21
    sts PATKEY,r18
    mov r24,r22
    tst r24
    brne PKpressed
    ret
PKrelease:
    sts PATKEY,r1
    ret
PKpressed:
    cpi r24,3
    breq pattern_request_switch
    lds r18,SAVEPH
    tst r18
    breq PKaction
    cpi r18,PPROMOTE
    brcs PKret
    cpi r24,5
    breq PKret
PKaction:
    cpi r24,3
    brcs PKselect
    cpi r24,4
    breq PKcopy
    cpi r24,5
    breq PKsave
    jmp pattern_revert
PKsave:
    jmp pattern_save
PKselect:
    dec r24
    rjmp pattern_select
pattern_request_switch:
    sts 0x3dd4,r1
    lds r24,QUEUEPAT
    cpi r24,0xff
    breq PKswitch
    ldi r24,0xff
    sts QUEUEPAT,r24
    ret
PKswitch:
    lds r24,PLAYPAT
    ldi r18,1
    eor r24,r18
    sts QUEUEPAT,r24
    in r18,0x02
    tst r18
    brne PKret
    jmp pattern_launch
PKcopy:
    sts UNDOPTRHI,r1
    lds r24,PLAYPAT
    call pattern_select
    ldi r24,1
    call pattern_buffer
    lds r24,PLAYPAT
    ldi r18,1
    eor r24,r18
    call pattern_select
    MONITOR_PATTERN_HOOK
    ret
PKret:
    ret

pattern_select:
    lds r18,EDITPAT
    cp r24,r18
    breq PSelret
    sts EDITPAT,r24
    sts 0x3dd4,r1
    clr r24
    jmp pattern_buffer
PSelret:
    ret

pattern_launch:
    lds r24,QUEUEPAT
    ldi r18,0xff
    sts QUEUEPAT,r18
    lds r18,PLAYPAT
    cp r24,r18
    breq PLret
    sts PLAYPAT,r24
    sts 0x3dd4,r1
    call flushnotes
    jmp posreset
PLret:
    ret

; Both internal and external clocks feed the same 48-PPQN tick path.
pattern_tick:
    lds r18,BARPOS
    tst r18
    brne PTinc
    lds r24,QUEUEPAT
    cpi r24,0xff
    breq PTfirst
    call pattern_launch
PTfirst:
    clr r18
PTinc:
    inc r18
    cpi r18,PBARLEN
    brcs PTstore
    clr r18
PTstore:
    sts BARPOS,r18
    lds r18,EDITPAT
    lds r24,PLAYPAT
    cp r18,r24
    brne PTswap
    jmp seqtick
PTswap:
    clr r24
    call pattern_buffer
    call seqtick
    clr r24
    jmp pattern_buffer

; Four seven-segment digits: playing slot, dash, queued slot, edit slot.
; With no queue, a dash separates the playing and editing slots ("A- B").
pattern_display:
    lds r24,SAVEPH
    tst r24
    breq PDplaying
    ldi r30,lo8(save_text)
    ldi r31,hi8(save_text)
    jmp show4
PDplaying:
    lds r24,PLAYPAT
    call pattern_letter
    sts 0x2fe6,r24
    ldi r24,0x40
    sts 0x2fe7,r24
    lds r24,QUEUEPAT
    cpi r24,0xff
    breq PDblank
    call pattern_letter
    ori r24,0x80
    rjmp PDqueued
PDblank:
    clr r24
PDqueued:
    sts 0x2fe8,r24
    lds r24,EDITPAT
    call pattern_letter
    sts 0x2fe9,r24
    jmp dispcopy
pattern_letter:
    tst r24
    breq PDletterA
    ldi r24,0x7c
    ret
PDletterA:
    ldi r24,0x77
    ret

save_text:
    .byte 0x6d, 0x77, 0x3e, 0x79
pattern_regions:
    .byte PREGTAB
"""

ASM += r"""
; A save first commits a complete journal at 0x200, then copies it to
; the selected slot. The header is written last in both locations.
; Boot can read a committed journal directly and resume interrupted promotion.
pattern_init:
    sts PLAYPAT,r1
    sts EDITPAT,r1
    sts BARPOS,r1
    sts PATKEY,r1
    sts CTRLSTATE,r1
    sts SAVEPH,r1
    sts SAVEGEN,r1
    sts SAVEGENHI,r1
    sts UNDOPTRHI,r1
    sts UNDOHELD,r1
    sts TEMPO_KEY,r1
    sts LASTROW,r1
    sts ENC_WINDOW,r1
    ldi r24,64
    sts VTRIM,r24
    sts VTRIM1,r24
    sts VTRIM2,r24
    sts VTRIM3,r24
    ldi r24,0xff
    sts QUEUEPAT,r24
    ldi r30,lo8(PMAPJHDR)
    ldi r31,hi8(PMAPJHDR)
    call pattern_header
    cpi r24,0xff
    breq PIa
    sts SAVESLOT,r24
    ldi r24,PPROMOTE
    sts SAVEPH,r24
PIa:
    clr r24
    call pattern_source
    brcs PIclone
    sts SAVEGEN,r25
    sts SAVEGENHI,r21
    ldi r24,1
    sts PATKEY,r24
    ldi r24,lo8(PSAVED)
    ldi r25,hi8(PSAVED)
    call pattern_load
PIclone:
    ldi r24,1
    call pattern_buffer
    ldi r24,1
    call pattern_source
    brcs PIdone
    lds r18,PATKEY
    tst r18
    breq PIglobals
    lds r19,SAVEGEN
    mov r18,r25
    sub r18,r19
    lds r19,SAVEGENHI
    mov r18,r21
    sbc r18,r19
    breq PIpattern
    sbrc r18,7
    rjmp PIpattern
PIglobals:
    sts SAVEGEN,r25
    sts SAVEGENHI,r21
    ldi r24,lo8(PSAVED)
    ldi r25,hi8(PSAVED)
    rjmp PIloadB
PIpattern:
    ldi r24,lo8(PSIZE)
    ldi r25,hi8(PSIZE)
PIloadB:
    call pattern_load
    clr r24
    call pattern_buffer
PIdone:
    sts PATKEY,r1
    jmp apply_settings

; r24 = desired slot. Return mapped payload in Z and generation in r25 (low), r21 (high).
; Carry set if missing.
pattern_source:
    mov r20,r24
    lds r18,SAVEPH
    tst r18
    breq PSprimary
    lds r18,SAVESLOT
    cp r18,r20
    brne PSprimary
    ldi r30,lo8(PMAPJHDR)
    ldi r31,hi8(PMAPJHDR)
    rjmp PSheader
PSprimary:
    ldi r30,lo8(PMAPAHDR)
    ldi r31,hi8(PMAPAHDR)
    tst r20
    breq PSheader
    ldi r31,hi8(PMAPBHDR)
PSheader:
    call pattern_header
    cp r24,r20
    breq PSfound
    sec
    ret
PSfound:
    ; pattern_header leaves Z four bytes past the marker's start.
    subi r30,lo8(PHEADER_READ)
    sbci r31,hi8(PHEADER_READ)
    clc
    ret

; Read a nine-byte commit marker. Return slot r24, generation r25:r21 (low:high),
; or slot 0xff for an invalid/erased marker. Clobbers r18 and Z.
pattern_header:
    ld r18,z+
    cpi r18,0x50
    brne PHbad
    ld r18,z+
    cpi r18,26
    brne PHbad
    ld r24,z+
    cpi r24,2
    brcc PHbad
    ld r18,z+
    com r18
    cp r18,r24
    brne PHbad
    ld r25,z+
    ld r18,z+
    com r18
    cp r18,r25
    brne PHbad
    ld r21,z+
    ld r18,z+
    com r18
    cp r18,r21
    brne PHbad
    ld r18,z
    cpi r18,0xa5
    brne PHbad
    ; Restore Z to the byte after the slot/complement pair.
    sbiw r30,4
    ret
PHbad:
    ldi r24,0xff
    ret

; Copy and validate r24:r25 bytes from a mapped EEPROM image into the
; working arrays. Z is the source, X is derived from the region table.
pattern_load:
    push r14
    push r15
    push r16
    push r17
    push r28
    push r29
    movw r14,r24
    movw r16,r30
    clr r28
    clr r29
PLoadbyte:
    movw r30,r16
    add r30,r28
    adc r31,r29
    ld r18,z
    movw r24,r28
    call pattern_addr
    cp r18,r22
    brcs PLoaddefault
    cp r23,r18
    brcc PLoadstore
PLoaddefault:
    mov r18,r21
PLoadstore:
    st x,r18
    adiw r28,1
    cp r28,r14
    cpc r29,r15
    brne PLoadbyte
    pop r29
    pop r28
    pop r17
    pop r16
    pop r15
    pop r14
    ret

pattern_save:
    lds r24,EDITPAT
    sts SAVESLOT,r24
    lds r24,SAVEGEN
    inc r24
    sts SAVEGEN,r24
    brne PSavestart
    lds r24,SAVEGENHI
    inc r24
    sts SAVEGENHI,r24
PSavestart:
    sts 0x3dd4,r1
    ldi r24,1
    sts SAVEPH,r24
    ret

; Phase 1 invalidates the journal, 2..16 write the working image,
; and 17 commits it. 18..32 promote the journal to the selected slot,
; 33 commits that slot and 34 clears the journal. Each tick starts at
; most one page write, with the next call polling for completion.
pattern_write_tick:
    lds r24,SAVEPH
    tst r24
    breq PWreturn
    lds r18,0x01cf
    sbrs r18,7
    rjmp PWready
PWreturn:
    ret
PWready:
    push r16
    push r17
    push r28
    push r29
    lds r18,0x01cc
    ori r18,0x08
    sts 0x01cc,r18
    ldi r26,lo8(PAGEBUF)
    ldi r27,hi8(PAGEBUF)
    cpi r24,PWRITE
    brcs PWerase
    cpi r24,PJCOMMIT
    brcs PWstage
    breq PWjcommit
    cpi r24,PSCOMMIT
    brcs PWpromote
    breq PWslotcommit
PWerase:
    ldi r17,hi8(PJHDR)
    ldi r16,lo8(PJHDR)
    rjmp PWblank
PWjcommit:
    ldi r17,hi8(PJHDR)
    ldi r16,lo8(PJHDR)
    rjmp PWmark
PWslotcommit:
    call PWslot
    inc r17
    ldi r16,lo8(PHEADER)
PWmark:
    ldi r18,0x50
    st x+,r18
    ldi r18,26
    st x+,r18
    lds r18,SAVESLOT
    st x+,r18
    com r18
    st x+,r18
    lds r18,SAVEGEN
    st x+,r18
    com r18
    st x+,r18
    lds r18,SAVEGENHI
    st x+,r18
    com r18
    st x+,r18
    ldi r18,0xa5
    st x+,r18
    ldi r19,23
    rjmp PWfill
PWblank:
    ldi r19,32
PWfill:
    ldi r18,0xff
PWfillbyte:
    st x+,r18
    dec r19
    brne PWfillbyte
    rjmp PWwrite
PWstage:
    subi r24,PWRITE
    call PWoffset
    movw r16,r28
    subi r17,PJHIGH_NEG
PWstagebyte:
    movw r24,r28
    call pattern_addr
    ld r18,x
    ldi r30,lo8(PAGEBUF)
    ldi r31,hi8(PAGEBUF)
    mov r19,r28
    andi r19,31
    add r30,r19
    adc r31,r1
    st z,r18
    adiw r28,1
    cpi r19,31
    brne PWstagebyte
    rjmp PWwrite
PWpromote:
    subi r24,PPROMOTE
    call PWoffset
    call PWslot
    add r17,r29
    mov r16,r28
    movw r30,r28
    subi r31,PMAPJHIGH_NEG
    ldi r19,32
PWpromotebyte:
    ld r18,z+
    st x+,r18
    dec r19
    brne PWpromotebyte
PWwrite:
    call pattern_write_page
    lds r24,SAVEPH
    inc r24
    cpi r24,PFINISHED
    brcs PWadvance
    clr r24
PWadvance:
    sts SAVEPH,r24
    pop r29
    pop r28
    pop r17
    pop r16
    ret
PWoffset:
    ldi r25,32
    mul r24,r25
    movw r28,r0
    clr r1
    ret
PWslot:
    ldi r17,hi8(PSLOTA)
    lds r18,SAVESLOT
    tst r18
    breq PWslotdone
    ldi r17,hi8(PSLOTB)
PWslotdone:
    ret

; Write the prepared SRAM page at EEPROM byte address r16:r17.
; Disable EEPROM mapping when loading the NVM buffer. Restore CMD and
; interrupt enable after every protected operation.
pattern_write_page:
    lds r18,0x01cc
    andi r18,0xf7
    sts 0x01cc,r18
    lds r18,0x01cf
    sbrs r18,1
    rjmp PWPload
    ldi r20,0x36
    call PWPexec
PWPbusy:
    lds r18,0x01cf
    sbrc r18,7
    rjmp PWPbusy
PWPload:
    ldi r26,lo8(PAGEBUF)
    ldi r27,hi8(PAGEBUF)
    ldi r21,32
PWPbyte:
    ld r18,x+
    in r24,0x3f
    cli
    lds r19,0x01ca
    ldi r20,0x33
    sts 0x01ca,r20
    sts 0x01c0,r16
    sts 0x01c1,r17
    sts 0x01c2,r1
    sts 0x01c4,r18
    sts 0x01ca,r19
    out 0x3f,r24
    inc r16
    dec r21
    brne PWPbyte
    ldi r20,0x35
PWPexec:
    in r24,0x3f
    cli
    lds r19,0x01ca
    sts 0x01ca,r20
    ldi r18,0xd8
    ldi r25,1
    out 0x34,r18
    sts 0x01cb,r25
    sts 0x01ca,r19
    out 0x3f,r24
    ret
"""

ASM += r"""
; Preserve the track's original values on the first change of a Ctrl All
; gesture. Continuing to turn the same control keeps the same restore point.
; X is the parameter's track base. Preserve the Ctrl All working registers.
pattern_undo_capture:
    tst r18
    breq PUreturn
    push r20
    push r24
    lds r20,UNDOHELD
    tst r20
    breq PUcapture
    lds r20,UNDOEDIT
    lds r24,EDITPAT
    cp r20,r24
    brne PUcapture
    lds r20,UNDOPTR
    cp r20,r26
    brne PUcapture
    lds r20,UNDOPTRHI
    cp r20,r27
    breq PUdone
PUcapture:
    ldi r20,1
    sts UNDOHELD,r20
    lds r20,EDITPAT
    sts UNDOEDIT,r20
    sts UNDOPTR,r26
    sts UNDOPTRHI,r27
    ldi r30,lo8(UNDOBUF)
    ldi r31,hi8(UNDOBUF)
    ldi r24,16
PUcopy:
    ld r20,x+
    st z+,r20
    dec r24
    brne PUcopy
    lds r26,UNDOPTR
    lds r27,UNDOPTRHI
PUdone:
    pop r24
    pop r20
PUreturn:
    ret

pattern_revert:
    lds r26,UNDOPTR
    lds r27,UNDOPTRHI
    tst r27
    breq PRVdone
    lds r18,EDITPAT
    lds r19,UNDOEDIT
    cp r18,r19
    brne PRVdone
    ldi r30,lo8(UNDOBUF)
    ldi r31,hi8(UNDOBUF)
    ldi r24,16
PRVcopy:
    ld r18,z+
    st x+,r18
    dec r24
    brne PRVcopy
    sts UNDOPTRHI,r1
    sts UNDOHELD,r1
    sts 0x3dd4,r1
    MONITOR_UNDO_HOOK
PRVdone:
    ret

; Ctrl All supports both momentary use and tapping to latch. Ignore
; Shift+Lock and button gestures made outside the normal sequencer view.
; CTRLSTATE bits: 0 latched, 1 pressed, 2 used while held.
ctrl_update:
    lds r18,CTRLSTATE
    lds r19,0x3a57
    tst r19
    breq CULrelease
    tst r25
    breq CULused
    lds r19,0x3c29
    lds r20,0x2283
    or r19,r20
    brne CULused
    ori r18,2
    rjmp CULstore
CULused:
    ori r18,6
    rjmp CULstore
CULrelease:
    sbrs r18,1
    rjmp CULidle
    sbrc r18,2
    rjmp CULidle
    tst r25
    breq CULidle
    ldi r19,1
    eor r18,r19
CULidle:
    andi r18,1
    tst r18
    brne CULstore
    sts UNDOHELD,r1
CULstore:
    lds r19,CTRLSTATE
    cp r18,r19
    breq CULret
    sts CTRLSTATE,r18
    MONITOR_HEADER_HOOK
    ret

ctrl_active:
    lds r24,0x3a57
    tst r24
    brne CULret
    lds r24,CTRLSTATE
    andi r24,1
CULret:
    ret

; r24 = track, r18 = trim. At zero release every sounding note, including
; chord voices. The tick path retries releases if the MIDI ring was full.
trim_store:
    ldi r26,lo8(VTRIM)
    ldi r27,hi8(VTRIM)
    add r26,r24
    adc r27,r1
    st x,r18
    tst r18
    breq trim_silence
    ret
trim_silence:
    ldi r26,lo8(OFF)
    ldi r27,hi8(OFF)
    add r26,r24
    adc r27,r1
    st x,r1
    jmp noteoff

; Apply the track's temporary gain to a note-on velocity in r18.
; Center is unity, and active notes stay in the MIDI range 1..127.
trim_velocity:
    ldi r26,lo8(VTRIM)
    ldi r27,hi8(VTRIM)
    add r26,r17
    adc r27,r1
    ld r20,x
    mul r18,r20
    add r0,r0
    adc r1,r1
    add r0,r0
    adc r1,r1
    mov r18,r1
    clr r1
    cpi r18,128
    brcs TVmin
    ldi r18,127
    ret
TVmin:
    tst r18
    brne TVdone
    inc r18
TVdone:
    ret
"""
