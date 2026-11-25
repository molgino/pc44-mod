"""USB Monitor telemetry and direct parameter edits for the PC44 sequencer."""
from patterns import PATTERN_REGIONS, SHADOW

# Wire field, indexed by the MPC editor. Each entry names its RAM base and
# specifies the number of valid indices and the inclusive value range.
EDIT_FIELDS = (
    ('V', 64, 0, 127), ('N', 64, 0, 127), ('P', 64, 0, 44),
    ('L', 64, 0, 15), ('R', 64, 1, 4), ('CT', 64, 0, 7), ('NUDGE', 64, 0, 12),
    ('TLEN', 4, 1, 16), ('SPD', 4, 0, 6), ('DIR', 4, 0, 3), ('MODE', 4, 0, 2),
    ('OCT', 4, 0, 6), ('CHN', 4, 0, 15),
    ('SCALE', 1, 0, 10), ('ROOT', 1, 0, 11),
    ('SWING', 1, 0, 6), ('BPM_REG', 1, 30, 250), ('MREQ', 0, 0, 0), ('VTRIM', 4, 0, 127),
)


def constants(firmware):
    # Old v25 save scratch, between the chord and nudge arrays.
    names = ('MRX_COUNT', 'MRX_COMMAND', 'MRX_TOKEN', 'MRX_SLOT', 'MRX_INDEX',
             'MRX_LOW', 'MRX_FIELD', 'MRX_HIGH', 'MRX_READY', 'MTX_BLOCK', 'MSTATUS')
    values = {name: 0x3ED0 + offset for offset, name in enumerate(names)}
    # Reuse the old runtime mute bytes for a four-block priority queue.
    values.update(MDIRTY=0x3E80, MDIRTY1=0x3E81, MDIRTY2=0x3E82, MDIRTY3=0x3E83,
                  MTRIM_DIRTY=0x3EDF)

    shadow = {}
    offset = SHADOW
    for address, size, *_ in PATTERN_REGIONS:
        shadow[address] = offset
        offset += size
    firmware = dict(firmware, BPM_REG=3)

    def addresses(field):
        current = firmware[field]
        other = shadow.get(current, current)
        return (current & 255, current >> 8, other & 255, other >> 8)

    header = ('TLEN', 'SPD', 'DIR', 'MODE', 'OCT', 'CHN', 'MREQ', 'MREQ', 'SCALE', 'ROOT', 'SWING')
    steps = ('V', 'N', 'P', 'L', 'R', 'CT', 'NUDGE')
    for symbol, fields in (('MON_HEADER_TABLE', header), ('MON_STEP_TABLE', steps)):
        values[symbol] = ', '.join(str(byte) for field in fields for byte in addresses(field))
    values['MON_EDIT_FIELDS'] = ', '.join(str(byte) for field, count, low, high in EDIT_FIELDS
                                        for byte in (*addresses(field), count, low, high, 0))
    return values


ASM = r"""
; USB only. The V01.01 routing table sends DIN input (USART D0) to
; USB output (USART C0) in rou4. Stock notes and clock still use both.
monitor_init:
    sts MRX_COUNT,r1
    sts MRX_READY,r1
    sts MTX_BLOCK,r1
    sts MDIRTY,r1
    sts MDIRTY1,r1
    sts MDIRTY2,r1
    sts MDIRTY3,r1
    sts MTRIM_DIRTY,r1
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
; Legacy edit: F0 7D 50 34 20 token slot index low F7.
; General edit: F0 7D 50 34 22 token slot index low field high F7.
; MIDI real-time messages may be interleaved without resetting the parser.
monitor_rx:
    cpi r28,0xf8
    brcs MRmode
    ret
MRmode:
    lds r24,ROUTING
    cpi r24,SEQ
    breq MRsetup
    rjmp MRreset
MRsetup:
    lds r24,0x3bf3
    lds r19,0x211a
    or r24,r19
    breq MRready
    rjmp MRreset
MRready:
    lds r24,MRX_READY
    tst r24
    brne MRreturn
    cpi r28,0xf0
    breq MRstart
    lds r24,MRX_COUNT
    tst r24
    breq MRreturn
    cpi r24,9
    brcs MRdata
    lds r19,MRX_COMMAND
    cpi r19,0x20
    breq MRend
    cpi r24,11
    breq MRend
MRdata:
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
    breq MRcommand
    cpi r28,0x22
    brne MRreset
MRcommand:
    sts MRX_COMMAND,r28
    rjmp MRnext
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

; Schedule the changed slot, lane and row ahead of the normal sweep.
; Entries are (block * 8 + track * 2 + slot + 1); zero is empty.
monitor_queue_step:
    lds r18,0x3dd8
    ldi r30,lo8(monitor_modes)
    ldi r31,hi8(monitor_modes)
    add r30,r18
    adc r31,r1
    call lpmz
    tst r20
    brne MQstep
    ret
MQstep:
    mov r18,r24
    swap r18
    andi r18,3
    rjmp MQkey
monitor_queue_header:
    lds r18,EDTRK
    clr r20
MQkey:
    add r18,r18
    add r20,r20
    add r20,r20
    add r20,r20
    add r18,r20
    lds r20,EDITPAT
    add r18,r20
    inc r18
    ldi r26,lo8(MDIRTY)
    ldi r27,hi8(MDIRTY)
    ldi r19,4
MQscan:
    ld r20,x+
    cp r20,r18
    breq MQreturn
    tst r20
    breq MQstore
    dec r19
    brne MQscan
    ; The sweep covers any older data displaced by a fast group gesture.
    ldi r20,0x80
    sts MTX_BLOCK,r20
MQstore:
    sbiw r26,1
    st x,r18
MQreturn:
    ret

monitor_queue_trim:
    ldi r20,1
    sts MTRIM_DIRTY,r20
    ret

monitor_queue_clear:
    mov r18,r24
    swap r18
    andi r18,3
    ldi r20,1
    call MQkey
monitor_undo:
monitor_resync:
    ; Bulk edits get a full sweep at one block per available tick.
    ldi r20,0x80
    sts MTX_BLOCK,r20
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
    ; Send changes to the active slot before any legacy blocks. Re-send
    ; the transport state periodically for clients that joined while stopped.
    call monitor_status
    tst r24
    brne MTdone
    lds r24,MDIRTY
    tst r24
    brne MTpriority
    lds r24,MTRIM_DIRTY
    tst r24
    brne MTtrim
    lds r24,0x3de1
    andi r24,63
    cpi r24,1
    breq MTtrim
    lds r25,MTX_BLOCK
    sbrc r25,7
    rjmp MTblock
    andi r24,3
    brne MTdone
MTblock:
    call monitor_block
    rjmp MTdone
MTpriority:
    call monitor_priority
    rjmp MTdone
MTtrim:
    call monitor_trims
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

; Foreground only: the ISR owns the request until MRX_READY is cleared.
; Result 0 = applied, 1 = save staging, 2 = invalid field/index/value.
monitor_edit:
    ldi r29,2
    lds r28,MRX_SLOT
    cpi r28,2
    brcs MEfield
    rjmp MEreply
MEinvalid:
    rjmp MEreply
MEfield:
    clr r16
    lds r17,MRX_LOW
    lds r18,MRX_COMMAND
    cpi r18,0x20
    breq MErange
    lds r16,MRX_FIELD
    cpi r16,19
    brcc MEinvalid
    lds r18,MRX_HIGH
    cpi r18,2
    brcc MEinvalid
    tst r18
    breq MErange
    ori r17,0x80
MErange:
    ldi r30,lo8(monitor_fields)
    ldi r31,hi8(monitor_fields)
    mov r18,r16
    add r18,r18
    add r18,r18
    add r18,r18
    add r30,r18
    adc r31,r1
    adiw r30,4
    lds r18,MRX_INDEX
    call lpmz
    cp r18,r20
    brcc MEinvalid
    adiw r30,1
    call lpmz
    cp r17,r20
    brcs MEinvalid
    adiw r30,1
    call lpmz
    cp r20,r17
    brcs MEinvalid
    ldi r29,1
    lds r24,SAVEPH
    tst r24
    breq MEwrite
    cpi r24,PPROMOTE
    brcs MEreply
MEwrite:
    sbiw r30,6
    lds r24,EDITPAT
    cp r28,r24
    breq MEstore
    adiw r30,2
MEstore:
    call monitor_pointer
    add r26,r18
    adc r27,r1
    cpi r16,16
    breq MEtempo
    cpi r16,18
    breq MEtrim
    st x,r17
    rjmp MEok
MEtrim:
    mov r24,r18
    mov r18,r17
    call trim_store
    call monitor_queue_trim
    rjmp MEok
MEtempo:
    call monitor_set_tempo
MEok:
    clr r29
MEreply:
    call monitor_begin
    lds r24,MRX_COMMAND
    inc r24
    call monitor_byte
    ldi r28,0
    ldi r16,4
    lds r24,MRX_COMMAND
    cpi r24,0x20
    breq MEarg
    ldi r16,6
MEarg:
    ldi r26,lo8(MRX_TOKEN)
    ldi r27,hi8(MRX_TOKEN)
    add r26,r28
    adc r27,r1
    ld r24,x
    call monitor_byte
    inc r28
    cp r28,r16
    brne MEarg
    mov r24,r29
    call monitor_byte
    call monitor_end
    sts MRX_READY,r1
    ret

; Keep the internal clock setting while leaving an external clock in control.
monitor_set_tempo:
    out 0x03,r17
    mov r18,r17
    subi r18,BPMMIN
    ldi r30,lo8(pertab)
    ldi r31,hi8(pertab)
    add r30,r18
    adc r31,r1
    add r30,r18
    adc r31,r1
    call lpmz
    mov r18,r20
    adiw r30,1
    call lpmz
    in r19,0x3f
    cli
    sts INTPER,r18
    sts INTPER1,r20
    lds r24,EXT
    tst r24
    brne MTEskip
    sts 0x0a36,r18
    sts 0x0a37,r20
MTEskip:
    out 0x3f,r19
    ret

monitor_trims:
    sts MTRIM_DIRTY,r1
    call monitor_begin
    ldi r24,0x38
    call monitor_byte
    clr r16
MTRnext:
    ldi r26,lo8(VTRIM)
    ldi r27,hi8(VTRIM)
    add r26,r16
    adc r27,r1
    ld r24,x
    call monitor_byte
    inc r16
    cpi r16,4
    brne MTRnext
    jmp monitor_end

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
    lds r24,0x3de1
    andi r24,63
    breq MSsend
    mov r24,r28
    tst r24
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
    call monitor_end
    ldi r24,1
    ret

monitor_status_byte:
    cpi r16,4
    breq MSflags
    ldi r26,lo8(CPOS)
    ldi r27,hi8(CPOS)
    add r26,r16
    adc r27,r1
    ld r24,x
    andi r24,15
    ldi r26,lo8(VTRIM)
    ldi r27,hi8(VTRIM)
    add r26,r16
    adc r27,r1
    ld r18,x
    tst r18
    brne MSfires
    ori r24,0x10
    ret
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

; Alternating playing and inactive slot per track. Send headers and
; velocities for all tracks first. Read either RAM copy without swapping.
; r29: bit 0 slot, bit 6 inactive, bit 7 read from shadow.
monitor_priority:
    lds r28,MDIRTY
    lds r24,MDIRTY1
    sts MDIRTY,r24
    lds r24,MDIRTY2
    sts MDIRTY1,r24
    lds r24,MDIRTY3
    sts MDIRTY2,r24
    sts MDIRTY3,r1
    dec r28
    mov r29,r28
    andi r29,1
    ori r29,0x40
    rjmp MBsource

monitor_block:
    lds r28,MTX_BLOCK
    mov r24,r28
    inc r24
    sbrc r24,6
    clr r24
    sts MTX_BLOCK,r24
    andi r28,63
    lds r29,PLAYPAT
    sbrs r28,0
    rjmp MBsource
    ldi r18,0x41
    eor r29,r18
MBsource:
    lds r18,EDITPAT
    mov r24,r29
    andi r24,1
    cp r18,r24
    breq MBbegin
    ori r29,0x80
MBbegin:
    lsr r28
    mov r16,r28
    andi r16,3
    lsr r28
    lsr r28
    call monitor_begin
    mov r24,r28
    ori r24,0x10
    sbrc r29,6
    ori r24,0x20
    call monitor_byte
    mov r24,r16
    sbrs r29,6
    rjmp MBaddress
    sbrc r29,0
    ori r24,4
MBaddress:
    call monitor_byte
    clr r17
MBvalues:
    call monitor_block_byte
    call monitor_byte
    inc r17
    cpi r17,16
    brne MBvalues
    jmp monitor_end

monitor_block_byte:
    tst r28
    breq MBheader
    ldi r30,lo8(monitor_steps)
    ldi r31,hi8(monitor_steps)
    mov r18,r28
    dec r18
    add r18,r18
    add r18,r18
    add r30,r18
    adc r31,r1
    call monitor_block_pointer
    mov r18,r16
    swap r18
    add r18,r17
    rjmp MBload
MBheader:
    cpi r17,6
    breq MBmute
    cpi r17,7
    breq MBmute
    cpi r17,11
    brcc MBextra
    ldi r30,lo8(monitor_header)
    ldi r31,hi8(monitor_header)
    mov r18,r17
    add r18,r18
    add r18,r18
    add r30,r18
    adc r31,r1
    call monitor_block_pointer
    clr r18
    cpi r17,8
    brcc MBload
    mov r18,r16
MBload:
    add r26,r18
    adc r27,r1
    ld r24,x
    ret
MBmute:
    ldi r26,lo8(VTRIM)
    ldi r27,hi8(VTRIM)
    add r26,r16
    adc r27,r1
    ld r18,x
    clr r24
    tst r18
    brne MBmute_done
    inc r24
MBmute_done:
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
    jmp ctrl_active
MBslot:
    mov r24,r29
    andi r24,1
    ret

monitor_block_pointer:
    sbrc r29,7
    adiw r30,2
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

monitor_modes:
    .byte 0, 1, 2, 0, 3, 5, 4, 0, 0, 0, 0, 0, 0, 0, 6, 7
monitor_header:
    .byte MON_HEADER_TABLE
monitor_steps:
    .byte MON_STEP_TABLE
monitor_fields:
    .byte MON_EDIT_FIELDS
"""
