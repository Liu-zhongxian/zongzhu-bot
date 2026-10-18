// SPDX-License-Identifier: AGPL-3.0-or-later
// Eye proportions adapted from Trentct/m5stack-stopwatch-avatar (2049632).
// See kk-avatar-NOTICE.md. Rendering/timing are adapted for XiaoZhi's LVGL UI.
#pragma once

#include <array>
#include <cmath>
#include <cstdint>

namespace kk {
enum class Emotion {
    Idle,
    Listening,
    Thinking,
    Speaking,
    Happy,
    Excited,
    Curious,
    Confused,
    Angry,
    Surprised,
    Sad,
    Sleepy,
    Dizzy
};

struct Eye {
    float x, y, width, height, angle, lid, brow;
};
using Pose = std::array<Eye, 2>;

// The source avatar uses a 1000-unit design space; render at 0.466 on this panel.
inline Pose PoseAt(Emotion emotion, uint32_t milliseconds) {
    const float t = milliseconds / 1000.0f;
    const float sway = std::sin(t * 0.65f);
    Pose p = {{{-225, -15, 155, 360, 0, 0, 0}, {225, -15, 155, 360, 0, 0, 0}}};
    switch (emotion) {
        case Emotion::Listening:
            p = {{{-220, -22, 160, 325 + 14 * sway, -3, 0, 0},
                  {220, -20, 174, 325 - 14 * sway, 4, 0, 0}}};
            break;
        case Emotion::Thinking:
            p = {{{-220, -30, 178 + 18 * sway, 275 + 30 * sway, -5, 0, 0},
                  {220, -34, 178 - 25 * sway, 275 - 30 * sway, 8, 0, 0}}};
            for (auto& eye : p)
                eye.x += sway * 20;
            break;
        case Emotion::Speaking:
            for (auto& eye : p) {
                eye.width = 174;
                eye.height = 320 + 22 * std::sin(t * 7);
            }
            break;
        case Emotion::Happy:
            p = {{{-220, -4, 290, 72, -8, 0, 0}, {220, -4, 290, 72, 8, 0, 0}}};
            break;
        case Emotion::Excited:
            p = {{{-225, -34, 225, 340, -6, 0, 0}, {225, -34, 225, 340, 6, 0, 0}}};
            for (auto& eye : p)
                eye.y += 16 * std::sin(t * 8);
            break;
        case Emotion::Curious:
            p = {{{-218, -28, 195, 360, -8, 0, 0}, {218, -18, 142, 270, 4, 0, 0}}};
            break;
        case Emotion::Confused:
            p = {{{-220, -12, 168 + 20 * sway, 270 + 20 * sway, 9, 0, 0},
                  {220, -26, 168 - 20 * sway, 270 - 20 * sway, -7, 0, 0}}};
            break;
        case Emotion::Angry:
            p = {{{-212, -28, 220, 270, 17, .22f, 1}, {212, -28, 220, 270, -17, .22f, 1}}};
            break;
        case Emotion::Surprised:
            p = {{{-230, -15, 255, 255, 0, 0, 0}, {230, -15, 255, 255, 0, 0, 0}}};
            break;
        case Emotion::Sad:
            p = {{{-215, 18, 205, 205, -17, .26f, .75f}, {215, 18, 205, 205, 17, .26f, .75f}}};
            break;
        case Emotion::Sleepy:
            p = {{{-210, 48, 305, 48, 0, 0, 0}, {210, 48, 305, 48, 0, 0, 0}}};
            break;
        case Emotion::Dizzy:
            p = {{{-210, -10, 270, 270, 0, 0, 0}, {210, 4, 244, 244, 0, 0, 0}}};
            for (auto& eye : p) {
                eye.x += 12 * std::sin(t * 6);
                eye.y += 10 * std::cos(t * 6);
            }
            break;
        default:
            for (auto& eye : p)
                eye.x += 8 * sway;
    }
    for (auto& eye : p)
        eye.y += 3.2f * std::sin(t * 1.15f);
    return p;
}

inline Eye Blend(const Eye& from, const Eye& to, float a) {
    return {from.x + (to.x - from.x) * a,
            from.y + (to.y - from.y) * a,
            from.width + (to.width - from.width) * a,
            from.height + (to.height - from.height) * a,
            from.angle + (to.angle - from.angle) * a,
            from.lid + (to.lid - from.lid) * a,
            from.brow + (to.brow - from.brow) * a};
}
}  // namespace kk
