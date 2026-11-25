// SPDX-License-Identifier: MIT
#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>

namespace pc44 {

constexpr int Tracks = 4;
constexpr int Steps = 16;
constexpr int Cells = Tracks * Steps;
constexpr std::array<uint8_t, 4> Prefix{0xf0, 0x7d, 0x50, 0x34};

enum Field {
    StepVelocity, Pitch, Chance, Gate, Ratchet, Chord, Nudge,
    TrackLength, Speed, Direction, Mode, Octave, Channel, Scale, Root,
    Shuffle, BPM, Mute, Trim, FieldCount
};
constexpr int StepFields = TrackLength;
constexpr int SetupFields = FieldCount - StepFields;

struct Range { int min; int max; };
constexpr std::array<Range, FieldCount> Ranges{{
    {0, 127}, {0, 127}, {0, 44}, {0, 15}, {1, 4}, {0, 7}, {0, 12},
    {1, 16}, {0, 6}, {0, 3}, {0, 2}, {0, 6}, {0, 15}, {0, 10}, {0, 11},
    {0, 6}, {30, 250}, {0, 1}, {0, 127}
}};

struct Edit {
    uint8_t token;
    uint8_t slot;
    uint8_t index;
    uint8_t field;
    uint8_t value;

    bool legacy() const { return field == StepVelocity; }
    int size() const { return legacy() ? 10 : 12; }

    std::array<uint8_t, 12> packet() const
    {
        std::array<uint8_t, 12> bytes{Prefix[0], Prefix[1], Prefix[2], Prefix[3],
            static_cast<uint8_t>(legacy() ? 0x20 : 0x22), token, slot, index,
            static_cast<uint8_t>(value & 127), field, static_cast<uint8_t>(value >> 7), 0xf7};
        bytes[size() - 1] = 0xf7;
        return bytes;
    }

    bool matches(const uint8_t* frame, std::size_t length) const
    {
        return length == static_cast<std::size_t>(size() + 1) &&
               frame[4] == (legacy() ? 0x21 : 0x23) &&
               frame[5] == token && frame[6] == slot && frame[7] == index &&
               frame[8] == (value & 127) &&
               (legacy() || (frame[9] == field && frame[10] == (value >> 7)));
    }
};

struct Track {
    // 0 header, 1 velocity, 2 pitch, 3 chance, 4 length, 5 ratchet,
    // 6 chord, 7 nudge. Bit masks distinguish confirmed edits from missing data.
    std::array<std::array<uint8_t, Steps>, 8> data{};
    std::array<uint16_t, 8> received{};

    bool has(int block) const { return received[block] == 0xffff; }
    int get(int block, int step) const
    {
        return (received[block] & (1u << step)) ? data[block][step] : -1;
    }
    void set(int block, int step, int value)
    {
        received[block] |= 1u << step;
        data[block][step] = value;
    }
    void update(int block, const uint8_t* bytes)
    {
        std::copy_n(bytes, Steps, data[block].begin());
        received[block] = 0xffff;
    }
};

struct Monitor {
    enum class Result { Ignored, Telemetry, Applied, Saving, Rejected };

    // Retain the two additional display-only slots used by seq28.
    std::array<std::array<Track, Tracks>, 4> patterns{};
    std::array<uint8_t, Tracks> heads{};
    std::array<int, Tracks> trims{{-1, -1, -1, -1}};
    int active = -1;
    int transport = -1;
    bool hasHeads = false;
    bool extended = false;

    bool running() const { return transport >= 0 && (transport & 1); }

    int value(int slot, int field, int index) const
    {
        if (slot < 0 || slot > 3) return -1;
        if (field < StepFields) return patterns[slot][index / Steps].get(field + 1, index % Steps);
        if (field == Trim) return trims[index];
        if (field >= Shuffle) slot = active; // shared globals
        if (slot < 0) return -1;
        if (field == Mute) return patterns[slot][index].get(0, 7);
        if (field == BPM) {
            const auto& header = patterns[slot][0];
            const int hi = header.get(0, 11);
            const int lo = header.get(0, 12);
            return hi >= 0 && lo >= 0 ? hi * 128 + lo : -1;
        }
        return patterns[slot][index].get(0, field < Scale ? field - TrackLength : field - Scale + 8);
    }

    Result receive(const uint8_t* frame, std::size_t size, const Edit* pending)
    {
        if (size < 6 || !std::equal(Prefix.begin(), Prefix.end(), frame) ||
            frame[size - 1] != 0xf7 ||
            std::any_of(frame + 4, frame + size - 1, [](uint8_t b) { return b > 127; }))
            return Result::Ignored;

        const int command = frame[4];
        if (command == 0x01 && size == 11) {
            std::copy_n(frame + 5, Tracks, heads.begin());
            setActive((frame[9] >> 1) & 3);
            transport = frame[9];
            hasHeads = true;
            return Result::Telemetry;
        }
        if (command >= 0x10 && command <= 0x17 && size == 23 && frame[5] < Tracks) {
            const int block = command - 0x10;
            if (block == 0) {
                if (frame[21] > 3) return Result::Ignored;
                setActive(frame[21]);
            }
            if (active < 0) return Result::Ignored;
            patterns[active][frame[5]].update(block, frame + 6);
            return Result::Telemetry;
        }
        if (command >= 0x30 && command <= 0x37 && size == 23 && frame[5] < 8) {
            const int slot = frame[5] / Tracks;
            const int block = command - 0x30;
            if (block == 0 && frame[21] != slot) return Result::Ignored;
            extended = true;
            patterns[slot][frame[5] % Tracks].update(block, frame + 6);
            return Result::Telemetry;
        }
        if (command == 0x38 && size == 10) {
            extended = true;
            std::copy_n(frame + 5, Tracks, trims.begin());
            return Result::Telemetry;
        }
        if (pending && pending->matches(frame, size)) {
            switch (frame[size - 2]) {
                case 0:
                    confirm(*pending);
                    return Result::Applied;
                case 1: return Result::Saving;
                case 2: return Result::Rejected;
            }
        }
        return Result::Ignored;
    }

private:
    void setActive(int slot)
    {
        if (active == slot) return;
        // Tagged telemetry keeps both caches fresh as playback switches.
        if (!extended) patterns[slot] = {};
        active = slot;
        transport = -1;
        hasHeads = false;
    }

    void confirm(const Edit& edit)
    {
        const int field = edit.field;
        const int index = edit.index;
        const int value = edit.value;
        if (field < StepFields) {
            patterns[edit.slot][index / Steps].set(field + 1, index % Steps, value);
        } else if (field < Scale) {
            patterns[edit.slot][index].set(0, field - TrackLength, value);
        } else if (field <= Root) {
            for (auto& track : patterns[edit.slot]) track.set(0, 8 + field - Scale, value);
        } else if (field == Trim) {
            trims[index] = value;
        } else {
            for (auto& tracks : patterns) {
                if (field == Mute) {
                    tracks[index].set(0, 7, value);
                    if (!running()) tracks[index].set(0, 6, value);
                } else {
                    for (auto& track : tracks) {
                        if (field == Shuffle) track.set(0, 10, value);
                        if (field == BPM) {
                            track.set(0, 11, value >> 7);
                            track.set(0, 12, value & 127);
                        }
                    }
                }
            }
        }
    }
};

// ALSA normally supplies complete SysEx events, but is allowed to split them.
class Framer {
public:
    template<typename Receive>
    void append(const uint8_t* data, std::size_t size, Receive receive)
    {
        for (std::size_t i = 0; i < size; ++i) {
            const uint8_t byte = data[i];
            if (byte == 0xf0) {
                length_ = 0;
                packet_[length_++] = byte;
            } else if (byte >= 0xf8) {
                continue;
            } else if (length_ != 0) {
                if (length_ == packet_.size()) {
                    length_ = 0;
                } else if (byte == 0xf7) {
                    packet_[length_++] = byte;
                    receive(packet_.data(), length_);
                    length_ = 0;
                } else if (byte < 0x80) {
                    packet_[length_++] = byte;
                } else {
                    length_ = 0;
                }
            }
        }
    }

    void reset() { length_ = 0; }

private:
    std::array<uint8_t, 23> packet_{};
    std::size_t length_ = 0;
};

} // namespace pc44
