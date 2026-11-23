# Contributing to pc44-mod

Thanks for helping! English or German – both are welcome.

## Reporting bugs
[Open an issue](https://github.com/molgino/pc44-mod/issues/new/choose) with the firmware version (only V01.01 is supported), the pc44-mod commit and steps to reproduce.

## Contributing code
1. Fork the repository and create a branch.
2. Download the original firmware `PC44_V0101.syx` from Faderfox yourself (**never put it in the repository**).
3. Build and test (Python 3.8+, no packages needed):
   ```sh
   python3 build.py PC44_V0101.syx PC44_seq.syx
   python3 tests/test_seq.py          # sequencer in the AVR emulator (needs the original firmware in the folder
   python3 tests/test_interrupts.py   # or via PC44_ORIG=/path/PC44_V0101.syx)
   python3 tests/test_patterns.py     # A/B and interrupted-save regression tests
   ```
4. Open a pull request against `main` and say whether you tested on real hardware.

The project is vibecoded (written with an AI coding assistant, checked in the emulator and on hardware), so reviews of the existing patches are just as welcome as new features.

## Rules
- **No Faderfox firmware and no larger parts of it** in the repository, not even disassembled. The short check bytes at the patch locations are fine.
- `build.py` must stop for a wrong firmware version instead of patching.
- By opening a pull request you agree that your contribution is licensed under the [MIT licence](LICENSE).
