#pragma once
// Zongzhu eye model: per-mood eye shapes and idle motion, independent of LVGL
// so it can be checked on the host. Units are screen pixels at full size.

#include <cmath>
#include <cstdint>

namespace eyes {

enum class Mood : uint8_t {
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
    Dizzy,
    Count
};

// One eye, relative to its home position.
struct Shape {
    float dx = 0, dy = 0;  // offset from home
    float w = 76, h = 150; // body size
    float tilt = 0;        // degrees, clockwise
    float lid = 0;         // 0..1 of the body hidden from the top
    float lid_tilt = 0;    // degrees of the lid edge, clockwise
    float arc = 0;         // +1 happy cap, -1 sleepy slit, 0 plain body
    float spin = 0;        // 0..1 dizzy swirl
};

struct Face {
    Shape left, right;  // screen left / right
};

constexpr float kHomeX = 100;      // half the distance between eye centres
constexpr float kMaxReach = 200;   // nothing may leave this radius from the face centre

inline float Wave(float t, float hz, float phase = 0) {
    return std::sin((t * hz + phase) * 6.2831853f);
}

// Mirror a left-eye shape to the right eye.
inline Shape Mirror(Shape s) {
    s.dx = -s.dx;
    s.tilt = -s.tilt;
    s.lid_tilt = -s.lid_tilt;
    return s;
}

inline Face FaceFor(Mood mood, float t) {
    Shape l;
    Face f;
    switch (mood) {
        case Mood::Listening:
            l.w = 82;
            l.h = 140 + 6 * Wave(t, 0.9f);
            l.tilt = -4;
            l.dy = -4;
            f = {l, Mirror(l)};
            f.right.h = 140 - 6 * Wave(t, 0.9f);
            break;
        case Mood::Thinking:
            l.w = 80;
            l.h = 124;
            l.dx = -16 + 6 * Wave(t, 0.25f);
            l.dy = -18;
            f = {l, l};
            f.right.h = 108;
            f.right.lid = 0.18f;
            f.right.lid_tilt = -8;
            break;
        case Mood::Speaking:
            l.w = 80 - 3 * Wave(t, 5.3f);
            l.h = 136 + 9 * Wave(t, 5.3f) + 5 * Wave(t, 3.1f, 0.3f);
            f = {l, l};
            break;
        case Mood::Happy:
            l.arc = 1;
            l.w = 104;
            l.h = 104;
            l.dy = 8 + 4 * std::fabs(Wave(t, 1.6f));
            l.tilt = -6;
            f = {l, Mirror(l)};
            break;
        case Mood::Excited:
            l.w = 94;
            l.h = 156;
            l.dy = -6 - 6 * std::fabs(Wave(t, 2.4f));
            f = {l, l};
            break;
        case Mood::Curious:
            l.w = 86;
            l.h = 166;
            l.tilt = -6;
            l.dy = -6;
            f = {l, l};
            f.right.w = 70;
            f.right.h = 112;
            f.right.lid = 0.12f;
            break;
        case Mood::Confused:
            l.w = 80;
            l.h = 132 + 10 * Wave(t, 0.6f);
            l.tilt = 8;
            f = {l, l};
            f.right.h = 112 - 10 * Wave(t, 0.6f);
            f.right.tilt = -5;
            f.right.dy = -10;
            break;
        case Mood::Angry:
            l.w = 92;
            l.h = 118;
            l.dy = 4;
            l.lid = 0.36f;
            l.lid_tilt = 16;  // inner edge lower
            f = {l, Mirror(l)};
            break;
        case Mood::Surprised:
            l.w = l.h = 118 + 4 * Wave(t, 1.2f);
            l.dy = -10;
            f = {l, l};
            break;
        case Mood::Sad:
            l.w = 86;
            l.h = 108;
            l.dy = 20 + 3 * Wave(t, 0.4f);
            l.lid = 0.3f;
            l.lid_tilt = -14;  // outer edge lower
            f = {l, Mirror(l)};
            break;
        case Mood::Sleepy:
            l.arc = -1;
            l.w = 112;
            l.h = 112;
            l.dy = 26 + 4 * Wave(t, 0.22f);
            l.tilt = 4;
            f = {l, Mirror(l)};
            break;
        case Mood::Dizzy:
            l.w = l.h = 108;
            l.spin = 1;
            l.dx = 7 * Wave(t, 0.9f);
            l.dy = 7 * Wave(t, 0.9f, 0.25f);
            f = {l, l};
            f.right.dx = -l.dx;
            break;
        default:  // Idle
            l.h = 150 + 3 * Wave(t, 0.3f);
            l.dy = 2 * Wave(t, 0.17f);
            f = {l, l};
            break;
    }
    return f;
}

inline float Lerp(float a, float b, float k) { return a + (b - a) * k; }

inline Shape Mix(const Shape& a, const Shape& b, float k) {
    Shape s;
    s.dx = Lerp(a.dx, b.dx, k);
    s.dy = Lerp(a.dy, b.dy, k);
    s.w = Lerp(a.w, b.w, k);
    s.h = Lerp(a.h, b.h, k);
    s.tilt = Lerp(a.tilt, b.tilt, k);
    s.lid = Lerp(a.lid, b.lid, k);
    s.lid_tilt = Lerp(a.lid_tilt, b.lid_tilt, k);
    s.arc = Lerp(a.arc, b.arc, k);
    s.spin = Lerp(a.spin, b.spin, k);
    return s;
}

// Frame-rate independent easing: fraction of the remaining distance to cover.
inline float Ease(float dt_ms, float rate_per_s = 11) {
    return 1.0f - std::exp(-dt_ms * 0.001f * rate_per_s);
}

}  // namespace eyes
