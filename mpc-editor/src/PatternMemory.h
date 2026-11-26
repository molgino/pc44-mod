// SPDX-License-Identifier: MIT
#pragma once
#include "Protocol.h"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace pc44 {

// One PC44 pattern as values the editor can write back with ordinary edits:
// per-track length, speed, direction, mode, octave and channel, the pattern's
// scale and root, and every step lane. Tempo, swing and track volume are
// shared by A and B and are not part of a pattern.
struct PatternImage {
    static constexpr int SettingCount = Scale - TrackLength;                 // 6 per track
    static constexpr int SettingEdits = Tracks * SettingCount;              // 24
    static constexpr int TuningEdits = 2;                                   // scale, root
    static constexpr int EditCount = SettingEdits + TuningEdits + StepFields * Cells;  // 474
    static constexpr uint8_t Version = 1;

    uint8_t source = 0;  // 0 = A, 1 = B
    std::array<std::array<uint8_t, SettingCount>, Tracks> settings{};  // field - TrackLength
    uint8_t scale = 0;
    uint8_t root = 0;
    std::array<std::array<std::array<uint8_t, Steps>, StepFields>, Tracks> steps{};

    struct Item { int field; int index; int value; };

    // The n-th edit in load order. Mode comes first on each track so the PC44
    // reads later pitches in the right mode; then the other track settings,
    // the tuning, and finally every step lane.
    Item item(int n) const
    {
        if (n < SettingEdits) {
            static constexpr int order[SettingCount]{Mode - TrackLength, 0, 1, 2, 4, 5};
            const int track = n / SettingCount;
            const int setting = order[n % SettingCount];
            return {TrackLength + setting, track, settings[track][setting]};
        }
        n -= SettingEdits;
        if (n == 0) return {Scale, 0, scale};
        if (n == 1) return {Root, 0, root};
        n -= TuningEdits;
        const int field = n / Cells;
        const int cell = n % Cells;
        return {field, cell, steps[cell / Steps][field][cell % Steps]};
    }

    // Copy a pattern from the telemetry cache. Needs every row of the slot.
    static std::optional<PatternImage> capture(const Monitor& monitor, int slot)
    {
        if (slot < 0 || slot > 1) return std::nullopt;
        PatternImage image;
        image.source = static_cast<uint8_t>(slot);
        for (int track = 0; track < Tracks; ++track) {
            const Track& row = monitor.patterns[slot][track];
            for (int block = 0; block <= StepFields; ++block)
                if (!row.has(block)) return std::nullopt;
            for (int setting = 0; setting < SettingCount; ++setting)
                image.settings[track][setting] = row.data[0][setting];
            for (int field = 0; field < StepFields; ++field)
                image.steps[track][field] = row.data[field + 1];
        }
        image.scale = monitor.patterns[slot][0].data[0][8];
        image.root = monitor.patterns[slot][0].data[0][9];
        if (!image.valid()) return std::nullopt;
        return image;
    }

    bool valid() const
    {
        if (source > 1) return false;
        for (int n = 0; n < EditCount; ++n) {
            const Item edit = item(n);
            if (edit.value < Ranges[edit.field].min || edit.value > Ranges[edit.field].max) return false;
        }
        return true;
    }

    // Versioned blob for the plugin state the MPC keeps in projects and presets.
    void serialize(std::vector<uint8_t>& out) const
    {
        out.insert(out.end(), {'P', '4', '4', 'M', Version, source});
        for (const auto& track : settings) out.insert(out.end(), track.begin(), track.end());
        out.push_back(scale);
        out.push_back(root);
        for (const auto& track : steps)
            for (const auto& lane : track) out.insert(out.end(), lane.begin(), lane.end());
    }

    static constexpr std::size_t SerializedSize = 6 + SettingEdits + TuningEdits + StepFields * Cells;

    static std::optional<PatternImage> parse(const uint8_t* data, std::size_t size)
    {
        if (!data || size < SerializedSize || data[0] != 'P' || data[1] != '4' || data[2] != '4' ||
            data[3] != 'M' || data[4] != Version)
            return std::nullopt;
        PatternImage image;
        const uint8_t* p = data + 5;
        image.source = *p++;
        for (auto& track : image.settings)
            for (auto& value : track) value = *p++;
        image.scale = *p++;
        image.root = *p++;
        for (auto& track : image.steps)
            for (auto& lane : track)
                for (auto& value : lane) value = *p++;
        if (!image.valid()) return std::nullopt;
        return image;
    }
};

} // namespace pc44
