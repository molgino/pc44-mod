"""PC44 Monitor 0.3.0 telemetry and a USB SysEx velocity edit."""
from patterns import PATTERN_REGIONS, SHADOW


def constants(firmware):
    # Use the old v25 EEPROM comparison scratch, now clear of save state.
    names = ('MRX_COUNT', 'MRX_TOKEN', 'MRX_SLOT', 'MRX_STEP', 'MRX_VEL',
             'MRX_READY', 'MTX_BLOCK', 'MSTATUS')
    values = {name: 0x3ED0 + offset for offset, name in enumerate(names)}

    velocity_shadow = SHADOW
    for address, size, *_ in PATTERN_REGIONS:
        if address == firmware['V']:
            break
        velocity_shadow += size
    values['MON_SHADOW_V'] = velocity_shadow

    # Header bytes 0–10 are RAM fields. The first eight are per track.
    header = ('TLEN', 'SPD', 'DIR', 'MODE', 'OCT', 'CHN', 'MUTE', 'MREQ', 'SCALE', 'ROOT', 'SWING')
    steps = ('V', 'N', 'P', 'L', 'R', 'CT', 'NUDGE')
    for symbol, fields in (('MON_HEADER_TABLE', header), ('MON_STEP_TABLE', steps)):
        values[symbol] = ', '.join(str(byte) for field in fields for byte in
                                   (firmware[field] & 255, firmware[field] >> 8))
    return values


ASM = r"""
; USB only. The V01.01 routing table sends DIN input (USART D0) to
; USB output (USART C0) in rou4. Stock notes and clock still use both.
monitor_init:
    sts MRX_COUNT,r1
    sts MRX_READY,r1
    sts MTX_BLOCK,r1
    ldi r26,lo8(MSTATUS)
    ldi r27,hi8(MSTATUS)
    ldi r19,5
    ldi r18,0xff
MIclear:
    st x+,r18
    dec r19
    brne MIclear
    ret

; Runs in the receive ISR. Preserve r28 (the original byte) and r25 (port).
; Accept exactly F0 7D 50 34 20 token slot step velocity F7.
; MIDI real-time messages may be interleaved without resetting the parser.
monitor_rx:
    cpi r28,0xf8
    brcc MRreturn
    lds r24,ROUTING
    cpi r24,SEQ
    brne MRreset
    lds r24,0x3bf3
    lds r19,0x211a
    or r24,r19
    brne MRreset
    lds r24,MRX_READY
    tst r24
    brne MRreturn
    cpi r28,0xf0
    breq MRstart
    lds r24,MRX_COUNT
    tst r24
    breq MRreturn
    cpi r24,9
    breq MRend
    cpi r28,0x80
    brcc MRreset
    cpi r24,5
    brcc MRarg
    cpi r24,1
    breq MRid
    cpi r24,2
    breq MRp
    cpi r24,3
    breq MRfour
    cpi r28,0x20
    rjmp MRmatch
MRid:
    cpi r28,0x7d
    rjmp MRmatch
MRp:
    cpi r28,0x50
    rjmp MRmatch
MRfour:
    cpi r28,0x34
MRmatch:
    brne MRreset
    rjmp MRnext
MRarg:
    ldi r26,lo8(MRX_TOKEN)
    ldi r27,hi8(MRX_TOKEN)
    mov r19,r24
    subi r19,5
    add r26,r19
    adc r27,r1
    st x,r28
MRnext:
    inc r24
    sts MRX_COUNT,r24
MRreturn:
    ret
MRstart:
    ldi r24,1
    sts MRX_COUNT,r24
    ret
MRend:
    cpi r28,0xf7
    brne MRreset
    ldi r24,1
    sts MRX_READY,r24
MRreset:
    sts MRX_COUNT,r1
    ret

; The main loop queues each complete packet in the stock USB TX ring.
; Leave room for the largest frame and skip a partially sent stock message.
monitor_tick:
    lds r24,0x3bf3
    tst r24
    brne MTret
    lds r24,0x220d
    tst r24
    brne MTret
    lds r24,0x3c36
    lds r25,0x2219
    sub r24,r25
    cpi r24,16
    brcc MTret
    push r16
    push r17
    push r28
    push r29
    lds r24,MRX_READY
    tst r24
    brne MTedit
    lds r24,0x3de1
    andi r24,7
    brne MTstatus
    call monitor_block
    rjmp MTdone
MTstatus:
    call monitor_status
    rjmp MTdone
MTedit:
    call monitor_edit
MTdone:
    pop r29
    pop r28
    pop r17
    pop r16
MTret:
    ret

; Foreground only: the ISR owns the request bytes until MRX_READY is set.
; Response code 0 = applied, 1 = saving, 2 = invalid slot or step.
monitor_edit:
    ldi r29,2
    lds r18,MRX_SLOT
    cpi r18,2
    brcc MEreply
    lds r19,MRX_STEP
    cpi r19,64
    brcc MEreply
    ldi r29,1
    lds r24,SAVEPH
    tst r24
    breq MEwrite
    cpi r24,PPROMOTE
    brcs MEreply
MEwrite:
    ldi r26,lo8(V)
    ldi r27,hi8(V)
    lds r24,EDITPAT
    cp r18,r24
    breq MEpickup
    ldi r26,lo8(MON_SHADOW_V)
    ldi r27,hi8(MON_SHADOW_V)
    rjmp MEcell
MEpickup:
    ldi r24,1
    sts PATPICKUP,r24
MEcell:
    add r26,r19
    adc r27,r1
    lds r24,MRX_VEL
    st x,r24
    clr r29
MEreply:
    call monitor_begin
    ldi r24,0x21
    call monitor_byte
    ldi r28,0
MEarg:
    ldi r26,lo8(MRX_TOKEN)
    ldi r27,hi8(MRX_TOKEN)
    add r26,r28
    adc r27,r1
    ld r24,x
    call monitor_byte
    inc r28
    cpi r28,4
    brne MEarg
    mov r24,r29
    call monitor_byte
    call monitor_end
    sts MRX_READY,r1
    ret

; Send playheads and the legacy playing/queued pattern status when changed.
monitor_status:
    clr r16
    clr r28
MScompare:
    call monitor_status_byte
    ldi r26,lo8(MSTATUS)
    ldi r27,hi8(MSTATUS)
    add r26,r16
    adc r27,r1
    ld r18,x
    cp r24,r18
    breq MScompare_next
    st x,r24
    ldi r28,1
MScompare_next:
    inc r16
    cpi r16,5
    brne MScompare
    tst r28
    brne MSsend
    ret
MSsend:
    call monitor_begin
    ldi r24,0x01
    call monitor_byte
    clr r16
MSvalue:
    ldi r26,lo8(MSTATUS)
    ldi r27,hi8(MSTATUS)
    add r26,r16
    adc r27,r1
    ld r24,x
    call monitor_byte
    inc r16
    cpi r16,5
    brne MSvalue
    jmp monitor_end

monitor_status_byte:
    cpi r16,4
    breq MSflags
    ldi r26,lo8(CPOS)
    ldi r27,hi8(CPOS)
    add r26,r16
    adc r27,r1
    ld r24,x
    andi r24,15
    ldi r26,lo8(MUTE)
    ldi r27,hi8(MUTE)
    add r26,r16
    adc r27,r1
    ld r18,x
    tst r18
    breq MSqueued_mute
    ori r24,0x10
MSqueued_mute:
    ldi r26,lo8(MREQ)
    ldi r27,hi8(MREQ)
    add r26,r16
    adc r27,r1
    ld r19,x
    cp r18,r19
    breq MSfires
    ori r24,0x20
MSfires:
    ldi r26,lo8(CACT)
    ldi r27,hi8(CACT)
    add r26,r16
    adc r27,r1
    ld r18,x
    tst r18
    breq MSret
    ori r24,0x40
MSret:
    ret
MSflags:
    lds r24,PLAYPAT
    add r24,r24
    in r18,0x02
    or r24,r18
    lds r18,QUEUEPAT
    cpi r18,0xff
    breq MSext
    swap r18
    ori r18,8
    or r24,r18
MSext:
    lds r18,EXT
    tst r18
    breq MSret
    ori r24,0x40
    ret

; The old Monitor has one grid shared with its playheads. Stream the playing
; pattern. If the user is editing the other slot, temporarily use the same
; exchange routine used by playback.
monitor_block:
    lds r18,PLAYPAT
    lds r29,EDITPAT
    eor r29,r18
    breq MBbegin
    clr r24
    call pattern_buffer
MBbegin:
    lds r28,MTX_BLOCK
    mov r24,r28
    inc r24
    andi r24,31
    sts MTX_BLOCK,r24
    mov r16,r28
    lsr r16
    lsr r16
    lsr r16
    andi r28,7
    call monitor_begin
    mov r24,r28
    ori r24,0x10
    call monitor_byte
    mov r24,r16
    call monitor_byte
    clr r17
MBvalues:
    call monitor_block_byte
    call monitor_byte
    inc r17
    cpi r17,16
    brne MBvalues
    call monitor_end
    tst r29
    breq MBret
    clr r24
    jmp pattern_buffer
MBret:
    ret

monitor_block_byte:
    tst r28
    breq MBheader
    ldi r30,lo8(monitor_steps)
    ldi r31,hi8(monitor_steps)
    mov r18,r28
    dec r18
    add r18,r18
    add r30,r18
    adc r31,r1
    call monitor_pointer
    mov r18,r16
    swap r18
    add r18,r17
    rjmp MBload
MBheader:
    cpi r17,11
    brcc MBextra
    ldi r30,lo8(monitor_header)
    ldi r31,hi8(monitor_header)
    mov r18,r17
    add r18,r18
    add r30,r18
    adc r31,r1
    call monitor_pointer
    clr r18
    cpi r17,8
    brcc MBload
    mov r18,r16
MBload:
    add r26,r18
    adc r27,r1
    ld r24,x
    ret
MBextra:
    cpi r17,11
    brne MBtempo_low
    in r24,0x03
    add r24,r24
    clr r24
    adc r24,r1
    ret
MBtempo_low:
    cpi r17,12
    brne MBfocus
    in r24,0x03
    andi r24,0x7f
    ret
MBfocus:
    cpi r17,13
    brne MBlock
    lds r24,LASTROW
    swap r24
    andi r24,3
    ret
MBlock:
    cpi r17,14
    brne MBslot
    lds r24,0x3a57
    ret
MBslot:
    lds r24,PLAYPAT
    ret

monitor_pointer:
    call lpmz
    mov r26,r20
    adiw r30,1
    call lpmz
    mov r27,r20
    ret

monitor_begin:
    sts 0x08a3,r1
    ldi r24,0xf0
    call monitor_byte
    ldi r24,0x7d
    call monitor_byte
    ldi r24,0x50
    call monitor_byte
    ldi r24,0x34
    rjmp monitor_byte
monitor_end:
    ldi r24,0xf7
    call monitor_byte
    ldi r24,0x28
    sts 0x08a3,r24
    ret
monitor_byte:
    ldi r22,1
    jmp 0x099a

monitor_header:
    .byte MON_HEADER_TABLE
monitor_steps:
    .byte MON_STEP_TABLE
"""
