// SPDX-License-Identifier: MIT
#include "mpc_vst2_abi.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <dlfcn.h>
#include <initializer_list>
#include <string>
#include <thread>
#include <vector>

extern "C" {
void fake_attach(bool enabled);
void fake_emit(const uint8_t* bytes, std::size_t size, int client);
int fake_command(uint8_t* bytes);
}

using namespace std::chrono_literals;

namespace {
using Packet = std::array<uint8_t, 10>;
constexpr int Slot = 1, Step = 2, Velocity = 3, Apply = 4, Link = 5, Transport = 6;
constexpr int Tuning = 7, Tempo = 8, Current = 9, Receipt = 10, GridStatus = 13, Details = 14, Timing = 15, Grid = 20;
constexpr int StepField = 84, SetupField = 85, SetupTrack = 86, SetupValue = 87, SetupApply = 88;
constexpr int StepStored = 89, SetupStored = 91, Track1 = 16;

VstIntPtr host(AEffect*, VstInt32 opcode, VstInt32, VstIntPtr, void*, float)
{
    return opcode == audioMasterVersion ? kVstVersion : 0;
}

void emit(std::initializer_list<uint8_t> contents, int source = 24)
{
    fake_emit(contents.begin(), contents.size(), source);
}

void block(uint8_t field, uint8_t slot, uint8_t value, uint8_t track = 0)
{
    const uint8_t address = track + (field >= 0x30 ? slot * 4 : 0);
    std::array<uint8_t, 23> bytes{0xf0, 0x7d, 0x50, 0x34, field, address};
    if (field == 0x10 || field == 0x30) {
        const uint8_t header[] = {16, 4, 0, 0, 3, 0, 0, 0, 1, 9, 0, 1, 2, 0, 0, slot};
        std::copy(std::begin(header), std::end(header), bytes.begin() + 6);
    } else {
        bytes[6] = value;
    }
    bytes.back() = 0xf7;
    fake_emit(bytes.data(), bytes.size(), 24);
}

void reply(const Packet& packet, uint8_t result, uint8_t tokenDelta = 0)
{
    // Exercise reassembly with a real-time clock byte inside the acknowledgement.
    emit({0xf0, 0x7d, 0x50, 0x34, 0x21, static_cast<uint8_t>((packet[5] + tokenDelta) & 127), 0xf8});
    emit({packet[6], packet[7], packet[8], result, 0xf7});
}

template<typename Condition>
bool waitFor(Condition condition, std::chrono::milliseconds limit = 2000ms)
{
    const auto until = std::chrono::steady_clock::now() + limit;
    do {
        if (condition()) return true;
        std::this_thread::sleep_for(10ms);
    } while (std::chrono::steady_clock::now() < until);
    return false;
}

void expect(AEffect* plug, int id, const char* expected)
{
    char actual[64]{};
    if (!waitFor([&] {
        plug->dispatcher(plug, effGetParamDisplay, id, 0, actual, 0);
        return std::string(actual) == expected;
    })) {
        std::fprintf(stderr, "parameter %d: expected '%s', got '%s'\n", id, expected, actual);
        std::abort();
    }
}

Packet command(uint8_t slot, uint8_t step, uint8_t velocity)
{
    Packet bytes{};
    assert(waitFor([&] { return fake_command(bytes.data()) == static_cast<int>(bytes.size()); }));
    assert((std::array<uint8_t, 5>{bytes[0], bytes[1], bytes[2], bytes[3], bytes[4]} ==
            std::array<uint8_t, 5>{0xf0, 0x7d, 0x50, 0x34, 0x20}));
    assert(bytes[6] == slot && bytes[7] == step && bytes[8] == velocity && bytes[9] == 0xf7);
    return bytes;
}

void extendedCommand(uint8_t slot, uint8_t index, uint8_t field, uint8_t value)
{
    std::array<uint8_t, 12> bytes{};
    assert(waitFor([&] { return fake_command(bytes.data()) == 12; }));
    assert((std::array<uint8_t, 5>{bytes[0], bytes[1], bytes[2], bytes[3], bytes[4]} ==
            std::array<uint8_t, 5>{0xf0, 0x7d, 0x50, 0x34, 0x22}));
    assert(bytes[6] == slot && bytes[7] == index && bytes[9] == field);
    assert((bytes[8] + 128 * bytes[10]) == value && bytes[11] == 0xf7);
    emit({0xf0, 0x7d, 0x50, 0x34, 0x23, bytes[5], slot, index, bytes[8], field, bytes[10], 0, 0xf7});
}

void noCommand()
{
    std::array<uint8_t, 12> bytes{};
    assert(!waitFor([&] { return fake_command(bytes.data()) != 0; }, 170ms));
}
}

int main(int argc, char** argv)
{
    assert(argc == 2);
    auto* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { std::fprintf(stderr, "%s\n", dlerror()); return 1; }
    auto entry = reinterpret_cast<AEffect* (*)(audioMasterCallback)>(dlsym(library, "VSTPluginMain"));
    assert(entry);
    auto* plugin = entry(host);
    assert(plugin && plugin->numInputs == 2 && plugin->numOutputs == 2);
    plugin->dispatcher(plugin, effMainsChanged, 0, 1, nullptr, 0);
    expect(plugin, Link, "Waiting for PC44 telemetry");

    emit({0xf0, 0x7d, 0x50, 0x34, 1, 0, 0, 0, 0, 1, 0xf7}, 128);
    noCommand();
    expect(plugin, Link, "Waiting for PC44 telemetry");
    emit({0xf0, 0x7d, 0x50, 0x34, 1, 0, 0x10, 0x20, 0, 0x59, 0xf7});
    block(0x10, 0, 0);
    block(0x11, 0, 100);
    block(0x12, 0, 62);
    block(0x13, 0, 9);
    block(0x14, 0, 2);
    block(0x15, 0, 1);
    block(0x17, 0, 8);
    expect(plugin, Link, "PC44 USB connected");
    expect(plugin, Transport, "A playing > B  EXT");
    expect(plugin, Tuning, "A Major");
    expect(plugin, Tempo, "130 BPM");
    expect(plugin, Current, "Current 100");
    expect(plugin, Details, "A4   /   100%");
    expect(plugin, Timing, "Len 1/2  x1  +2/12");
    expect(plugin, Grid, "100");
    plugin->setParameter(plugin, 0 /* set by the MPC at load */, 1.0f);
    plugin->setParameter(plugin, Apply, 1.0f);
    expect(plugin, Receipt, "Choose pattern A or B");
    noCommand();

    plugin->setParameter(plugin, Slot, 0.5f);
    plugin->setParameter(plugin, Velocity, 0.0f);
    // Both transitions of the Apply button issue exactly one explicit request.
    plugin->setParameter(plugin, Apply, 0.0f);
    auto bytes = command(0, 0, 0);
    expect(plugin, Receipt, "Waiting for PC44 confirmation");
    reply(bytes, 0, 1);
    noCommand();
    expect(plugin, Current, "Current 100");
    plugin->setParameter(plugin, Apply, 1.0f); // in-flight edit: duplicate tap ignored
    reply(bytes, 0);
    expect(plugin, Receipt, "Applied on PC44");
    expect(plugin, Current, "Current 0");
    noCommand();

    plugin->setParameter(plugin, Slot, 1.0f);
    plugin->setParameter(plugin, Step, 1.0f);
    plugin->setParameter(plugin, Velocity, 83.0f / 127.0f);
    expect(plugin, GridStatus, "Older firmware / live grid only");
    plugin->setParameter(plugin, Apply, 0.0f);
    bytes = command(1, 63, 83);
    reply(bytes, 1);
    expect(plugin, Receipt, "PC44 is saving. Try again.");
    expect(plugin, Current, "Current --");

    plugin->setParameter(plugin, Apply, 1.0f);
    bytes = command(1, 63, 83);
    reply(bytes, 0);
    expect(plugin, Receipt, "Applied on PC44");
    expect(plugin, Current, "Current 83");
    expect(plugin, GridStatus, "Last seen / older firmware");
    void* original = nullptr;
    const auto size = plugin->dispatcher(plugin, effGetChunk, 0, 0, &original, 0);
    assert(original && size > 0);
    const auto* chunk = static_cast<const uint8_t*>(original);
    std::vector<uint8_t> saved(chunk, chunk + size);

    plugin->setParameter(plugin, Apply, 0.0f);
    command(1, 63, 83);
    expect(plugin, Receipt, "No reply. Use Monitor firmware");
    assert(plugin->dispatcher(plugin, effSetChunk, 0, size, saved.data(), 0) == 1);
    noCommand();

    // Older firmware still supports velocity. Other fields report the
    // upgrade requirement without sending a command that cannot be applied.
    plugin->setParameter(plugin, StepField, 1.0f / 6.0f);
    plugin->setParameter(plugin, Velocity, 0.5f);
    plugin->setParameter(plugin, Apply, 0.0f);
    expect(plugin, Receipt, "Install matched PC44 firmware");
    noCommand();

    // B's full grid and pitch come from slot-tagged frames while A plays.
    plugin->setParameter(plugin, Step, 0.0f);
    for (uint8_t track = 0; track < 4; ++track) {
        block(0x30, 1, 0, track);
        block(0x31, 1, 91, track);
        block(0x32, 1, 62, track);
    }
    expect(plugin, Transport, "A playing > B  EXT");
    expect(plugin, GridStatus, "Inactive pattern / ready");
    expect(plugin, Grid, "A4");
    expect(plugin, StepStored, "A4");
    expect(plugin, Velocity, "A4");
    plugin->setParameter(plugin, Velocity, 0.0f);
    plugin->setParameter(plugin, Apply, 1.0f);
    extendedCommand(1, 0, 1, 0);
    expect(plugin, StepStored, "A3");
    expect(plugin, Grid, "A3");

    // Track 4 MIDI channel and a 2-byte BPM value share the same write path.
    // One tagged header from a different hardware track also updates
    // tuning for the currently selected track.
    emit({0xf0, 0x7d, 0x50, 0x34, 0x30, 6,
          16, 4, 0, 0, 3, 2, 0, 0, 1, 7, 0, 1, 2, 0, 1, 1, 0xf7});
    expect(plugin, Tuning, "G Major");
    expect(plugin, Grid, "G3");
    emit({0xf0, 0x7d, 0x50, 0x34, 0x38, 0, 64, 64, 64, 0xf7});
    expect(plugin, Track1, "VOL 0");

    plugin->setParameter(plugin, SetupField, 5.0f / 10.0f);
    plugin->setParameter(plugin, SetupTrack, 1.0f);
    plugin->setParameter(plugin, SetupValue, 1.0f);
    plugin->setParameter(plugin, SetupApply, 1.0f);
    extendedCommand(1, 3, 12, 15);
    expect(plugin, SetupStored, "16");
    plugin->setParameter(plugin, SetupField, 9.0f / 10.0f);
    plugin->setParameter(plugin, SetupValue, 189.0f / 220.0f);
    plugin->setParameter(plugin, SetupApply, 0.0f);
    extendedCommand(1, 0, 16, 219);
    expect(plugin, SetupStored, "219 BPM");
    expect(plugin, Tempo, "219 BPM");

    plugin->setParameter(plugin, StepField, 0.0f);
    block(0x10, 1, 0);
    block(0x11, 1, 70);
    expect(plugin, Transport, "B / transport unknown");
    expect(plugin, GridStatus, "Playing slot");
    expect(plugin, Current, "Current 70");

    fake_attach(false);
    expect(plugin, Link, "Connect PC44 via USB");
    plugin->setParameter(plugin, Apply, 0.0f);
    noCommand();
    fake_attach(true);
    block(0x10, 1, 0);
    block(0x11, 1, 52);
    expect(plugin, Link, "PC44 USB connected");
    expect(plugin, Current, "Current 52");

    // A value turned on the PC44 selects the same pattern, lane and step here.
    plugin->setParameter(plugin, Slot, 0.0f);       // Follow
    plugin->setParameter(plugin, StepField, 0.0f);  // Velocity lane
    plugin->setParameter(plugin, Step, 0.0f);
    block(0x32, 0, 40, 2);                          // A, pitch, track 3: complete row
    noCommand();
    expect(plugin, Slot, "Follow");                 // a first fill is not a change
    block(0x32, 0, 41, 2);                          // step 1 of track 3 moved on the PC44
    expect(plugin, Slot, "A");
    expect(plugin, StepField, "Pitch");
    expect(plugin, Step, "T3 / 1");
    noCommand();                                    // following never sends anything

    // A track setting changed on the PC44 selects it on the Setup page.
    auto header = [](uint8_t slot, uint8_t track, uint8_t octave) {
        std::array<uint8_t, 23> bytes{0xf0, 0x7d, 0x50, 0x34, 0x30,
            static_cast<uint8_t>(track + slot * 4), 16, 4, 0, 0, octave, 0, 0, 0, 1, 9, 0, 1, 2, 0, 0, slot, 0xf7};
        fake_emit(bytes.data(), bytes.size(), 24);
    };
    header(1, 1, 3);
    header(1, 1, 4);                                // octave of track 2 in B
    expect(plugin, Slot, "B");
    expect(plugin, SetupField, "Octave");
    waitFor([&] { return std::lround(plugin->getParameter(plugin, SetupTrack) * 3) == 1; });
    assert(std::lround(plugin->getParameter(plugin, SetupTrack) * 3) == 1);
    noCommand();

    float left[]{0.25f, 0.75f}, right[]{-0.125f, 0.5f}, outL[2]{}, outR[2]{};
    float* inputs[]{left, right};
    float* outputs[]{outL, outR};
    plugin->processReplacing(plugin, inputs, outputs, 2);
    assert(std::equal(std::begin(left), std::end(left), outL));
    assert(std::equal(std::begin(right), std::end(right), outR));
    plugin->dispatcher(plugin, effClose, 0, 0, nullptr, 0);
    dlclose(library);
    std::puts("PC44 Editor USB, A/B acknowledgements, project recall, following PC44 edits and stereo passthrough passed.");
}
