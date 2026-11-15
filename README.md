# pc44-mod: step sequencer for the Faderfox PC44

[![Ko-fi](https://img.shields.io/badge/Ko--fi-noxend-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/noxend) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-blue)](LICENSE)

An unofficial extension of the Faderfox PC44 firmware **V01.01** that turns the controller into a
**4-track step sequencer with 16 steps each** – in the style of Modwerk, right on the hardware.
The normal controller functions stay intact: the sequencer is only active when the routing
**`SEq`** is selected in setup.

> **Note:** this is not a Faderfox product and is neither supported nor reviewed by Faderfox.
> The original firmware is **not** included in this repository (copyright Faderfox).
> Use at your own risk – you can always flash the original firmware again.

> **How this was made:** pc44-mod is vibecoded. The patches were written with an AI coding assistant (Claude), checked in an AVR emulator and tested on a real PC44 by the author. Reviews from people who know AVR assembly are very welcome.

## Features

| Area | Features |
|---|---|
| Per step | velocity, pitch (scale-based), note length (1/12 … 16 steps), probability 10–100 % and conditions 1:2 … 8:8, ratchet 1–4, chord type, nudge (microtiming ±½ step) |
| Per track (edit page) | pattern length 1–16, octave, speed ×1/8 … ×2, MIDI channel, direction (forward, backward, ping-pong, random), mode note / chord / pad |
| Global | tempo 30–250 BPM, shuffle, root note, 11 scales |
| Live | quantised mute (Shift + pot), clear track, **Ctrl all** (Lock + pot: change all active steps of a track relatively) |
| Clock | internal clock with MIDI clock output, or automatically synced to external MIDI clock (USB/DIN), start/continue/stop |
| Memory | patterns and settings are saved automatically to EEPROM (they survive power cycles) |
| Snap/Jump | the firmware's pot mode applies per step parameter |

The full manual (German) is in [`docs/PC44_SEq_Anleitung.pdf`](docs/PC44_SEq_Anleitung.pdf).

## Building the firmware

Requires Python 3.8 or newer, no other packages.

1. Download the original firmware **`PC44_V0101.syx`** (version 01.01) from Faderfox and put it in this folder.
2. Build:

   ```sh
   python3 build.py PC44_V0101.syx PC44_seq.syx
   ```

   The script checks at every patch location that the original bytes match, and stops for any other
   firmware version.
3. Send `PC44_seq.syx` to the PC44 like a normal firmware update with **Bome SendSX**
   (procedure as in the Faderfox manual).
4. In setup, use button 2 (routing) and choose the entry `SEq` after `rou6`.

Back to the original: flash `PC44_V0101.syx` the same way.

## How it works

The firmware of the ATxmega128A4U is not rewritten but patched:

- **`pc44tool.py`** – reads and writes the PC44's SysEx update format (pages, checksums).
- **`asm.py`** – small AVR assembler (subset of the instructions).
- **`avrdis.py`** – AVR disassembler.
- **`build.py`** – contains the sequencer code in assembly. It is placed after the original image; at a few places (main loop, pot handling, display, LEDs, MIDI receive, timer interrupts) jumps into the new code are inserted.

## Tests

The tests run in an AVR emulator (`tests/avrsim.py`, EEPROM/NVM model in `tests/eesim.py`) that executes the real
firmware image. They also need the original firmware (path can be changed with `PC44_ORIG`):

```sh
python3 tests/test_seq.py            # functional test of all features
python3 tests/test_interrupts.py 1   # inject interrupts at random points
```

`tests/build_seq20.py` is an older version and is only needed for the test that patterns from the
older storage format are carried over.

## Hardware notes

- ATxmega128A4U, 32 MHz. Only GPIOR0..3 store values; GPIOR4..15 always read 0 on this chip.
- The firmware uses EEPROM from 0x010 to 0x11F; the sequencer stores from 0x400.
- The bootloader accepts larger images than the original (tested up to 151 pages).

## Contributing

Ideas, bug reports and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Especially helpful: test on your PC44 and report back.

## Support

pc44-mod is free. If you like the sequencer: **[ko-fi.com/noxend](https://ko-fi.com/noxend)**

## Licence

The code in this repository (build and patch tools, assembler, disassembler, simulators, manual) is under the [MIT licence](LICENSE). It does **not** cover the Faderfox firmware: the original firmware is not included, remains under copyright and must be obtained from Faderfox. Faderfox and PC44 are names of their manufacturer; no affiliation with Faderfox.
