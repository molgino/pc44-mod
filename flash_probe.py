#!/usr/bin/env python3
"""Build a temporary PC44 firmware that checks its own flash after an upload."""
import argparse
import hashlib
from pathlib import Path

from asm import assemble, encode_line, self_test
from pc44tool import PAGE, decode, encode

APP_BYTES = 128 * 1024
MAX_PAGES = APP_BYTES // PAGE
CODE_START = 0x6D00
DATA_START = 0x6E00
MIN_PAGES = DATA_START // PAGE + 1
HOOK = 0x6982  # Stock call into the main loop, after board initialization.
HOOK_STOCK = bytes.fromhex("0e 94 1b 06")
STOCK_SHA256 = "91454fbb288459d4c6d6041a416242f5cd84f46b4af16df0ad3d7cc3722236d7"
KIT_SIZES_KIB = (32, 40, 48, 56, 64, 65, 80, 96, 112, 128)

PAGE_STRIDE = 17
BANK_STRIDE = 91

PROBE = """
; The stock startup has already initialized the LED scanner interrupt.
; Stop normal application work so knobs and buttons cannot change settings.
probe_entry:
    clr r1
    call probe_check
    sts 0x2fe6,r24
    movw r26,r16
    ldi r19,100
    call probe_digit
    sts 0x2fe7,r24
    ldi r19,10
    call probe_digit
    sts 0x2fe8,r24
    mov r18,r26
    call probe_glyph
    sts 0x2fe9,r24
    call probe_render
probe_wait:
    rjmp probe_wait

probe_render:
    ; 0x3a18 tail-calls the stock renderer with this saved frame.
    push r17
    push r28
    push r29
    jmp 0x3a18

; Return the P or E glyph in r24 and the display count in r17:r16.
; RAMPZ gives ELPM the right byte address above 64 KiB.
probe_check:
    in r25,0x3f
    cli
    push r25
    in r25,0x3b
    push r25
    lds r25,0x01ca
    push r25
    sts 0x01ca,r1
    ldi r16,START_PAGE
    clr r17
    ldi r21,PAGE_STRIDE
    ldi r22,FIRST_BYTE
    ldi r23,BANK_STRIDE
probe_page:
    out 0x3b,r17
    mov r31,r16
    clr r30
    ; Each chunk also carries this image's size, so a stale chunk from a
    ; different-size probe cannot pass even if the byte-pattern seeds match.
    elpm r24,z
    cpi r24,lo8(UPLOAD_PAGES)
    brne probe_bad
    inc r30
    elpm r24,z
    cpi r24,hi8(UPLOAD_PAGES)
    brne probe_bad
    inc r30
    mov r20,r22
    inc r20
    inc r20
probe_byte:
    elpm r24,z
    cp r24,r20
    brne probe_bad
    inc r20
    inc r30
    brne probe_byte
    add r22,r21
    inc r16
    brne probe_end
    inc r17
    add r22,r23
probe_end:
    cpi r16,lo8(UPLOAD_PAGES)
    brne probe_page
    cpi r17,hi8(UPLOAD_PAGES)
    brne probe_page
    ldi r24,0x73
    rjmp probe_restore
probe_bad:
    ; Convert the zero-based failing offset to a one-based chunk number.
    inc r16
    brne probe_error
    inc r17
probe_error:
    ldi r24,0x79
probe_restore:
    pop r25
    sts 0x01ca,r25
    pop r25
    out 0x3b,r25
    pop r25
    out 0x3f,r25
    ret

; Count one decimal digit by repeated subtraction, keeping the remainder.
probe_digit:
    clr r18
probe_subtract:
    sub r26,r19
    sbc r27,r1
    brcs probe_remainder
    inc r18
    rjmp probe_subtract
probe_remainder:
    add r26,r19
    adc r27,r1
probe_glyph:
    ldi r30,lo8(probe_digits)
    ldi r31,hi8(probe_digits)
    add r30,r18
    adc r31,r1
    lds r25,0x01ca
    sts 0x01ca,r1
    lpm r24,z
    sts 0x01ca,r25
    ret

probe_digits:
    .byte 0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f
"""


def probe_image(stock, pages):
    """Return the application image and AVR labels for the requested size."""
    if not MIN_PAGES <= pages <= MAX_PAGES:
        raise ValueError(f"Use {MIN_PAGES} to {MAX_PAGES} chunks of {PAGE} bytes")
    if (len(stock) != CODE_START or hashlib.sha256(stock).hexdigest() != STOCK_SHA256
            or stock[HOOK:HOOK + 4] != HOOK_STOCK):
        raise ValueError("Expected the unmodified PC44 V01.01 firmware")

    start_page = DATA_START // PAGE
    seed = ((pages & 0xff) + (pages >> 8)) & 0xff
    code, labels = assemble(PROBE, CODE_START, {
        "START_PAGE": start_page,
        "UPLOAD_PAGES": pages,
        "PAGE_STRIDE": PAGE_STRIDE,
        "BANK_STRIDE": BANK_STRIDE,
        "FIRST_BYTE": (seed + start_page * PAGE_STRIDE) & 0xff,
    })
    if CODE_START + len(code) > DATA_START:
        raise ValueError("Verifier overlaps the test region")

    image = bytearray(stock)
    image[HOOK:HOOK + 4] = encode_line("jmp", "probe_entry", HOOK, labels)
    image.extend(code)
    image.extend(b"\xff" * (DATA_START - len(image)))
    for page in range(start_page, pages):
        first = seed + page * PAGE_STRIDE + (page >> 8) * BANK_STRIDE
        image.extend((pages & 0xff, pages >> 8))
        image.extend((first + offset) & 0xff for offset in range(2, PAGE))
    return bytes(image), labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path, help="Original Faderfox PC44 V01.01 SysEx")
    parser.add_argument("output", type=Path, help="Output .syx, or a folder for --kit")
    sizes = parser.add_mutually_exclusive_group(required=True)
    sizes.add_argument("--pages", type=int, help="Total count of 256-byte update chunks")
    sizes.add_argument("--kib", type=int, help="Total application size in KiB")
    sizes.add_argument("--kit", action="store_true", help="Build the standard size ladder")
    args = parser.parse_args()
    self_test()
    if args.kit:
        jobs = [(kib * 1024 // PAGE, args.output / f"PC44_flash_{kib:03d}KiB.syx")
                for kib in KIT_SIZES_KIB]
    else:
        pages = args.pages if args.pages is not None else args.kib * 1024 // PAGE
        jobs = [(pages, args.output)]

    try:
        header, stock = decode(args.stock.read_bytes())
        if header[:4] != [8, 1, 1, 1]:
            raise ValueError("Expected the stock PC44 V01.01 SysEx header")
        for pages, path in jobs:
            image, _ = probe_image(stock, pages)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create protects the stock file and previous results.
            with path.open("xb") as out:
                out.write(encode(image, header))
            print(f"{path.name}: {len(image)} flash bytes, expect P{pages:03d}")
    except (OSError, ValueError, AssertionError) as error:
        parser.exit(1, f"flash_probe: {error or 'invalid V01.01 SysEx input'}\n")


if __name__ == "__main__":
    main()
