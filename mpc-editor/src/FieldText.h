// SPDX-License-Identifier: MIT
#pragma once
#include "Protocol.h"
#include <cmath>
#include <string>

namespace pc44 {
constexpr const char* FieldNames[]{
    "Velocity", "Pitch", "Chance", "Gate", "Ratchet", "Chord", "Nudge",
    "Steps", "Speed", "Direction", "Mode", "Octave", "MIDI Ch.",
    "Scale", "Root", "Swing", "Tempo", "Legacy Mute", "Volume"
};
constexpr const char* NoteNames[]{"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
constexpr const char* Scales[]{"Chromatic", "Major", "Minor", "Dorian", "Phrygian", "Lydian",
    "Mixolydian", "Harmonic Minor", "Major Pent.", "Minor Pent.", "Blues"};
constexpr const char* Gates[]{"1/12", "1/4", "1/2", "3/4", "1", "2", "3", "4",
    "5", "6", "7", "8", "10", "12", "14", "16"};

inline int amountValue(int field, float normalized)
{
    const auto range = Ranges[field];
    return range.min + static_cast<int>(std::lround(normalized * (range.max - range.min)));
}

inline float normalizeAmount(int field, int value)
{
    const auto range = Ranges[field];
    return static_cast<float>(std::clamp(value, range.min, range.max) - range.min) /
           (range.max - range.min);
}

inline std::string signedText(int value)
{
    return (value > 0 ? "+" : "") + std::to_string(value);
}

inline std::string chanceText(int chance)
{
    if (chance < 10) return std::to_string((chance + 1) * 10) + "%";
    chance -= 10;
    for (int cycle = 2; cycle <= 8; ++cycle) {
        if (chance < cycle) return std::to_string(chance + 1) + ":" + std::to_string(cycle);
        chance -= cycle;
    }
    return "--";
}

inline std::string noteName(int note)
{
    return std::string(NoteNames[note % 12]) + std::to_string(note / 12 - 1);
}

inline int pitchContext(const Track& track)
{
    const int mode = track.get(0, 3), octave = track.get(0, 4);
    const int scale = track.get(0, 8), root = track.get(0, 9);
    if (mode < 0 || mode > 2 || octave < 0 || octave > 6 ||
        scale < 0 || scale > 10 || root < 0 || root > 11)
        return 0;
    return 1 + mode + (octave << 2) + (scale << 5) + (root << 9);
}

inline int midiNote(int raw, int context)
{
    constexpr int intervals[][12]{
        {0,1,2,3,4,5,6,7,8,9,10,11}, {0,2,4,5,7,9,11},
        {0,2,3,5,7,8,10}, {0,2,3,5,7,9,10}, {0,1,3,5,7,8,10},
        {0,2,4,6,7,9,11}, {0,2,4,5,7,9,10}, {0,2,3,5,7,8,11},
        {0,2,4,7,9}, {0,3,5,7,10}, {0,3,5,6,7,10}
    };
    constexpr int counts[]{12,7,7,7,7,7,7,7,5,5,6};
    const int flags = context - 1;
    const int octave = ((flags >> 2) & 7) - 3;
    if ((flags & 3) == 2) return std::clamp(std::max(0, raw - 26) + 12 * octave, 0, 127);
    const int scale = (flags >> 5) & 15, root = flags >> 9;
    if (scale >= 11) return raw;
    const int count = counts[scale];
    const int degree = raw * (2 * count + 1) / 128;
    return std::clamp(48 + 12 * (octave + degree / count) +
                      intervals[scale][degree % count] + root, 0, 127);
}

inline std::string fieldText(int field, int value, int context = 0, bool compact = false)
{
    const auto range = Ranges[field];
    if (value < range.min || value > range.max) return "--";
    constexpr const char* chords[]{"Triad", "Sus2", "Sus4", "7th", "Add9", "6th", "Open", "Power"};
    constexpr const char* chordShort[]{"Tri", "s2", "s4", "7th", "a9", "6th", "Opn", "Pwr"};
    constexpr const char* speeds[]{"x1/8", "x1/4", "x1/2", "x3/4", "x1", "x3/2", "x2"};
    constexpr const char* directions[]{"Forward", "Reverse", "Ping-pong", "Random"};
    constexpr const char* modes[]{"Note", "Chord", "Pad"};
    constexpr int shuffle[]{50,54,58,62,67,71,75};
    switch (field) {
        case StepVelocity: return value ? std::to_string(value) : (compact ? "" : "Off");
        case Pitch: return context ? noteName(midiNote(value, context)) : std::to_string(value);
        case Chance: return chanceText(value);
        case Gate: return Gates[value];
        case Ratchet: return "x" + std::to_string(value);
        case Chord: return compact ? chordShort[value] : chords[value];
        case Nudge: return signedText(value - 6) + (compact ? "" : "/12");
        case Speed: return speeds[value];
        case Direction: return directions[value];
        case Mode: return modes[value];
        case Octave: return signedText(value - 3);
        case Channel: return std::to_string(value + 1);
        case Scale: return Scales[value];
        case Root: return NoteNames[value];
        case Shuffle: return std::to_string(shuffle[value]) + "%";
        case BPM: return std::to_string(value) + " BPM";
        case Trim: return std::to_string(static_cast<int>(std::lround(value * 100.0 / 64))) + "%";
        default: return std::to_string(value);
    }
}
}
