# pc44-mod: Step-Sequencer für den Faderfox PC44

Eine inoffizielle Erweiterung der Faderfox-PC44-Firmware **V01.01**, die aus dem Controller einen
**4-Spur-Step-Sequencer mit je 16 Steps** macht – im Stil von Modwerk, direkt auf der Hardware.
Die normalen Controller-Funktionen bleiben erhalten: Der Sequencer ist nur aktiv, wenn im Setup das
Routing **`SEq`** gewählt ist.

> **Hinweis:** Dies ist kein Produkt von Faderfox und wird von Faderfox weder unterstützt noch geprüft.
> Die Original-Firmware ist **nicht** in diesem Repository enthalten (Urheberrecht von Faderfox).
> Benutzung auf eigene Gefahr – die Original-Firmware lässt sich jederzeit wieder einspielen.

## Funktionen

| Bereich | Funktionen |
|---|---|
| Pro Step | Velocity, Tonhöhe (skalenbasiert), Notenlänge (1/12 … 16 Steps), Wahrscheinlichkeit 10–100 % und Bedingungen 1:2 … 8:8, Ratchet 1–4, Akkordart, Nudge (Microtiming ±½ Step) |
| Pro Spur (Edit-Seite) | Pattern-Länge 1–16, Oktave, Speed ×1/8 … ×2, MIDI-Kanal, Richtung (vorwärts, rückwärts, Pingpong, zufällig), Modus Note / Chord / Pad |
| Global | Tempo 30–250 BPM, Shuffle, Grundton, 11 Skalen |
| Live | quantisiertes Mute (Shift + Poti), Spur löschen, **Ctrl all** (Lock + Poti: alle aktiven Steps einer Spur relativ ändern) |
| Clock | interner Takt mit MIDI-Clock-Ausgang oder automatisch synchron zu externer MIDI-Clock (USB/DIN), Start/Continue/Stop |
| Speicher | Pattern und Einstellungen werden automatisch im EEPROM gesichert (übersteht Aus- und Einschalten) |
| Snap/Jump | der Poti-Modus der Firmware gilt pro Step-Parameter |

Die vollständige Bedienungsanleitung liegt unter [`docs/PC44_SEq_Anleitung.pdf`](docs/PC44_SEq_Anleitung.pdf).

## Firmware bauen

Voraussetzung: Python 3.8 oder neuer, keine weiteren Pakete.

1. Die Original-Firmware **`PC44_V0101.syx`** (Version 01.01) bei Faderfox herunterladen und in diesen Ordner legen.
2. Bauen:

   ```sh
   python3 build.py PC44_V0101.syx PC44_seq.syx
   ```

   Das Skript prüft an jeder Patch-Stelle, dass die Original-Bytes stimmen, und bricht bei einer anderen
   Firmware-Version ab.
3. `PC44_seq.syx` wie ein normales Firmware-Update mit **Bome SendSX** an den PC44 schicken
   (Vorgehen laut Faderfox-Anleitung).
4. Im Setup mit Taste 2 (Routing) hinter `rou6` den Eintrag `SEq` wählen.

Zurück zum Original: `PC44_V0101.syx` genauso einspielen.

## Wie es funktioniert

Die Firmware des ATxmega128A4U wird nicht neu geschrieben, sondern gepatcht:

- **`pc44tool.py`** – liest und schreibt das SysEx-Update-Format des PC44 (Seiten, Prüfsummen).
- **`asm.py`** – kleiner AVR-Assembler (Teilmenge der Befehle).
- **`avrdis.py`** – AVR-Disassembler.
- **`build.py`** – enthält den Sequencer-Code in Assembler. Er wird hinter das Original-Image gelegt; an wenigen Stellen (Hauptschleife, Poti-Verarbeitung, Anzeige, LEDs, MIDI-Empfang, Timer-Interrupts) werden Sprünge in den neuen Code eingesetzt.

## Tests

Die Tests laufen in einem AVR-Emulator (`tests/avrsim.py`, EEPROM/NVM-Modell in `tests/eesim.py`), der das echte
Firmware-Image ausführt. Sie brauchen ebenfalls die Original-Firmware (Pfad über `PC44_ORIG` änderbar):

```sh
python3 tests/test_seq.py            # Funktionstest aller Features
python3 tests/test_interrupts.py 1   # Interrupts an zufälligen Stellen einstreuen
```

`tests/build_seq20.py` ist eine ältere Version und wird nur für den Test gebraucht, dass Patterns aus dem
älteren Speicherformat übernommen werden.

## Hardware-Notizen

- ATxmega128A4U, 32 MHz. Nur GPIOR0..3 speichern Werte, GPIOR4..15 lesen auf diesem Chip immer 0.
- Die Firmware nutzt das EEPROM von 0x010 bis 0x11F, der Sequencer speichert ab 0x400.
- Der Bootloader akzeptiert grössere Images als das Original (getestet bis 151 Seiten).
