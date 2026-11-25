# PC44 flash update limit

Use **64 KiB (65,536 bytes)** as the total application image budget for
the stock Faderfox USB SysEx update path. The 64 KiB probe passed on the
tested PC44. The very next size, 257 chunks, stopped at `UdEr` during
upload. Each update chunk holds 256 flash bytes.

## Hardware results

| Application size | 256-byte chunks | Result |
| ---: | ---: | --- |
| 32 KiB | 128 | Passed, `P128` on the PC44 |
| 64 KiB | 256 | Passed |
| 64.25 KiB | 257 | `UdEr` during upload |
| 65 KiB | 260 | `UdEr` during upload |
| 128 KiB | 512 | Failed |

`UdEr` came from the updater before the 257- and 260-chunk probes could
run their flash readback. These results describe the observed update path
on the tested unit. The ATxmega128A4U has a 128 KiB application flash region
and a separate boot section. [Faderfox update instructions](https://www.faderfox.de/PDF/PC44%20update.pdf)
· [Microchip XMEGA A4U datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-8387-8-and16-bit-AVR-Microcontroller-XMEGA-A4U_Datasheet.pdf)

## Budget for firmware changes

Count the decoded application bytes, including stock code, patches, tables
and padding. SysEx encoding expands the file on disk. The 158-chunk
one-handed A/B Monitor build uses **39.5 KiB**, leaving **98 chunks
(24.5 KiB)** within the observed update budget.
