# Mitmachen bei pc44-mod

Danke fürs Mithelfen! Deutsch oder Englisch – beides ist willkommen.

## Fehler melden
[Issue anlegen](https://github.com/molgino/pc44-mod/issues/new/choose) mit Firmware-Version (nur V01.01 wird unterstützt), Commit von pc44-mod und Schritten zum Nachstellen.

## Code beitragen
1. Fork anlegen, Branch erstellen.
2. Original-Firmware `PC44_V0101.syx` selbst bei Faderfox herunterladen (**nie ins Repository legen**).
3. Bauen und testen (Python 3.8+, keine Pakete nötig):
   ```sh
   python3 build.py PC44_V0101.syx PC44_seq.syx
   python3 tests/test_seq.py          # Sequencer im AVR-Emulator (braucht die Original-Firmware im Ordner
   python3 tests/test_interrupts.py   # oder per PC44_ORIG=/pfad/PC44_V0101.syx)
   ```
4. Pull Request gegen `main`, mit Hinweis, ob auf echter Hardware getestet.

## Regeln
- **Keine Faderfox-Firmware und keine größeren Teile davon** ins Repository, auch nicht disassembliert. Erlaubt sind die kurzen Prüf-Bytes an den Patch-Stellen.
- `build.py` muss bei einer falschen Firmware-Version abbrechen statt zu patchen.
- Mit einem Pull Request stimmst du zu, dass dein Beitrag unter der [MIT-Lizenz](LICENSE) steht.
