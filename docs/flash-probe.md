# PC44 flash size test

This temporary firmware checks whether the stock Faderfox updater can write
application images of different sizes. The PC44 holds the result on its own
four-character display. The MPC plugin can stay installed throughout the test.

## Before you start

Save A and B on the PC44 if you have unsaved edits. Keep the PC44 sequencer
firmware you want to return to and the original Faderfox PC44 V01.01 file on
your computer. The probe takes the place of the sequencer until you reflash it.
Use the direct USB connection and SysEx sender settings that already work
for this PC44. [Faderfox update instructions](https://www.faderfox.de/PDF/PC44%20update.pdf)
· [Original PC44 firmware](https://www.faderfox.de/pc44.html)

The generated files request writes within the 128 KiB application address
range. The probe itself reads flash and displays a result. It does no flash
programming or EEPROM writes. The tested PC44 accepted 64 KiB and stopped at
`UdEr` with 257 chunks (64.25 KiB). [Hardware results](flash-limits.md)

## Run the test

1. Disconnect the PC44 from the MPC. Hold the red **Shift** button while
   connecting the PC44 to your computer over USB. Release Shift once the
   display lights and wait for `Ud00`.
2. Set the SysEx sender's output to **Faderfox PC44**. Send
   `PC44_flash_040KiB.syx` first. Let the transfer finish. After a successful
   upload, reconnect normally if needed to boot the probe.
3. Read the result on the PC44. For this file, **P160** is a successful check.
   If it does not pass, try the **32 KiB** file (`P128`). If 32 KiB passes
   and 40 KiB fails repeatedly, narrow that interval first.
4. Once the 40 KiB file passes, try **64 KiB** (`P256`). To check the
   observed boundary on another unit, generate the **257-chunk** file below.
   If it passes, the higher sizes help find that setup's limit.
5. When finished, return to update mode with **Shift + USB** and send your
   working sequencer firmware or the original V01.01 file.

The sizes below refer to flash bytes. SysEx encoding makes the files larger
on disk.

| Flash size | Full pass | Flash size | Full pass |
| ---: | --- | ---: | --- |
| 32 KiB | `P128` | 65 KiB | `P260` |
| 40 KiB | `P160` | 80 KiB | `P320` |
| 48 KiB | `P192` | 96 KiB | `P384` |
| 56 KiB | `P224` | 112 KiB | `P448` |
| 64 KiB | `P256` | 128 KiB | `P512` |

## Interpret the display

- **P###** matching the file means the PC44 started the selected probe and
  read back the full test region through the last byte of that image. Each
  chunk is 256 bytes. **P512** reaches address `0x1FFFF`, the last byte of the
  application region. [Microchip XMEGA A4U datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-8387-8-and16-bit-AVR-Microcontroller-XMEGA-A4U_Datasheet.pdf)
- **E###** is the first unreadable or mismatching chunk, counted from one.
  **E257** is the first chunk above 64 KiB. The test pattern starts at address
  `0x6E00`, so the earliest possible mismatch is **E111**.
- A different **P###**, a blank display, or a repeatable **UdEr** leaves that
  size unverified. On **UdEr**, stop sending, tap **Shift** to return to
  `Ud00`, and retry the same size once. If a formerly passing smaller file
  still passes using the same setup, use those two sizes to narrow the
  observed limit. A transfer error alone can also come from the sender or
  cable. [Faderfox update instructions](https://www.faderfox.de/PDF/PC44%20update.pdf)

Record the **file size**, the **exact display**, and whether you saw it after
a normal power cycle. For example, `64 KiB P256, 65 KiB E257 after reboot`.

## Generate a size between two results

The included Python 3 generator needs the original PC44 V01.01 SysEx as its
template. Run the command from the unpacked kit folder, alongside the
included Python files. It creates a new file and protects any existing
file at the output path.

```sh
python3 flash_probe.py "PC44 V0101.SYX" PC44_flash_257chunks.syx --pages 257
```

For example, after `P256` at 64 KiB and a failure at 65 KiB (260 chunks),
try 258 chunks. Continue with the midpoint between the largest passing size
and the smallest repeatable failure. Each test costs one upload. A 128 KiB
pass already covers the application range.

The firmware compares every byte in the patterned region. Every chunk
includes the requested size and a page-and-bank-specific byte sequence, so
a stale chunk from a different probe size fails the comparison. The first
27.5 KiB contains the stock startup and diagnostic code. The host build checks
the original image before patching it. The AVR emulator checked the full
128 KiB path, truncation at 64 KiB, stale chunks, a corrupt final byte, and
the four-character display.
