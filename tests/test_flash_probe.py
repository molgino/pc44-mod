#!/usr/bin/env python3
"""Run the real flash verifier and stock display copy in the AVR emulator."""
from hashlib import sha256
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from avrsim import AVR
from flash_probe import APP_BYTES, DATA_START, HOOK, MAX_PAGES, MIN_PAGES, probe_image
from pc44tool import PAGE, decode, encode

DIGITS = (0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f)


def shown(flash, labels, result, count):
    cpu = AVR(flash)
    # Return from the final idle loop to the harness after the stock LED copy.
    cpu.stubs[labels["probe_wait"]] = lambda _: None
    cpu.mem[0x3b] = 2
    cpu.mem[0x01ca] = 3
    cpu.call(HOOK, maxsteps=850_000)
    expected = bytes(({"P": 0x73, "E": 0x79}[result],
                      *(DIGITS[int(n)] for n in f"{count:03d}")))
    assert cpu.mem[0x2fe6:0x2fea] == expected, cpu.mem[0x2fe6:0x2fea].hex()
    for index, segment in enumerate(expected):
        start = ((index & 2) + 2) * 8 + (index & 1)
        for bit in range(8):
            pin = start + 2 * bit
            if pin != 0x2f:
                assert cpu.mem[0x3bf9 + pin] == (3 if segment & (1 << bit) else 0)
    assert cpu.mem[0x3b] == 2 and cpu.mem[0x01ca] == 3
    assert cpu.sp == 0x3fff and cpu.r[1] == 0


def run(header, stock):
    image, labels = probe_image(stock, MAX_PAGES)
    assert len(image) == APP_BYTES == 0x20000
    assert image[:HOOK] == stock[:HOOK] and image[HOOK + 4:len(stock)] == stock[HOOK + 4:]
    assert len(image[DATA_START:]) == APP_BYTES - DATA_START
    wire = encode(image, header)
    roundtrip_header, roundtrip_image = decode(wire)
    assert (roundtrip_header[4] << 8 | roundtrip_header[5]) == MAX_PAGES - 1
    assert sha256(roundtrip_image).digest() == sha256(image).digest()

    shown(image, labels, "P", MAX_PAGES)
    shown(image[:0x10000], labels, "E", 0x10000 // PAGE + 1)
    corrupt_last = image[:-1] + bytes((image[-1] ^ 1,))
    shown(corrupt_last, labels, "E", MAX_PAGES)
    bad_first = bytearray(image)
    bad_first[DATA_START] ^= 1
    shown(bad_first, labels, "E", DATA_START // PAGE + 1)

    # The new image starts, but the uploader left a smaller probe's data
    # behind. This should fail even when the two seeds are identical.
    small, _ = probe_image(stock, 255)
    larger, larger_labels = probe_image(stock, 510)
    stale = larger[:DATA_START] + small[DATA_START:] + larger[len(small):]
    shown(stale, larger_labels, "E", DATA_START // PAGE + 1)

    for count in (MIN_PAGES - 1, MAX_PAGES + 1):
        try:
            probe_image(stock, count)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted out-of-range flash size")
    print("Full 128 KiB readback, 64 KiB truncation, stale chunks, final-byte corruption and LED output passed.")


if __name__ == "__main__":
    original = Path(os.environ.get("PC44_ORIG", ROOT / "PC44_V0101.syx"))
    run(*decode(original.read_bytes()))
