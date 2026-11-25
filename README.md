# pc44-mod: step sequencer for the Faderfox PC44

[![Ko-fi](https://img.shields.io/badge/Ko--fi-noxend-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/noxend) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-blue)](LICENSE)

An unofficial extension of the Faderfox PC44 firmware **V01.01** that turns the controller into a
**4-track step sequencer with 16 steps each** – in the style of Modwerk, right on the hardware.
This build runs in **`SEq`** mode. The setup routing control stays fixed to the sequencer. Each track keeps the same 16 physical step pots across two editable patterns, A and B.

> **Note:** this is not a Faderfox product and is neither supported nor reviewed by Faderfox.
> The original firmware is **not** included in this repository (copyright Faderfox).
> Use at your own risk – you can always flash the original firmware again.

> **How this was made:** pc44-mod is vibecoded. The original sequencer patch was written with an AI coding assistant (Claude), checked in an AVR emulator and tested on a real PC44 by the author. Reviews from people who know AVR assembly are very welcome.

## Features

| Area | Features |
|---|---|
| Per step | velocity, pitch (scale-based), note length (1/12 … 16 steps), probability 10–100 % and conditions 1:2 … 8:8, ratchet 1–4, chord type, nudge (microtiming ±½ step) |
| Per track (edit page) | pattern length 1–16, octave, speed ×1/8 … ×2, MIDI channel, direction (forward, backward, ping-pong, random), mode note / chord / pad |
| Per pattern | root note and 11 scales |
| Global | tempo 30–250 BPM and swing |
| Live | bar-quantized A/B switching, four track volumes with silence at zero, clear track, and reversible **Ctrl All** |
| Clock | internal clock with MIDI clock output, or automatically synced to external MIDI clock (USB/DIN), start/continue/stop |
| Memory | two explicitly saved EEPROM slots with interrupted-save recovery |
| Snap/Jump | your selected hardware pot mode applies across A/B switching and USB edits |

## A/B performance workflow

Hold **Shift** and press a numbered key in the sequencer play screen.

| Key | Action |
|---|---|
| 1 / 2 | Edit A / B. You can edit either slot while the other plays. |
| 3 | Switch playback between A and B. While playing, the switch occurs at the next 4/4 bar boundary and all four tracks restart together. Press again before the boundary to cancel. While stopped, the switch is immediate. |
| 4 | Copy the playing slot to the other slot and select the copy for editing. |
| 5 | Save the slot you are editing, along with the shared tempo and swing settings. Wait for `SAVE` to clear before switching the unit off. |
| 6 | Revert the most recent **Ctrl All** gesture with its original slot selected for editing. |

Double-press the encoder in the play view to switch playback between A and B with one hand. Make both presses within about 400 ms. While playing, the switch waits for the next bar. Double-press again before the boundary to cancel. While stopped, it switches immediately. A single press shows the tempo.

Start a groove in A with key **7**. Use **Shift + 4** to copy it to B, then turn the step pots to make a variation. Double-press the encoder to launch B. Key **8** stops playback.

The four large pots (65–68) control the playback velocity of tracks 1–4. The center is unity gain. At zero, the track releases held notes and suppresses new ones. Stored step velocities stay intact. Hold **Shift** and turn **pot 65** for the edit slot's root note or **pot 66** for its scale. To change shared swing, open Track Edit (**Shift + Lock**), press the encoder, then turn it. Buttons 1–7 still choose the track settings and button 8 controls playback.

The idle display shows the playing slot in the first digit and the edit slot in the fourth. The third digit shows a queued slot with its decimal point lit. For example, `A- b` means A plays and B is being edited. `A-b.b` means B is queued and is also the edit slot.

Hold **Shift** to see the pattern status on the numbered LEDs. LEDs **1** and **2** represent A and B. The playing slot is bright and the edit slot is dim if it differs. LED **3** lights while a switch is queued. When stopped, the LEDs show the active steps in the last row you touched. A numbered key lights at full brightness while held, including when another key is already down. Hold **Lock** and turn a step pot, or tap **Lock** to latch **Ctrl All** and free your hand. The Lock LED follows Ctrl All. Tap **Lock** again to turn off the latch. **Shift + Lock** opens and closes the track edit page.

At boot, A is selected. A saved pattern from earlier releases is imported as A. Until B has a saved version, it starts as a copy of A. Use **Shift + 5** in each slot to keep both versions across a reboot. Existing A/B saves keep the root and scale stored when each slot was last saved.

The older [German manual](docs/PC44_SEq_Anleitung.pdf) covers the original step editing and track parameters. Use the controls above for startup, pattern switching, and saving in this build.

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
4. Reboot the PC44. The sequencer screen opens with A selected.

### Restore the original firmware

The patch applies to the application image. The Faderfox updater runs at USB power-up in its original bootloader, and the sequencer leaves the stock routing preference in EEPROM available for the restored firmware.

1. Get the unmodified **PC44 Version 01.01** SysEx file from the [Faderfox PC44 downloads](https://www.faderfox.de/pc44.html).
2. With the PC44 unplugged, hold the red **Shift** key and connect USB. Release Shift when the display lights up, then wait for `Ud00`.
3. Select **Faderfox PC44** as the MIDI output in Bome Send SX or SysEx Librarian. Send the original V01.01 file. When the update finishes, reconnect USB.

If the updater reports `UdEr`, stop the transfer, tap Shift and wait for `Ud00`, then retry the transfer. [Faderfox update instructions](https://www.faderfox.de/PDF/PC44%20update.pdf)

## How it works

The firmware of the ATxmega128A4U is not rewritten but patched:

- **`pc44tool.py`** – reads and writes the PC44's SysEx update format (pages, checksums).
- **`asm.py`** – small AVR assembler (subset of the instructions).
- **`avrdis.py`** – AVR disassembler.
- **`build.py`** – applies the checked firmware patches and assembles the clock, playback, editing, and display code.
- **`patterns.py`** – defines the A/B controls, bar scheduling, pattern memory, and save journal.

## PC44 Monitor and MPC editor

[PC44 Editor](mpc-editor/README.md) is an MPC mixer insert that displays and
edits both A/B patterns over USB MIDI. The matched firmware continuously
streams both patterns, including while the sequencer is stopped. It preserves
the active-pattern telemetry used by the original PC44 Monitor. Changed
panel values and track volume take priority over the background sweep.

```sh
python3 build.py --monitor PC44_V0101.syx PC44_seq_ab_one_hand.syx
```

The USB protocol uses the SysEx prefix `F0 7D 50 34` and ends each packet
with `F7`. All fields are 7-bit bytes.

| Opcode | Payload | Direction |
| --- | --- | --- |
| `01` | `head0 head1 head2 head3 transport` | PC44 → editor |
| `10`–`17` | `track data[16]` for the playing slot | PC44 → editor |
| `30`–`37` | `slot*4+track data[16]` for the inactive slot or a changed block in either slot | PC44 → editor |
| `38` | `trim0 trim1 trim2 trim3` | PC44 → editor |
| `20` / `21` | `token slot index velocity` plus result in the reply | Legacy velocity edit / reply |
| `22` / `23` | `token slot index low field high` plus result in the reply | Parameter edit / reply |

Telemetry blocks contain the track header, velocity, pitch, chance, gate,
ratchet, chord and nudge, in that order. The parameter field IDs and bounds
are defined by `EDIT_FIELDS` in `monitor.py`. Field 17 is reserved for the
removed mute switch. Use field 18 (volume) with value zero to silence a track.
Slot 0/1 selects A/B. Index is a flattened step, track number, or zero
depending on the field.
Values use `low + 128 * high`. Result 0 means applied, 1 EEPROM save is
staging, and 2 invalid. Wait for the reply before sending another edit.

Edits update the working pattern. Select the desired edit slot on the PC44
and use **Shift + 5** to save. The Monitor build uses 158 application pages
and retains the Faderfox update flow and existing pattern save layout.
Build without `--monitor` for the 151-page standalone sequencer.

## PC44 flash size test

The temporary flash probe displays a pass count or the first mismatching
256-byte chunk on the PC44. Follow the separate instructions to test the
stock updater and return to your sequencer firmware. [Flash probe instructions](docs/flash-probe.md)

## Tests

The tests run in an AVR emulator (`tests/avrsim.py`, EEPROM/NVM model in `tests/eesim.py`) that executes the real
firmware image. They also need the original firmware (path can be changed with `PC44_ORIG`):

```sh
python3 tests/test_seq.py            # functional test of all features
python3 tests/test_interrupts.py 1   # inject interrupts at random points
python3 tests/test_patterns.py       # front panel, MIDI timing, and save recovery
python3 tests/test_monitor.py        # optional Monitor telemetry and USB edit round trip
python3 tests/test_flash_probe.py    # verifier and display for the flash probe
```

`tests/build_seq20.py` is an older version and is only needed for the test that patterns from the
older storage format are carried over.

## Hardware notes

- The stock USB SysEx update path has a verified working budget of **64 KiB**. See the [PC44 flash test results](docs/flash-limits.md).
- ATxmega128A4U, 32 MHz. Only GPIOR0..3 store values; GPIOR4..15 always read 0 on this chip.
- The firmware uses EEPROM from `0x010` to `0x11F`. The save journal starts at `0x200`, A at `0x400`, and B at `0x600`. The old save layout remains readable until A is first saved in the new format.
- The pot scanner averages eight ADC samples per pot, freeing SRAM for the inactive pattern. The patches retain the original pot scaling and the encoder switch sampling address.
- The standalone build uses 151 update pages. The Monitor build uses 158, or 39.5 KiB of the chip's 128 KiB application flash. The assembler currently uses 16-bit byte addresses for table reads. The space below 64 KiB gives about 24.5 KiB of address range beyond this build. [ATxmega128A4U datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-8387-8-and16-bit-AVR-Microcontroller-XMEGA-A4U_Datasheet.pdf)

## Contributing

Ideas, bug reports and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Especially helpful: test on your PC44 and report back.

## Support

pc44-mod is free. If you like the sequencer: **[ko-fi.com/noxend](https://ko-fi.com/noxend)**

## Licence

The code in this repository (build and patch tools, assembler, disassembler, simulators, manual) is under the [MIT licence](LICENSE). It does **not** cover the Faderfox firmware: the original firmware is not included, remains under copyright and must be obtained from Faderfox. Faderfox and PC44 are names of their manufacturer; no affiliation with Faderfox.
