#!/usr/bin/env python3
"""Both pattern streams and parameter edits through the real USB MIDI ISR."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build
from eesim import EEAVR
from patterns import CONSTS, PATTERN_REGIONS, SHADOW
from pc44tool import decode

PREFIX = bytes.fromhex('f0 7d 50 34')
USB_RX = 0x64
DIN_RX = 0x160
USB_TX = 0x6c
USB_DATA = 0x08a0
DIN_DATA = 0x09a0
USB_RING_READ = 0x2219
USB_RING_WRITE = 0x3c36
VELOCITY = build.RAM['V']


def run(flash, labels):
    machine = EEAVR(flash)
    machine.stubs.update({
        0x407e: lambda _: None,
        0x3ac0: lambda _: None,
    })
    notes = []
    machine.stubs[0xa9a] = lambda cpu: notes.append(tuple(cpu.r[i] for i in (24, 22, 20)))
    machine.call(labels['init'])
    machine.mem[0x2218] = 8

    def advance(ticks):
        packets = []
        for _ in range(ticks):
            machine.call(labels['tce0isr'])
            machine.call(labels['hook'])
            wire = bytearray()
            while machine.mem[USB_RING_READ] != machine.mem[USB_RING_WRITE]:
                wire.append(machine.mem[USB_DATA])
                machine.call(USB_TX)
            if wire:
                assert wire.startswith(PREFIX) and wire[-1] == 0xf7, wire.hex()
                assert all(value < 128 for value in wire[1:-1])
                packets.append(bytes(wire[4:-1]))
            assert machine.sp == 0x3fff and machine.r[1] == 0
        return packets

    def receive(data, vector=USB_RX):
        port = USB_DATA if vector == USB_RX else DIN_DATA
        for byte in data:
            machine.mem[port] = byte
            machine.call(vector)
            assert machine.sp == 0x3fff and machine.r[1] == 0

    def command(token, slot, step, velocity):
        return PREFIX + bytes((0x20, token, slot, step, velocity, 0xf7))

    def reply(token, slot, step, velocity, status=0):
        return bytes((0x21, token, slot, step, velocity, status))

    def parameter(token, slot, index, field, value):
        return (token, slot, index, value & 127, field, value >> 7)

    def edit(args, status=0):
        receive(PREFIX + bytes((0x22, *args, 0xf7)))
        assert bytes((0x23, *args, status)) in advance(1), args

    # The original USB transmitter, including its ring and interrupt, sends
    # every legacy block for each track. DIN receives no display traffic.
    packets = advance(512)
    assert machine.mem[0x3c3b] == machine.mem[0x2282] == 0
    assert bytes((0x01, 0, 0, 0, 0, 0)) in packets
    blocks = {tuple(packet[:2]): packet[2:] for packet in packets if len(packet) == 18}
    assert set(blocks) == ({(kind, track) for kind in range(0x10, 0x18) for track in range(4)} |
                           {(kind, track + 4) for kind in range(0x30, 0x38) for track in range(4)})
    assert bytes((0x38, 64, 64, 64, 64)) in packets
    assert blocks[0x10, 0] == bytes((16, 4, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 120, 0, 0, 0))
    assert blocks[0x11, 0] == bytes((100, 0, 0, 0) * 4)
    assert blocks[0x30, 4][-1] == 1
    assert blocks[0x31, 4] == blocks[0x11, 0]

    # No remote edits are collected in the stock Setup screen.
    machine.mem[0x3bf3] = 1
    receive(command(8, 0, 0, 23))
    machine.mem[0x3bf3] = 0
    assert reply(8, 0, 0, 23) not in advance(1)
    assert machine.mem[VELOCITY] == 100

    # A command needs the full header, data, and end marker on USB.
    frame = command(9, 0, 0, 74)
    receive(frame, DIN_RX)
    assert reply(9, 0, 0, 74) not in advance(1)
    assert machine.mem[VELOCITY] == 100
    for malformed in (frame[:-1] + b'\x90', frame[:-2] + b'\xf7', frame[:-1] + b'\x7f\xf7'):
        receive(malformed)
        assert reply(9, 0, 0, 74) not in advance(1)
        assert machine.mem[VELOCITY] == 100
    receive(frame[:-1])
    assert reply(9, 0, 0, 74) not in advance(1)
    assert machine.mem[VELOCITY] == 100
    receive(frame[-1:])
    assert reply(9, 0, 0, 74) in advance(1)
    assert machine.mem[VELOCITY] == 74

    # Playback responds at the normal scheduling point.
    machine.call(labels['seqstart'])
    advance(1)
    assert (0x90, 60, 74) in notes
    machine.call(labels['stopseq'])

    edit(parameter(15, 1, 0, 14, 5))
    assert machine.mem[0x3de8] == 0
    receive(command(10, 1, 0, 54))
    assert reply(10, 1, 0, 54) in advance(1)
    assert machine.mem[VELOCITY] == 74
    assert machine.mem[SHADOW + 64] == 54
    machine.r[24] = 1
    machine.call(labels['pattern_select'])
    assert machine.mem[VELOCITY] == 54
    packets = advance(512)
    assert any(p[:3] == bytes((0x11, 0, 74)) for p in packets)
    assert not any(p[:3] == bytes((0x11, 0, 54)) for p in packets)

    # Playback switches the legacy grid and its slot status together.
    machine.mem[CONSTS['QUEUEPAT']] = 1
    machine.call(labels['pattern_launch'])
    packets = advance(512)
    assert any(p[0] == 1 and (p[-1] >> 1) & 3 == 1 for p in packets)
    assert any(p[:3] == bytes((0x11, 0, 54)) for p in packets)
    assert all(p[-1] == 1 for p in packets if p[0] == 0x10)
    assert any(p[:2] == bytes((0x10, 0)) and p[11] == 5 for p in packets)
    notes.clear()
    machine.call(labels['seqstart'])
    advance(1)
    assert (0x90, 65, 54) in notes  # B's root and velocity take effect at launch.
    machine.call(labels['stopseq'])
    edit(parameter(16, 1, 0, 14, 0))

    # Reject out-of-range addresses and writes while staging an EEPROM save.
    for token, slot, step in ((11, 2, 0), (12, 1, 64)):
        receive(command(token, slot, step, 31))
        assert reply(token, slot, step, 31, 2) in advance(1)
    machine.call(labels['pattern_save'])
    receive(command(13, 1, 0, 87))
    assert reply(13, 1, 0, 87, 1) in advance(1)
    assert machine.mem[VELOCITY] == 54

    # Write all pattern parameters in inactive A while B keeps playing and
    # remains selected on the PC44. The active memory and the old stream stay B.
    machine.mem[CONSTS['SAVEPH']] = 0
    shadow = {}
    address = SHADOW
    for base, size, *_ in PATTERN_REGIONS:
        shadow[base] = address
        address += size
    pattern_values = (
        (0x3cc0, 63, 37), (0x3c80, 63, 124), (0x3d00, 63, 44), (0x3d88, 63, 15),
        (0x3d40, 63, 4), (0x3e90, 63, 7), (0x3ee0, 63, 12),
        (0x3df2, 3, 6), (0x3e60, 3, 6), (0x3e68, 3, 3), (0x3dc8, 3, 2),
        (0x3de9, 3, 6), (0x3e64, 3, 15), (0x3de2, 0, 10), (0x3de8, 0, 11),
    )
    machine.call(labels['seqstart'])
    for field, (base, index, value) in enumerate(pattern_values):
        offset = shadow[base + index] if field == 12 else shadow[base] + index
        before = machine.mem[base + index]
        edit(parameter(30 + field, 0, index, field, value))
        assert machine.mem[offset] == value, (field, offset, machine.mem[offset])
        assert machine.mem[base + index] == before
        assert machine.mem[CONSTS['EDITPAT']] == machine.mem[CONSTS['PLAYPAT']] == 1

    edit(parameter(60, 0, 0, 15, 5))
    edit(parameter(61, 0, 0, 16, 219))
    edit(parameter(62, 0, 3, 17, 1))
    edit(parameter(63, 0, 3, 18, 95))
    assert machine.mem[0x3ded] == 5
    assert machine.mem[3] == 219
    assert int.from_bytes(machine.mem[0x3e0a:0x3e0c], 'little') == build.per(219)
    assert machine.mem[0x3e87] == 1
    assert machine.mem[CONSTS['VTRIM'] + 3] == 95
    packets = advance(512)
    blocks = {tuple(packet[:2]): packet[2:] for packet in packets if len(packet) == 18}
    assert bytes((0x38, 64, 64, 64, 95)) in packets
    assert blocks[0x30, 3][:6] == bytes((6, 6, 3, 2, 6, 15))
    assert blocks[0x30, 3][8:13] == bytes((10, 11, 5, 1, 91))
    for field, (_, index, value) in enumerate(pattern_values[:7]):
        assert blocks[0x31 + field, 3][index % 16] == value
    assert blocks[0x10, 3][8:10] == bytes((0, 0))
    machine.call(labels['stopseq'])

    for field, index, value in ((19, 0, 1), (7, 4, 16), (7, 3, 0), (4, 1, 0),
                                (16, 0, 29), (16, 0, 251), (13, 1, 0), (0, 0, 270)):
        edit(parameter(72, 1, index, field, value), status=2)
    # Apply the slew-free mute immediately while stopped, even for an
    # explicitly selected A when B is the current hardware edit slot.
    edit(parameter(73, 0, 2, 17, 1))
    assert machine.mem[0x3e82] == machine.mem[0x3e86] == 1

    # Real-time bytes may arrive between any SysEx bytes. Leave stock timing
    # running; the deferred edit is applied through the foreground hook.
    machine.mem[CONSTS['SAVEPH']] = 0
    frame = command(14, 1, 0, 0)
    receive(frame[:6] + bytes((0xfa, 0xf8)) + frame[6:])
    machine.call(labels['hook'])
    wire = bytearray()
    while machine.mem[USB_RING_READ] != machine.mem[USB_RING_WRITE]:
        wire.append(machine.mem[USB_DATA])
        machine.call(USB_TX)
    assert PREFIX + reply(14, 1, 0, 0) + bytes((0xf7,)) in wire, wire.hex()
    assert machine.mem[2] and machine.mem[VELOCITY] == 0
    print('USB Monitor live/inactive telemetry and all parameter edits passed.')


if __name__ == '__main__':
    original = os.environ.get('PC44_ORIG', ROOT / 'PC44_V0101.syx')
    with TemporaryDirectory() as temporary:
        output = Path(temporary) / 'preview.syx'
        labels = build.main(original, output, enable_monitor=True)
        _, flash = decode(output.read_bytes())
        run(flash, labels)
