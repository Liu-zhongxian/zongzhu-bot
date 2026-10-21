#pragma once
// Tilt and shake detection for the Zongzhu eyes, shared by the IMU drivers.
// Feed() takes gravity on screen axes (+x right, +y down) in g every ~20 ms.

#include <esp_log.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <utility>

class MotionGesture {
public:
    // tilt_x/tilt_y are -1..1 in screen coordinates (+x right, +y down).
    using TiltCallback = std::function<void(float tilt_x, float tilt_y)>;
    using ShakeCallback = std::function<void(bool active)>;

    void SetCallbacks(TiltCallback on_tilt, ShakeCallback on_shake) {
        on_tilt_ = std::move(on_tilt);
        on_shake_ = std::move(on_shake);
    }

    void Feed(float sx, float sy, uint32_t now) {
        if (settled_ == 0) {
            lp_x_ = slow_x_ = sx;
            lp_y_ = sy;
        }
        lp_x_ += (sx - lp_x_) * 0.15f;
        lp_y_ += (sy - lp_y_) * 0.15f;
        slow_x_ += (sx - slow_x_) * 0.05f;
        const float hp = sx - slow_x_;
        activity_ = activity_ * 0.9f + std::fabs(hp) * 0.1f;

        if (settled_ < kSettleSamples) {
            centre_x_ = lp_x_;
            centre_y_ = lp_y_;
            if (++settled_ == kSettleSamples)
                ESP_LOGI(kTag, "Motion ready, rest (%.2f, %.2f)", centre_x_, centre_y_);
            return;
        }

        // Re-centre only after the board has rested for a while (e.g. on a stand).
        if (activity_ < kCalmG) {
            if (still_since_ == 0)
                still_since_ = now;
            if (now - still_since_ > kRecentreAfterMs) {
                centre_x_ += (lp_x_ - centre_x_) * 0.02f;
                centre_y_ += (lp_y_ - centre_y_) * 0.02f;
            }
        } else {
            still_since_ = 0;
        }
        if (on_tilt_)
            on_tilt_(Shape(lp_x_ - centre_x_), Shape(lp_y_ - centre_y_));

        if (!shaking_) {
            if (lobes_ > 0 && now - last_lobe_ > kLobeMaxGapMs)
                lobes_ = 0;
            if (lobe_open_ && std::fabs(hp) < kLobeResetG)
                lobe_open_ = false;
            const int sign = hp > 0 ? 1 : -1;
            if (!lobe_open_ && std::fabs(hp) > kLobeG) {
                lobe_open_ = true;
                const uint32_t gap = now - last_lobe_;
                if (lobes_ == 0 || (sign != last_sign_ && gap >= kLobeMinGapMs))
                    ++lobes_;
                else
                    lobes_ = 1;
                last_sign_ = sign;
                last_lobe_ = now;
                ESP_LOGI(kTag, "Shake lobe %d/%d", lobes_, kLobesToTrigger);
            }
            if (lobes_ >= kLobesToTrigger) {
                shaking_ = true;
                lobes_ = 0;
                calm_since_ = 0;
                ESP_LOGI(kTag, "Shake: dizzy");
                if (on_shake_)
                    on_shake_(true);
            }
        } else if (activity_ < kCalmG) {
            if (calm_since_ == 0)
                calm_since_ = now;
            else if (now - calm_since_ >= kCalmForMs) {
                shaking_ = false;
                ESP_LOGI(kTag, "Steady again");
                if (on_shake_)
                    on_shake_(false);
            }
        } else {
            calm_since_ = 0;
        }
    }

private:
    static constexpr const char* kTag = "MotionGesture";

    // Tilt
    static constexpr float kDeadZoneG = 0.03f;
    static constexpr float kFullTiltG = 0.30f;
    static constexpr uint32_t kRecentreAfterMs = 3000;
    static constexpr int kSettleSamples = 25;

    // Shake: alternating left/right lobes of the high-passed X acceleration.
    static constexpr float kLobeG = 0.55f;      // a lobe must exceed this
    static constexpr float kLobeResetG = 0.2f;  // and fall back below this before the next
    static constexpr uint32_t kLobeMinGapMs = 70;
    static constexpr uint32_t kLobeMaxGapMs = 450;
    static constexpr int kLobesToTrigger = 4;
    static constexpr float kCalmG = 0.06f;
    static constexpr uint32_t kCalmForMs = 700;

    TiltCallback on_tilt_;
    ShakeCallback on_shake_;

    float lp_x_ = 0, lp_y_ = 0;          // smoothed gravity on screen axes
    float slow_x_ = 0;                   // very slow baseline for the high-pass
    float centre_x_ = 0, centre_y_ = 0;  // resting attitude
    float activity_ = 0;
    int settled_ = 0;
    uint32_t still_since_ = 0;

    int lobes_ = 0, last_sign_ = 0;
    bool lobe_open_ = false;
    uint32_t last_lobe_ = 0, calm_since_ = 0;
    bool shaking_ = false;

    static float Shape(float d) {
        const float m = std::max(0.0f, std::fabs(d) - kDeadZoneG) / kFullTiltG;
        return std::copysign(std::min(1.0f, m), d);
    }
};
