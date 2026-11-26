# PC44 Editor for MPC standalone

PC44 Editor 0.7.2 is a stereo pass-through insert for the Faderfox PC44
sequencer. It connects directly to the PC44 over USB MIDI. It uses no plugin
instrument track or MIDI Learn.

## Install on an MPC Live III

1. Remove or replace the previous `NOXED - VST - PC44 Editor` folder in
   `VST2 Plugins`. Copy the folder from the 0.7.2 ZIP into that same location.
2. On MPC OS 3.10.1 or newer, enable **Enable Enhancements** and **External
   Plugin Support** in **Preferences → Enhancements (Beta)**.
3. Flash the matched **PC44_seq_ab_one_hand.syx** to enable both pattern
   streams and all edits. Use the Faderfox update procedure with the PC44
   booted into update mode and reconnect it to the MPC via USB afterward.
4. In **Channel Mixer**, open the insert on **Out 1/2** or another active
   stereo channel. Select **External Plugins → PC44 Editor**.

The PC44 Editor retains its plugin ID, so existing instances can load the
new version. Open one instance per MPC.

## Edit before launching

- Select **A** or **B** at the top to see and edit that slot. The PC44
  streams both slots, including while stopped. The transport and blue
  playheads follow the PC44's playing slot. **Follow** is the playback view.
- In **Steps**, tap a lane and a step. The grid shows the lane's values.
  Amber indicates a sequenced step with a level bar, blue the playhead, and a white inner
  outline the step selected for editing.
- Change something on the PC44 and the editor follows: it selects that
  pattern, the lane (Velocity, Pitch, Chance, Gate, Ratchet, Chord, Nudge)
  and the step you turned. A track setting (length, speed, direction, mode,
  octave, channel), scale, root or a big pot selects the matching card on
  the **Setup** page; switch to that page with the MPC's tab. Ctrl All keeps
  the step column. Pattern copy, load and undo change several things at once
  and are not followed. Following only selects; it never sends anything.
- In **Setup**, choose a track and tap a setting card. See the current
  track, pattern, and global values in the cards.
- Turn **Value** with its Q-Link (Q-Link 4) or the slider. The change is sent
  to the PC44 at once, no Apply needed. **Applied on PC44** confirms the exact
  write. Q-Links 1-4 are the same on both pages: Pattern, Lane or Setting,
  Step or Track, Value. Physical
  knob changes get their own update ahead of the background sweep. Velocity
  zero switches a step off.
- To save B, use **Shift + 2** on the PC44 to select B for editing, then
  **Shift + 5**. Use **Shift + 1**, then **Shift + 5**, to save A.
  Selecting the edit slot leaves playback where it is. Double-press the
  encoder in the play view, or use **Shift + 3**, to launch the other pattern.
  During playback the switch waits for the next bar.

| Page | Scope | Parameters |
| --- | --- | --- |
| Steps | Per step | Velocity, pitch, chance or condition, gate length, ratchet, chord, nudge |
| Setup | Track in A/B | Step count, speed, direction, mode, octave, MIDI channel |
| Setup | Selected pattern | Scale, root |
| Setup | Shared | Internal tempo, swing and track volume |

Tempo edits set the internal clock. An active external clock remains in
control. A track at Volume 0 releases held notes and sends no new ones.
Volume is a live control and starts at unity when the PC44 is powered on.
Sequence edits remain in RAM until you save.

The supplied **seq28** firmware supports viewing. The previous A/B Monitor
preview also supports sending velocity. The matched build is required to see
both slots live and edit every setting.

## Build and test

Use the [MPC Plugin Builder SDK](https://github.com/inmusic-software/mpc-plugin-builder-sdk)
and Zig 0.15.2. On Linux, install the ALSA development headers (on Debian,
`libasound2-dev`), and Pillow (Titillium Web is bundled in `fonts/`, SIL OFL). Set `MPC_SDK` to the SDK checkout.
If the ALSA headers are outside the compiler's search path, set
`CPLUS_INCLUDE_PATH` to the directory that contains `alsa/asoundlib.h`.

```sh
python3 build.py --monitor PC44_V0101.syx PC44_seq_ab_one_hand.syx
python3 mpc-editor/make_skin.py
python3 "$MPC_SDK/tools/build.py" mpc-editor
"$MPC_SDK/.sdk-tools/host_sim" mpc-editor/build/native/pc44-editor.so test --seconds 3
bash mpc-editor/tests/run.sh
python3 "$MPC_SDK/tools/package.py" mpc-editor
```

The tests use the AVR firmware emulator and a simulated ALSA USB MIDI port.
Test the new firmware and both editor pages on physical hardware before
relying on the build live.

Licensed under MIT. See the repository's LICENSE.
