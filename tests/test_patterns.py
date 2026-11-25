#!/usr/bin/env python3
"""A/B controls, MIDI launch timing, and EEPROM recovery in the AVR emulator."""

from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build
import patterns
from eesim import EEAVR
from pc44tool import decode


def run_suite(flash, labels):
    events = []
    v = build.RAM['V']
    scale, root = 0x3de2, 0x3de8
    c = patterns.CONSTS
    a, b = patterns.SLOTS
    journal_header = patterns.JOURNAL + patterns.HEADER_OFFSET

    def boot(eeprom=None):
        m = EEAVR(flash, eeprom)
        m.stubs.update({
            0x407e: lambda _: None,
            0x3f0e: lambda _: None,
            0x687e: lambda _: None,
            0x3ac0: lambda _: None,
            0x1466: lambda _: None,
            0xa9a: lambda cpu: events.append((cpu.r[24], cpu.r[22], cpu.r[20])),
            0x3e6a: lambda _: None,
        })
        m.call(labels['init'])
        m.call(0x687a)
        assert m.mem[0x2218] == 8
        return m

    def hook(m):
        m.call(labels['hook'])

    def key(m, number):
        m.mem[0x2283] = m.mem[0x230e + number] = 1
        hook(m)
        hook(m)  # A held gesture must only execute once.
        m.mem[0x2283] = m.mem[0x230e + number] = 0
        hook(m)

    def tick(m, count, external=False):
        timeline = []
        for t in range(count):
            events.clear()
            if external:
                m.mem[0x09a0] = 0xf8
                m.call(labels['rxd0'])
            else:
                m.call(labels['tce0isr'])
            hook(m)
            timeline.extend((t, *msg) for msg in events)
        return timeline

    def set_pot(m, index, value, snap=0, stock_fallback=False):
        m.mem[0x3a56] = index
        m.mem[0x3df6] = value
        m.r[10] = 0
        m.r[24] = index if stock_fallback else snap
        m.mem[0x2b1a] = snap
        m.call(0x1336 if stock_fallback else 0x11e8)

    def finish_save(m):
        for _ in range(220):
            hook(m)
            if not m.mem[c['SAVEPH']] and not (m.rd(0x1cf) & 0x80):
                break
        assert not m.mem[c['SAVEPH']] and not m.busy
        assert not m.errors, m.errors

    # Exercise the patched stock setup entry points and verify that setup
    # loading, routing controls, and setup exits keep the user's EEPROM.
    m = boot()
    before_setup = bytes(m.ee)
    def unexpected_routing_write(_):
        raise AssertionError('unexpected stock routing write')

    m.stubs.update({
        0x416a: lambda _: None,
        0x5dba: lambda _: None,
        0x5e72: lambda _: None,
        0x4542: unexpected_routing_write,
    })
    for entry in (0x4156, 0x5bb2, 0x5bce, 0x5ca4, 0x5cb4):
        m.mem[0x2218] = 3
        m.call(entry)
        assert m.mem[0x2218] == 8
    for entry in (0x5da8, 0x5e60):
        m.call(entry)
    assert bytes(m.ee) == before_setup

    # Run the ADC and front-panel interrupt vectors, followed by the stock
    # main loop and actual display renderer. Stub unrelated USB/pot services.
    m = boot()
    del m.stubs[0x3ac0], m.stubs[0x3e6a]
    m.stubs.update({address: lambda _: None for address in (0xc36, 0xe92, 0x69d2)})

    def panel(shift=False, number=1, down=False, encoder=False, lock=False):
        m.mem[0x3a47] = 12
        m.mem[0x3a9d] = 4  # First encoder-switch ADC sample after the 68 pots.
        m.mem[0x0210] = 0 if encoder else 0xff
        m.call(0x11c)
        assert m.mem[0x2fa3] == m.mem[0x0210]
        m.mem[0x0668] = 0xff ^ (0x02 if shift else 0) ^ (0x10 if lock else 0)
        m.mem[0x0648] = 0 if down else 0x80
        m.mem[0x3a9d] = 0x10 + number - 1
        m.call(0x38)
        m.call(0x6980)
        assert m.sp == 0x3fff and m.r[1] == 0

    def panel_status(digits, keys):
        assert m.mem[0x2fe6:0x2fea] == bytes(digits)
        assert m.mem[0x3bf9:0x3bf9 + len(keys)] == bytes(keys)
        # The display renderer must propagate the digits to the scanner's
        # LED buffer, including clearing old segments when status changes.
        for index, segments in enumerate(digits):
            start = ((index & 2) + 2) * 8 + (index & 1)
            for bit in range(8):
                pin = start + 2 * bit
                if pin != 0x2f:
                    assert m.mem[0x3bf9 + pin] == (3 if segments & (1 << bit) else 0)

    panel()
    panel_status([0x77, 0x40, 0, 0x77], [3, 0, 0, 0, 3, 0, 0, 0])
    # The stock scanner drives both lit and unlit key LEDs from this buffer.
    for key_index, expected in ((0, 0), (1, 1)):
        m.mem[0x3a9d] = 7 + 8 * key_index
        m.call(0x38)
        assert m.mem[0x0664] & 1 == expected
    for number in range(1, 9):
        panel(number=number, down=True)
        assert m.mem[0x3bf8 + number] == 3
        panel(number=number)
    assert m.mem[2] == 0  # Keys 7 and 8 are reachable in the play view.

    panel(lock=True)
    assert m.mem[0x3c01] == 3 and m.mem[0x212f] == 0
    m.mem[0x3a9d] = 3  # Scan the dedicated Lock LED on the physical output.
    m.call(0x38)
    assert m.mem[0x0664] & 1 == 0
    set_pot(m, 0, 100)
    set_pot(m, 0, 115)
    assert m.mem[v] == m.mem[v + 4] == 115
    panel(lock=True, number=1, down=True)
    assert m.mem[0x3c01] == m.mem[0x3bf9] == 3
    panel(number=1)
    assert m.mem[0x3c01] == m.mem[0x212f] == 0
    m.mem[0x3a9d] = 3
    m.call(0x38)
    assert m.mem[0x0664] & 1 == 1
    panel(shift=True, number=6, down=True)
    assert m.mem[0x3bfe] == 3 and m.mem[v] == m.mem[v + 4] == 100
    panel(shift=True, number=6)
    # Tap Lock to latch it, then pass through the stock raw movement
    # comparison path with Lock physically released.
    panel(lock=True)
    panel()
    assert m.mem[c['CTRLSTATE']] & 1 and m.mem[0x3c01] == 3
    set_pot(m, 0, 125, stock_fallback=True)
    assert m.mem[v] == m.mem[v + 4] == 110
    panel(lock=True)
    panel()
    assert not m.mem[c['CTRLSTATE']] and m.mem[0x3c01] == 0
    panel(shift=True, number=6, down=True)
    assert m.mem[v] == m.mem[v + 4] == 100
    panel(shift=True, number=6)
    panel(shift=True, lock=True)
    panel(shift=True)
    panel()
    assert m.mem[0x220e] == 2 and m.mem[0x3c02]
    for number in range(1, 8):
        panel(number=number, down=True)
        panel(number=number)
        assert m.mem[0x3bf8 + number] == 3
    panel(encoder=True)
    assert m.mem[0x3e8d] == 9
    m.mem[0x3bf8] = m.mem[0x213e] = 1
    panel()
    assert m.mem[0x3ded] == 1
    m.mem[0x3ded] = 0
    panel(number=8, down=True)
    assert m.mem[2] == 1 and m.mem[0x3c00] == 3
    panel(number=8)
    panel(number=8, down=True)
    assert m.mem[2] == 0
    panel(number=8)
    panel(shift=True, lock=True)
    panel(shift=True)
    panel()
    assert m.mem[0x220e] == 0 and m.mem[0x3c02] == 0

    panel(encoder=True)
    assert m.mem[0x3dd4] == build.HOLD
    m.mem[0x3dd4] = 1
    m.call(labels['tce0isr'])
    panel(encoder=True)
    panel_status([0x77, 0x40, 0, 0x77], [3, 0, 0])
    panel(shift=True, number=4, down=True, encoder=True)
    panel_status([0x77, 0x40, 0, 0x7c], [3, 1, 0])
    panel(shift=True, number=1, down=True, encoder=True)
    assert m.mem[c['EDITPAT']] == 0  # A new gesture works while Copy is held.
    panel(shift=True, number=2, down=True, encoder=True)
    assert m.mem[c['EDITPAT']] == 1
    panel(shift=True, number=1)
    panel(shift=True, number=2)
    panel(shift=True, number=4)
    assert m.mem[0x230e] == 0  # Released encoder is seen by the stock loop.
    panel(number=7, down=True)
    panel(number=7)
    assert m.mem[2] == 1
    tick(m, 1)
    panel(shift=True, number=3, down=True)
    panel_status([0x77, 0x40, 0xfc, 0x7c], [3, 1, 3])
    panel(shift=True, number=3, down=True)
    assert m.mem[c['QUEUEPAT']] == 1  # Holding a key doesn't cancel the switch.
    panel(shift=True, number=3)
    tick(m, 191)
    assert m.mem[c['PLAYPAT']] == 0
    tick(m, 1)
    panel(shift=True)
    panel_status([0x7c, 0x40, 0, 0x7c], [0, 3, 0])
    panel(shift=True, number=1, down=True)
    panel_status([0x7c, 0x40, 0, 0x77], [3, 3, 0])
    panel(shift=True, number=1)
    panel_status([0x7c, 0x40, 0, 0x77], [1, 3, 0])
    panel(number=1)
    panel(number=8, down=True)
    panel(number=8)
    assert m.mem[2] == 0
    m.mem[v + 16:v + 24] = bytes((0, 0, 80, 0, 0, 0, 0, 0))
    set_pot(m, 18, 80)
    m.mem[0x3dd4] = 0
    panel()
    panel_status([0x7c, 0x40, 0, 0x77], [0, 0, 3, 0, 0, 0, 0, 0])
    panel(shift=True, number=5, down=True)
    panel_status([0x6d, 0x77, 0x3e, 0x79], [1, 3, 0, 0, 3])
    panel(number=5)
    finish_save(m)

    # Use the real encoder ADC switch and panel loop for the shortcut.
    m = boot()
    del m.stubs[0x3ac0], m.stubs[0x3e6a]
    m.stubs.update({address: lambda _: None for address in (0xc36, 0xe92, 0x69d2)})

    def click_ticks(count):
        for _ in range(count):
            m.r[24] = 0x10  # One call for every 16th stock panel scan.
            m.call(labels['pattern_panel_clock'])

    def double_click():
        panel(encoder=True)
        panel()
        click_ticks(64)
        panel(encoder=True)
        panel()

    panel(encoder=True)
    assert m.mem[0x3dd4] == build.HOLD and m.mem[c['PLAYPAT']] == 0
    m.mem[0x3a9d] = 0x0f
    m.call(0x38)
    assert m.mem[0x3a9d] == 0x10
    assert m.mem[c['ENC_WINDOW']] == c['ENC_DOUBLE_TICKS'] - 1
    panel(encoder=True)
    panel()
    click_ticks(5)
    panel(encoder=True)  # Bounce under the minimum interval.
    panel()
    assert m.mem[c['PLAYPAT']] == 0
    click_ticks(40)
    panel(encoder=True)
    panel()
    assert m.mem[c['PLAYPAT']] == 1 and m.mem[c['EDITPAT']] == 0
    panel_status([0x7c, 0x40, 0, 0x77], [])

    panel(encoder=True)
    panel()
    click_ticks(c['ENC_DOUBLE_TICKS'])
    panel(encoder=True)
    panel()
    assert m.mem[c['PLAYPAT']] == 1 and m.mem[c['ENC_WINDOW']]
    panel(shift=True)
    panel()
    assert not m.mem[c['ENC_WINDOW']]
    double_click()
    assert m.mem[c['PLAYPAT']] == 0

    panel(number=7, down=True)
    panel(number=7)
    tick(m, 1)
    double_click()
    assert m.mem[c['PLAYPAT']] == 0 and m.mem[c['QUEUEPAT']] == 1
    double_click()
    assert m.mem[c['PLAYPAT']] == 0 and m.mem[c['QUEUEPAT']] == 0xff
    double_click()
    tick(m, 191)
    assert m.mem[c['PLAYPAT']] == 0
    tick(m, 1)
    assert m.mem[c['PLAYPAT']] == 1 and m.mem[c['EDITPAT']] == 0

    m = boot()
    key(m, 2)
    set_pot(m, 0, 25, snap=1)
    assert m.mem[v] == 100  # Explicit Snap still applies in B.
    set_pot(m, 0, 100, snap=1)
    set_pot(m, 0, 50, snap=1)
    assert m.mem[v] == 50
    key(m, 1)
    set_pot(m, 0, 35, snap=0)
    assert m.mem[v] == 35  # Leaving B does not force Snap in A either.

    for external in (False, True):
        m = boot()
        m.mem[v:v + 64] = bytes(64)
        m.mem[v] = 100
        m.mem[v + 16] = 111
        pitch = 74
        m.mem[build.RAM['N']] = pitch
        m.mem[build.RAM['N'] + 16] = pitch
        a_note = build.tunetable()[pitch]
        b_note = build.tunetable()[128 + pitch] + 3
        assert a_note != b_note
        m.mem[0x3df2] = 5      # track 1 does not align with a bar
        m.mem[0x3df3] = 3
        m.mem[0x3e61] = 3      # track 2 runs at a different division
        m.mem[build.RAM['L']] = 15  # an A note is still held at the launch
        key(m, 4)
        assert m.mem[c['EDITPAT']] == 1 and m.mem[c['PLAYPAT']] == 0
        set_pot(m, 0, 30)
        assert m.mem[v] == 30  # Jump remains active when an A/B slot is selected.
        set_pot(m, 0, 70)
        assert m.mem[v] == 70

        # Shift+large pots edit the harmony of B while A keeps its own.
        m.mem[0x2283] = 1
        for pot, setting in ((64, 33), (65, 12)):
            set_pot(m, pot, 0)
            set_pot(m, pot, setting)
        m.mem[0x2283] = 0
        assert (m.mem[scale], m.mem[root]) == (1, 3)
        if external:
            m.mem[0x09a0] = 0xfa
            m.call(labels['rxd0'])
            hook(m)
        else:
            m.call(labels['seqstart'])
        first = tick(m, 1, external)
        assert (0, 0x90, a_note, 100) in first
        key(m, 3)
        m.call(labels['rendhook'])
        assert list(m.mem[0x2fe6:0x2fea]) == [0x77, 0x40, 0xfc, 0x7c]
        until_boundary = 95 if external else 191
        before = tick(m, until_boundary, external)
        assert all(vel != 70 for _, status, _, vel in before if status == 0x90)
        assert m.mem[c['PLAYPAT']] == 0
        launch = tick(m, 1, external)
        assert (0, 0x90, b_note, 70) in launch, launch
        assert (0, 0x91, b_note, 111) in launch, launch
        assert any(status == 0x80 for _, status, _, _ in launch)
        assert all(status not in (0xfa, 0xfc) for _, status, _, _ in launch)
        assert m.mem[c['PLAYPAT']] == 1 and m.mem[c['QUEUEPAT']] == 255
        assert m.mem[c['EDITPAT']] == 1
        key(m, 1)
        assert (m.mem[scale], m.mem[root]) == (0, 0)
        key(m, 3)  # Return to A without changing the slot being edited.
        key(m, 3)  # Cancel.
        assert m.mem[c['QUEUEPAT']] == 255
        key(m, 3)
        tick(m, until_boundary, external)
        assert (0, 0x90, a_note, 100) in tick(m, 1, external)
        assert m.mem[c['PLAYPAT']] == 0 and m.mem[c['QUEUEPAT']] == 255

    m = boot()
    key(m, 4)
    m.mem[0x3a57] = 1
    set_pot(m, 0, 100)
    set_pot(m, 0, 120)
    set_pot(m, 0, 127)
    assert m.mem[v] == 127
    m.mem[0x3a57] = 0
    key(m, 6)
    assert m.mem[v] == 100
    m.mem[0x3dc8] = 1
    key(m, 3)  # A stopped transport changes slots immediately.
    assert m.mem[c['PLAYPAT']] == 1
    set_pot(m, 64, 32)
    m.call(labels['seqstart'])
    notes = [vel for _, status, _, vel in tick(m, 1) if status == 0x90]
    assert notes == [50, 50, 50], notes
    assert m.mem[v] == 100  # Trim stays separate from step data.

    m = boot()
    m.mem[v] = 91
    m.mem[scale], m.mem[root] = 2, 4
    key(m, 5)
    m.mem[0x3dd4] = 100
    m.call(labels['rendhook'])
    assert m.mem[0x2fe6:0x2fea] == bytes((0x6d, 0x77, 0x3e, 0x79))
    finish_save(m)
    key(m, 4)
    assert (m.mem[scale], m.mem[root]) == (2, 4)  # Copy includes harmony.
    m.mem[v] = 57
    m.mem[scale], m.mem[root] = 5, 9
    m.mem[3] = 145
    key(m, 5)
    finish_save(m)
    original = bytes(m.ee)
    assert original[a + 64] == 91 and original[b + 64] == 57
    assert original[journal_header:journal_header + 32] == bytes([255]) * 32
    m = boot(original)
    assert m.mem[v] == 91 and m.mem[3] == 145
    assert (m.mem[scale], m.mem[root]) == (2, 4)
    key(m, 2)
    assert m.mem[v] == 57 and (m.mem[scale], m.mem[root]) == (5, 9)
    key(m, 1)
    key(m, 5)  # A is now newer; B must still load its own harmony.
    finish_save(m)
    m = boot(bytes(m.ee))
    assert (m.mem[scale], m.mem[root]) == (2, 4)
    key(m, 2)
    assert (m.mem[scale], m.mem[root]) == (5, 9)

    # Cut power after each successive page has been launched, including during
    # journal promotion. Before commit keep old B, afterwards recover new B.
    m.mem[v] = 83
    m.mem[scale], m.mem[root] = 6, 10
    m.call(labels['pattern_save'])
    seen_phases = set()
    for _ in range(220):
        phase = m.mem[c['SAVEPH']]
        if phase not in seen_phases:
            seen_phases.add(phase)
            if phase == 18:
                committed_journal = bytes(m.ee)
            recovered = boot(bytes(m.ee))
            assert recovered.mem[v] == 91
            expected = 83 if phase == 0 or phase >= 18 else 57
            if phase >= 18:
                finish_save(recovered)
            key(recovered, 2)
            assert (recovered.mem[scale], recovered.mem[root]) == ((6, 10) if expected == 83 else (5, 9))
            assert recovered.mem[v] == expected, (phase, recovered.mem[v], expected)
            assert recovered.ee[:patterns.JOURNAL] == original[:patterns.JOURNAL]
        if not phase:
            break
        hook(m)
    assert seen_phases == set(range(35))
    for written_bytes in range(10):
        torn = bytearray(committed_journal)
        torn[journal_header + written_bytes:journal_header + 32] = bytes([255]) * (32 - written_bytes)
        recovered = boot(torn)
        finish_save(recovered)
        key(recovered, 2)
        assert recovered.mem[v] == (83 if written_bytes == 9 else 57)

    # The ADC address transform must never reach the reclaimed SRAM, even
    # when the stock scan cursor is in the upper half of its 16-slot cycle.
    for pot in range(68):
        for sample in range(16):
            m.r[30], m.r[31], m.r[24] = pot, 0, sample
            m.call(labels['adc_addr'])
            assert m.Zr() == 0x2b63 + pot * 8 + sample % 8 < patterns.SHADOW

    for row in (4, 10, 11, 12):
        for group in range(8):
            for sample in (0, 7, 8, 15):
                index = (row - 4) * 8 + group
                m.mem[0x3a47] = row
                m.mem[0x3a9d] = sample * 8 + group
                m.mem[0x0210] = 173
                working = bytes(m.mem[patterns.SHADOW:patterns.ADC_END])
                m.call(0x782)
                if index < 68:
                    address = 0x2b63 + index * 8 + sample % 8
                else:
                    address = 0x2b63 + index * 16 + sample
                assert m.mem[address] == 173
                assert m.mem[patterns.SHADOW:patterns.ADC_END] == working

    m.stubs.update({0xf44: lambda _: None, 0x6954: lambda _: None})
    m.r[14], m.r[15] = 0x80, 0x37
    m.r[24], m.r[25] = 0x80, 0x37
    for routine in ('adc_scan_scale', 'adc_init_scale'):
        m.call(labels[routine])
        assert m.mem[0x31a4:0x31a6] == bytes((0, 0x6f))

    old_tuning = build.tunetable()
    for scale in range(len(build.SCALES)):
        m.mem[0x3de2] = scale
        for root in (0, 11):
            m.mem[0x3de8] = root
            for raw in range(128):
                m.r[18] = raw
                m.call(labels['tunenote'])
                assert m.r[18] == old_tuning[scale * 128 + raw] + root

    print('Front panel, A/B launch, ADC bounds, tuning and interrupted saves passed.')


if __name__ == '__main__':
    original = os.environ.get('PC44_ORIG', ROOT / 'PC44_V0101.syx')
    with TemporaryDirectory() as tmp:
        output = Path(tmp) / 'pc44.syx'
        labels = build.main(original, output)
        _, flash = decode(output.read_bytes())
        run_suite(flash, labels)
