// SPDX-License-Identifier: MIT
#include "mpc_plugin.h"
#include "AlsaMidi.h"
#include "FieldText.h"

#include <atomic>
#include <chrono>
#include <optional>
#include <thread>

namespace {

using namespace pc44;
using namespace std::chrono_literals;
using Clock = std::chrono::steady_clock;

enum Parameter {
    HostNudge, Slot, Step, Velocity, Apply, Link, Transport, Tuning, Tempo,
    Current, Receipt, Focus, EditSlot, Background, Details, Timing, Track1, Track2,
    Track3, Track4, Grid,
    StepField = Grid + Cells, SetupField, SetupTrack, SetupValue, SetupApply,
    StepStored, EditPitchContext, SetupStored, SetupValues
};

enum LinkState { Connecting, NoAlsa, NoPC44, TwoPC44s, NoTelemetry, ViewOnly, Live, SecondInsert };
enum ReceiptState { NoEdit, Sending, Applied, SaveBusy, Rejected, NoReply, Disconnected, InvalidTarget, SendFailed,
                    NeedsNewFirmware, SetValue };
enum GridState { Awaiting, CurrentPattern, CachedPattern, EmptyCache, ReadingBoth, InactiveReady };

constexpr int InFlight = -1;

std::atomic_flag editorOpen = ATOMIC_FLAG_INIT;
thread_local bool restoring = false;

mpc::PluginInfo editorInfo()
{
    mpc::PluginInfo info;
    info.name = "PC44 Editor";
    info.vendor = "NOXED";
    info.version = 702;
    info.uniqueId = MPC_FOURCC('N', 'X', 'p', 'E');
    info.tailSamples = 1;
    return info;
}

class Editor : public mpc::Plugin {
public:
    Editor() : Plugin(editorInfo())
    {
        add(mpc::intParam("host_nudge", "Host Nudge", 0, 1, 0));
        add(mpc::choiceParam("slot", "Edit Pattern", {"Follow", "A", "B"}));
        add(mpc::intParam("step", "Edit Step", 0, Cells - 1, 0));
        add(mpc::intParam("velocity", "New Velocity", 0, 127, 100));
        add(mpc::boolParam("apply", "Apply", false));
        add(mpc::choiceParam("link", "USB link", {
            "Connecting", "ALSA MIDI unavailable", "Connect PC44 via USB",
            "Multiple PC44 MIDI ports", "Waiting for PC44 telemetry", "USB view only",
            "PC44 USB connected", "Open one PC44 Editor only"
        }));
        add(mpc::intParam("transport", "Transport", 0, 132, 0));
        add(mpc::intParam("tuning", "Scale and Root", 0, 2048, 0));
        add(mpc::intParam("tempo", "Tempo", 0, 16383, 0));
        add(mpc::intParam("current", "Current Velocity", 0, 128, 0));
        add(mpc::choiceParam("receipt", "Edit Status", {
            "Live: turn a value to edit", "Waiting for PC44 confirmation",
            "Applied on PC44", "PC44 is saving. Try again.", "PC44 rejected the edit",
            "No reply. Use Monitor firmware", "PC44 connection lost",
            "Choose pattern A or B", "Could not send to PC44",
            "Install matched PC44 firmware", "Move the value to edit"
        }));
        add(mpc::intParam("focus", "PC44 Controls", 0, 256, 0));
        add(mpc::intParam("edit_slot", "Target Pattern", 0, 4, 0));
        add(mpc::choiceParam("grid_state", "Grid Status", {
            "Waiting for PC44", "Playing slot", "Last seen / older firmware",
            "Older firmware / live grid only", "Reading pattern...",
            "Inactive pattern / ready"
        }));
        add(mpc::intParam("details", "Step Details", 0, 16384, 0));
        add(mpc::intParam("timing", "Step Timing", 0, 8192, 0));
        for (int track = 0; track < Tracks; ++track) {
            const auto id = "track_" + std::to_string(track + 1);
            const auto name = "Track " + std::to_string(track + 1);
            add(mpc::intParam(id.c_str(), name.c_str(), 0, 128, 0));
        }
        for (int cell = 0; cell < Cells; ++cell) {
            const auto id = "cell_" + std::to_string(cell + 1);
            const auto name = "Cell " + std::to_string(cell + 1);
            add(mpc::intParam(id.c_str(), name.c_str(), 0, 515, 0));
        }
        add(mpc::choiceParam("step_field", "Step Lane", {FieldNames, FieldNames + StepFields}));
        std::vector<std::string> setupNames;
        for (int choice = 0; choice < SetupChoices; ++choice)
            setupNames.emplace_back(FieldNames[setupField(choice)]);
        add(mpc::choiceParam("setup_field", "Setting", std::move(setupNames)));
        add(mpc::intParam("setup_track", "Setup Track", 0, Tracks - 1, 0));
        add(mpc::intParam("setup_value", "New Setting", 0, 220, 0));
        add(mpc::boolParam("setup_apply", "Apply Setting", false));
        add(mpc::intParam("step_stored", "Stored Step Value", 0, 128, 0));
        add(mpc::intParam("pitch_context", "Pitch Context", 0, 8192, 0));
        add(mpc::intParam("setup_stored", "Stored Setting", 0, 251, 0));
        for (int field = StepFields; field < FieldCount; ++field) {
            const auto id = "setting_" + std::to_string(field);
            add(mpc::intParam(id.c_str(), FieldNames[field], 0, 251, 0));
        }
    }

    ~Editor() override
    {
        stop_.store(true);
        if (worker_.joinable()) worker_.join();
    }

    void prepare(double, int) override
    {
        if (!worker_.joinable()) worker_ = std::thread(&Editor::run, this);
    }

    void process(mpc::ProcessContext& ctx) override
    {
        if (!ctx.outputs) return;
        for (int channel = 0; channel < ctx.numOutputs; ++channel) {
            auto* output = ctx.outputs[channel];
            if (!output) continue;
            const auto* input = ctx.inputs && channel < ctx.numInputs ? ctx.inputs[channel] : nullptr;
            if (!input) std::fill_n(output, ctx.numFrames, 0.0f);
            else if (input != output) std::copy_n(input, ctx.numFrames, output);
        }
    }

    void parameterChanged(int index, float value) override
    {
        if (index == Slot || index == Step || index == StepField) invalidateControl(false);
        if (index == Slot || index == SetupTrack || index == SetupField) invalidateControl(true);
        // Live edit: a user change of the value control is sent right away.
        // The worker thread resends if the value moved while a send was in flight.
        if (!restoring && (index == Velocity || index == SetupValue)) {
            const bool setup = index == SetupValue;
            dirty_[setup].store(true);
            if (writable_.load()) queueEdit(setup);
            return;
        }
        if (index != Apply && index != SetupApply) return;

        // Apply stays as an optional manual resend.
        const bool setup = index == SetupApply;
        const bool pressed = value >= 0.5f;
        const bool edge = applyState_[setup].exchange(pressed) != pressed;
        if (restoring || !edge || !writable_.load()) return;
        queueEdit(setup);
    }

    void queueEdit(bool setup)
    {
        const auto target = selection(setup);
        const int slot = getInt(Slot);
        const int encoded = target.key(slot);
        // Only a value adjusted by the user or loaded for this exact target
        // can be sent. A quick slot/step change cannot reuse a stale slider.
        const bool ready = dirty_[setup].load() || ready_[setup].load() == encoded;
        const int amount = amountValue(target.field, getNormalised(setup ? SetupValue : Velocity));
        const int request = (1 + encoded + amount) | (ready ? 0 : MissingAmount);
        int idle = 0;
        if (request_.compare_exchange_strong(idle, request)) sentAmount_[setup].store(ready ? amount : -1);
    }

    bool formatValue(int index, float value, std::string& out) override
    {
        const int n = static_cast<int>(value);
        switch (index) {
            case Step:
                out = "T" + std::to_string(n / Steps + 1) + " / " + std::to_string(n % Steps + 1);
                return true;
            case Velocity:
                out = fieldText(getInt(StepField), amountValue(getInt(StepField), value / 127.0f),
                                getInt(EditPitchContext));
                return true;
            case SetupValue:
                out = fieldText(setupField(getInt(SetupField)), amountValue(setupField(getInt(SetupField)), value / 220.0f));
                return true;
            case StepStored:
                out = fieldText(getInt(StepField), n - 1, getInt(EditPitchContext));
                return true;
            case SetupStored:
                out = fieldText(setupField(getInt(SetupField)), n - 1);
                return true;
            case Current:
                out = n ? "Current " + std::to_string(n - 1) : "Current --";
                return true;
            case EditSlot:
                out = n ? "PATTERN " + slotName(n - 1) : "PATTERN --";
                return true;
            case Transport:
                out = transportText(n);
                return true;
            case Tuning:
                out = tuningText(n);
                return true;
            case Tempo:
                out = n ? std::to_string(n) + " BPM" : "-- BPM";
                return true;
            case Focus:
                if (!n) out = "";
                else {
                    out = "PC44 T" + std::to_string(((n - 1) & 3) + 1);
                    if ((n - 1) & 4) out += " / CTRL ALL";
                }
                return true;
            case Details:
                if (!n) out = "";
                else {
                    const int packed = n - 1;
                    const int note = packed & 127;
                    out = std::string(NoteNames[note % 12]) + std::to_string(note / 12 - 1) +
                          "   /   " + chanceText(packed >> 7);
                }
                return true;
            case Timing:
                if (!n) out = "";
                else {

                    const int packed = n - 1;
                    const int offset = ((packed >> 8) & 15) - 6;
                    out = std::string("Len ") + Gates[packed & 15] + "  x" +
                          std::to_string((packed >> 4) & 15) + "  " +
                          (offset > 0 ? "+" : "") + std::to_string(offset) + "/12";
                }
                return true;
            case Track1: case Track2: case Track3: case Track4:
                out = trackText(n);
                return true;
        }
        if (index >= Grid && index < Grid + Cells) {
            const int cellValue = n % 129 - 1;
            const int field = getInt(StepField);
            out = cellValue < 0 ? "" : field == Pitch ? noteName(cellValue) : fieldText(field, cellValue, 0, true);
            return true;
        }
        if (index >= SetupValues && index < SetupValues + SetupFields) {
            out = fieldText(index - SetupValues + StepFields, n - 1);
            return true;
        }
        return false;
    }

    void cancelStagedEdit()
    {
        int staged = request_.load();
        if (staged > 0) request_.compare_exchange_strong(staged, 0);
        for (int page = 0; page < 2; ++page) {
            dirty_[page].store(false);
            ready_[page].store(-1);
            sentAmount_[page].store(-1);
        }
    }

private:
    void add(mpc::Param p)
    {
        p.automatable = false;
        addParam(p);
    }

    static std::string slotName(int slot)
    {
        if (slot < 0 || slot > 3) return "--";
        return std::string(1, static_cast<char>('A' + slot));
    }

    static std::string transportText(int value)
    {
        if (!value) return "PC44 transport";
        if (value >= 129) return slotName(value - 129) + " / transport unknown";
        const int state = value - 1;
        std::string text = slotName((state >> 1) & 3);
        text += (state & 1) ? " playing" : " stopped";
        if (state & 8) text += " > " + slotName((state >> 4) & 3);
        if (state & 64) text += "  EXT";
        return text;
    }

    static std::string tuningText(int value)
    {
        if (!value) return "Scale --";
        const int scale = (value - 1) >> 4;
        const int root = (value - 1) & 15;
        if (root >= 12 || scale >= 11) return "Scale --";
        return std::string(NoteNames[root]) + " " + Scales[scale];
    }

    struct Selection {
        int field;
        int index;
        int key(int slot) const { return (slot << 19) | (field << 14) | (index << 8); }
    };
    struct ControlState { int key = -1; int value = -1; };
    static constexpr int MissingAmount = 1 << 22;

    Selection selection(bool setup) const
    {
        if (!setup) return {getInt(StepField), getInt(Step)};
        const int field = setupField(getInt(SetupField));
        return {field, field < Scale || field == Trim ? getInt(SetupTrack) : 0};
    }

    void invalidateControl(bool setup)
    {
        const int key = selection(setup).key(getInt(Slot));
        if (selectionKey_[setup].exchange(key) != key) {
            dirty_[setup].store(false);
            ready_[setup].store(-1);
            sentAmount_[setup].store(-1);
            redraw_.store(true);
        }
    }

    bool refreshControl(bool setup, int slot, Selection target, int value)
    {
        auto& state = controls_[setup];
        ControlState next{target.key(slot), value};
        if (next.key == state.key && next.value == state.value &&
            (value < 0 || ready_[setup].load() == next.key)) return false;
        state = next;
        if (!dirty_[setup].load()) {
            // Internal slider refreshes must not look like a user gesture.
            restoring = true;
            setNormalised(setup ? SetupValue : Velocity, normalizeAmount(target.field, value));
            restoring = false;
        }
        ready_[setup].store(value >= 0 ? next.key : -1);
        return true;
    }

    // Select what was just changed on the PC44: pattern, lane and step, or the
    // track setting on the Setup page. Selection parameters only; nothing is sent.
    void follow(const Monitor::Touch& touch)
    {
        auto move = [this](int index, int value) {
            if (getInt(index) == value) return;
            set(index, static_cast<float>(value));
            notifyHostParameterChanged(index);
        };
        if (touch.slot >= 0) move(Slot, touch.slot + 1);
        if (touch.field < StepFields) {
            move(StepField, touch.field);
            const int current = getInt(Step);
            // Several steps (Ctrl All): stay on the column, but on the touched track.
            move(Step, touch.track * Steps + (touch.step >= 0 ? touch.step : current % Steps));
        } else {
            move(SetupField, touch.field == Trim ? SetupChoices - 1 : touch.field - StepFields);
            if (touch.field < Scale || touch.field == Trim) move(SetupTrack, touch.track);
        }
        redraw_.store(true);
    }

    void releaseConfirmedDraft(const Edit& edit)
    {
        const bool setup = edit.field >= StepFields;
        const auto target = selection(setup);
        if (getInt(Slot) == edit.slot + 1 && target.field == edit.field &&
            target.index == edit.index &&
            amountValue(target.field, getNormalised(setup ? SetupValue : Velocity)) == edit.value)
            dirty_[setup].store(false);
    }

    static std::string trackText(int value)
    {
        if (!value) return "--";
        if (value & 32) return "VOL 0";
        const int length = value & 31;
        return length ? std::to_string(length) + " steps" : "--";
    }

    void publish(const Monitor& monitor, LinkState link, ReceiptState receipt)
    {
        bool changed = false;
        auto update = [&](int index, int value) {
            if (getInt(index) != value) {
                set(index, static_cast<float>(value));
                changed = true;
            }
        };

        const int selectedSlot = getInt(Slot);
        const int slot = selectedSlot ? selectedSlot - 1 : monitor.active;
        const int cell = getInt(Step);
        const auto* pattern = slot >= 0 ? &monitor.patterns[slot] : nullptr;
        const bool liveGrid = pattern && slot == monitor.active;
        const auto* selected = pattern ? &(*pattern)[cell / Steps] : nullptr;

        update(Link, link);
        const int transport = monitor.hasHeads ? monitor.transport + 1 :
                              monitor.active >= 0 ? monitor.active + 129 : 0;
        update(Transport, transport);
        update(Receipt, receipt);
        update(EditSlot, slot + 1);
        update(Current, selected ? selected->get(1, cell % Steps) + 1 : 0);
        int grid = EmptyCache;
        if (monitor.active < 0) grid = Awaiting;
        else if (liveGrid) grid = CurrentPattern;
        else if (pattern) {
            const auto hasGrid = std::all_of(pattern->begin(), pattern->end(), [](const Track& t) { return t.has(1); });
            const auto hasData = std::any_of(pattern->begin(), pattern->end(), [](const Track& t) { return t.received[1]; });
            if (monitor.extended) grid = hasGrid ? InactiveReady : ReadingBoth;
            else if (hasData) grid = CachedPattern;
        }
        update(Background, grid);

        const auto stepTarget = selection(false);
        const auto setupTarget = selection(true);
        const int stepStored = monitor.value(slot, stepTarget.field, stepTarget.index);
        const int setupStored = monitor.value(slot, setupTarget.field, setupTarget.index);
        update(StepStored, stepStored + 1);
        update(EditPitchContext, selected ? pitchContext(*selected) : 0);
        update(SetupStored, setupStored + 1);
        if (refreshControl(false, selectedSlot, stepTarget, stepStored)) changed = true;
        if (refreshControl(true, selectedSlot, setupTarget, setupStored)) changed = true;
        for (int field = StepFields; field < FieldCount; ++field) {
            const int track = field < Scale || field == Trim ? getInt(SetupTrack) : 0;
            update(SetupValues + field - StepFields, monitor.value(slot, field, track) + 1);
        }

        const auto& active = monitor.patterns[monitor.active >= 0 ? monitor.active : 0][0];
        update(Tempo, std::max(0, monitor.value(slot, BPM, 0)));
        const int scale = monitor.value(slot, Scale, 0);
        const int root = monitor.value(slot, Root, 0);
        update(Tuning, scale >= 0 && scale < 11 && root >= 0 && root < 12 ? 1 + (scale << 4) + root : 0);
        const int focus = active.get(0, 13);
        update(Focus, focus >= 0 ? 1 + (focus & 3) + (active.get(0, 14) > 0 ? 4 : 0) : 0);
        const int offset = cell % Steps;
        update(Details, selected && selected->has(0) && selected->has(2) && selected->has(3)
                            ? 1 + midiNote(selected->data[2][offset], pitchContext(*selected)) +
                                  (selected->data[3][offset] << 7) : 0);
        update(Timing, selected && selected->has(4) && selected->has(5) && selected->has(7)
                           ? 1 + (selected->data[4][offset] & 15) +
                                 ((selected->data[5][offset] & 15) << 4) +
                                 ((selected->data[7][offset] & 15) << 8) : 0);

        for (int row = 0; row < Tracks; ++row) {
            const auto* track = pattern ? &(*pattern)[row] : nullptr;
            const auto* header = track && track->has(0) ? &track->data[0] : nullptr;
            const int length = header ? std::min<int>(Steps, (*header)[0]) : 0;
            const int head = liveGrid && monitor.hasHeads ? monitor.heads[row] : 0;
            const int trim = monitor.trims[row];
            const bool muted = trim >= 0 ? trim == 0 :
                               liveGrid && monitor.hasHeads ? (head & 0x10) != 0 :
                               header && (*header)[6] != 0;
            update(Track1 + row, length + (muted ? 32 : 0));
            const int context = track ? pitchContext(*track) : 0;
            for (int step = 0; step < Steps; ++step) {
                const int field = stepTarget.field;
                const int raw = track ? track->get(field + 1, step) : -1;
                const int value = field == Pitch && raw >= 0 ? (context ? midiNote(raw, context) : -1) : raw;
                const bool playhead = liveGrid && monitor.hasHeads && monitor.running() && (head & 15) == step;
                const bool enabled = track && track->get(1, step) > 0 && (!length || step < length) && !muted;
                const int appearance = value + 1 + (playhead ? 258 : 0) + (enabled ? 129 : 0);
                update(Grid + row * Steps + step, appearance);
            }
        }
        if (changed) requestDisplayUpdate();
    }

    void run()
    {
        // All real USB I/O lives here. The audio thread only copies audio.
        AlsaMidi midi;
        Monitor monitor;
        std::optional<Edit> pending;
        Clock::time_point nextDiscovery{}, connectedAt{}, lastFrame{}, deadline{}, nextUI{};
        AlsaMidi::State port = AlsaMidi::State::Unavailable;
        ReceiptState receipt = NoEdit;
        LinkState link = Connecting;
        bool ownsPort = false;
        uint8_t token = static_cast<uint8_t>(Clock::now().time_since_epoch().count() & 127);

        auto disconnect = [&] {
            writable_.store(false);
            if (request_.exchange(0) != 0) receipt = Disconnected;
            pending.reset();
            monitor = Monitor{};
            lastFrame = {};
        };

        while (!stop_.load()) {
            const auto now = Clock::now();
            if (now >= nextDiscovery) {
                nextDiscovery = now + 750ms;
                if (!ownsPort) ownsPort = !editorOpen.test_and_set();
                if (ownsPort) {
                    const int previous = midi.address();
                    port = midi.refresh();
                    if (previous != midi.address()) {
                        disconnect();
                        connectedAt = now;
                    }
                }
            }

            if (ownsPort && !midi.poll([&](const uint8_t* bytes, std::size_t size) {
                const auto result = monitor.receive(bytes, size, pending ? &*pending : nullptr);
                using Result = Monitor::Result;
                if (result == Result::Telemetry) {
                    lastFrame = now;
                } else if (result != Result::Ignored) {
                    if (result == Result::Applied && pending) releaseConfirmedDraft(*pending);
                    receipt = result == Result::Applied ? Applied :
                              result == Result::Saving ? SaveBusy : Rejected;
                    pending.reset();
                    request_.store(0);
                }
            })) {
                midi.close();
                port = AlsaMidi::State::Unavailable;
                disconnect();
            }

            const bool fresh = lastFrame != Clock::time_point{} && now - lastFrame < 6s;
            if (!fresh && midi.address() >= 0 && now - connectedAt >= 6s) {
                // A USB replug can reuse an ALSA address after deleting its subscription.
                midi.detach();
                disconnect();
                nextDiscovery = now;
            }
            switch (port) {
                case AlsaMidi::State::Unavailable: link = ownsPort ? NoAlsa : SecondInsert; break;
                case AlsaMidi::State::Missing: link = NoPC44; break;
                case AlsaMidi::State::Multiple: link = TwoPC44s; break;
                case AlsaMidi::State::ReadOnly: link = fresh ? ViewOnly : NoTelemetry; break;
                case AlsaMidi::State::Duplex: link = fresh ? Live : NoTelemetry; break;
            }
            // Follow edits made on the PC44 itself, but never while a plugin edit is in flight.
            if (const auto touch = monitor.takeTouch();
                touch && !pending && (link == Live || link == ViewOnly))
                follow(*touch);

            if (pending && now >= deadline) {
                pending.reset();
                request_.store(0);
                receipt = NoReply;
            }

            int request = request_.load();
            if (request > 0 && request_.compare_exchange_strong(request, InFlight)) {
                const int edit = (request & ~MissingAmount) - 1;
                const int slot = (edit >> 19) - 1;
                const int field = (edit >> 14) & 31;
                if (link != Live) {
                    receipt = Disconnected;
                } else if (slot < 0 || slot > 1) {
                    receipt = InvalidTarget;
                } else if (field != StepVelocity && !monitor.extended) {
                    receipt = NeedsNewFirmware;
                } else if (request & MissingAmount) {
                    receipt = SetValue;
                } else {
                    token = static_cast<uint8_t>((token + 1) & 127);
                    const Edit command{token, static_cast<uint8_t>(slot),
                        static_cast<uint8_t>((edit >> 8) & 63), static_cast<uint8_t>(field),
                        static_cast<uint8_t>(edit & 255)};
                    if (midi.send(command)) {
                        deadline = now + 1500ms;
                        pending = command;
                        receipt = Sending;
                    } else {
                        receipt = SendFailed;
                    }
                }
                if (!pending) request_.store(0);
            }
            writable_.store(link == Live && !pending);
            if (link == Live && !pending && request_.load() == 0) {
                // Value changed while an edit was in flight: send the newest one once.
                for (int page = 0; page < 2; ++page) {
                    if (!dirty_[page].load()) continue;
                    const auto target = selection(page);
                    const int amount = amountValue(target.field,
                        getNormalised(page ? SetupValue : Velocity));
                    if (amount != sentAmount_[page].load()) { queueEdit(page); break; }
                }
            }

            const bool selectionChanged = redraw_.exchange(false);
            if (selectionChanged || now >= nextUI || getInt(Receipt) != receipt) {
                publish(monitor, link, receipt);
                nextUI = now + 33ms;
            }
            std::this_thread::sleep_for(10ms);
        }
        midi.close();
        if (ownsPort) editorOpen.clear();
    }

    std::atomic<bool> stop_{false};
    std::atomic<bool> redraw_{false};
    std::atomic<bool> writable_{false};
    std::atomic<bool> applyState_[2]{};
    std::atomic<bool> dirty_[2]{};
    std::atomic<int> sentAmount_[2]{{-1}, {-1}};
    std::atomic<int> ready_[2]{{-1}, {-1}};
    std::atomic<int> selectionKey_[2]{{0}, {StepFields << 14}};
    ControlState controls_[2]{};
    std::atomic<int> request_{0};
    std::thread worker_;
};

VstIntPtr dispatch(AEffect* effect, VstInt32 opcode, VstInt32 index, VstIntPtr value, void* ptr, float opt)
{
    if (opcode != effSetChunk && opcode != effSetProgram)
        return mpc::detail::dispatcher(effect, opcode, index, value, ptr, opt);

    // Project and preset loads restore parameter values but never emit an edit.
    auto* editor = static_cast<Editor*>(effect->object);
    editor->cancelStagedEdit();
    const bool saved = restoring;
    restoring = true;
    const auto result = mpc::detail::dispatcher(effect, opcode, index, value, ptr, opt);
    restoring = saved;
    return result;
}

} // namespace

extern "C" MPC_EXPORT AEffect* VSTPluginMain(audioMasterCallback host)
{
    if (host && !host(nullptr, audioMasterVersion, 0, 0, nullptr, 0.0f)) return nullptr;
    auto* effect = mpc::detail::createEffect(new Editor(), host);
    if (effect) effect->dispatcher = dispatch;
    return effect;
}
