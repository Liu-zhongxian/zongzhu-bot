#pragma once
// SPDX-License-Identifier: AGPL-3.0-or-later
// Tilt and shake thresholds adapted from Trentct/m5stack-stopwatch-avatar (2049632),
// see kk-avatar-NOTICE.md. The QMI8658 register access is written for the 1.75C board.

#include <driver/i2c_master.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>

class Qmi8658Motion {
public:
    // tilt_x/tilt_y are in -1..1 screen coordinates (+x right, +y down).
    using TiltCallback = std::function<void(float tilt_x, float tilt_y)>;
    using ShakeCallback = std::function<void(bool active)>;

    Qmi8658Motion(i2c_master_bus_handle_t bus) : bus_(bus) {}

    bool Start(TiltCallback on_tilt, ShakeCallback on_shake) {
        for (uint8_t addr : {0x6B, 0x6A}) {
            if (i2c_master_probe(bus_, addr, 50) == ESP_OK && Attach(addr)) {
                break;
            }
        }
        if (!dev_) {
            ESP_LOGW(kTag, "QMI8658 not found, motion disabled");
            return false;
        }
        on_tilt_ = std::move(on_tilt);
        on_shake_ = std::move(on_shake);
        xTaskCreate([](void* arg) { static_cast<Qmi8658Motion*>(arg)->Loop(); }, "imu_motion",
                    3072, this, 2, nullptr);
        return true;
    }

private:
    static constexpr const char* kTag = "Qmi8658Motion";
    static constexpr uint32_t kIntervalMs = 20;
    static constexpr uint32_t kShakeReleaseDelayMs = 650;
    static constexpr uint32_t kShakeSequenceTimeoutMs = 1500;
    static constexpr uint32_t kShakeMaximumSwingGapMs = 480;
    static constexpr uint32_t kShakeMinimumSwingGapMs = 90;
    static constexpr float kStrongShakeAxisDelta = 0.32f;
    static constexpr float kStrongShakeJerk = 0.50f;
    static constexpr int kRequiredShakeSwings = 4;
    static constexpr int kCalibrationSamples = 30;
    // CTRL2 range +-4g => 8192 LSB/g.
    static constexpr float kAccelLsbPerG = 8192.0f;

    i2c_master_bus_handle_t bus_;
    i2c_master_dev_handle_t dev_ = nullptr;
    TiltCallback on_tilt_;
    ShakeCallback on_shake_;

    bool Write(uint8_t reg, uint8_t value) {
        uint8_t buf[2] = {reg, value};
        return i2c_master_transmit(dev_, buf, 2, 50) == ESP_OK;
    }

    bool Read(uint8_t reg, uint8_t* data, size_t len) {
        return i2c_master_transmit_receive(dev_, &reg, 1, data, len, 50) == ESP_OK;
    }

    bool Attach(uint8_t addr) {
        i2c_device_config_t cfg = {};
        cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
        cfg.device_address = addr;
        cfg.scl_speed_hz = 400 * 1000;
        if (i2c_master_bus_add_device(bus_, &cfg, &dev_) != ESP_OK) {
            dev_ = nullptr;
            return false;
        }
        uint8_t who = 0;
        if (!Read(0x00, &who, 1) || who != 0x05) {
            ESP_LOGW(kTag, "0x%02x WHO_AM_I=0x%02x, skip", addr, who);
            i2c_master_bus_rm_device(dev_);
            dev_ = nullptr;
            return false;
        }
        // CTRL1: register auto-increment, little endian.
        // CTRL2: accel +-4g, 125Hz. CTRL3: gyro 512dps, 125Hz. CTRL7: enable accel+gyro.
        bool ok = Write(0x02, 0x40) && Write(0x03, 0x16) && Write(0x04, 0x56) && Write(0x08, 0x03);
        ESP_LOGI(kTag, "QMI8658 at 0x%02x %s", addr, ok ? "ready" : "init failed");
        if (!ok) {
            i2c_master_bus_rm_device(dev_);
            dev_ = nullptr;
        }
        return ok;
    }

    // Board orientation: chip X/Y are mapped to screen axes here.
    static void ToScreen(const float a[3], float& sx, float& sy) {
        sx = QMI8658_SCREEN_X(a);
        sy = QMI8658_SCREEN_Y(a);
    }

    void Loop() {
        float neutral_x = 0, neutral_y = 0, filtered_x = 0, filtered_y = 0;
        float prev_x = 0, prev_y = 0, shake_energy = 0;
        int calibration = 0;
        int swings = 0;
        int prev_direction = 0;
        uint32_t sequence_start = 0, last_swing = 0, quiet_since = 0;
        bool shaking = false;
        uint32_t last_log = 0;

        while (true) {
            vTaskDelay(pdMS_TO_TICKS(kIntervalMs));
            uint8_t raw[6];
            if (!Read(0x35, raw, sizeof(raw))) {
                continue;
            }
            float a[3];
            for (int i = 0; i < 3; ++i) {
                a[i] = static_cast<int16_t>(raw[i * 2] | (raw[i * 2 + 1] << 8)) / kAccelLsbPerG;
            }
            float sx, sy;
            ToScreen(a, sx, sy);
            const uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
            if (now - last_log > 2000) {
                last_log = now;
                ESP_LOGD(kTag, "accel x=%.2f y=%.2f z=%.2f screen=(%.2f, %.2f)", a[0], a[1], a[2],
                         sx, sy);
            }

            if (calibration == 0) {
                filtered_x = prev_x = sx;
                filtered_y = prev_y = sy;
            }
            const float delta_x = sx - prev_x;
            const float delta_y = sy - prev_y;
            prev_x = sx;
            prev_y = sy;
            filtered_x += (sx - filtered_x) * 0.18f;
            filtered_y += (sy - filtered_y) * 0.18f;

            if (calibration < kCalibrationSamples) {
                neutral_x += sx / kCalibrationSamples;
                neutral_y += sy / kCalibrationSamples;
                if (++calibration == kCalibrationSamples) {
                    ESP_LOGI(kTag, "Motion ready: neutral x=%.2f y=%.2f", neutral_x, neutral_y);
                }
                continue;
            }
            // Roughly 0.28 g of tilt reaches full gaze travel; the neutral slowly follows
            // a new resting angle so a desk stand does not leave the eyes off-centre.
            if (!shaking) {
                neutral_x += (filtered_x - neutral_x) * 0.002f;
                neutral_y += (filtered_y - neutral_y) * 0.002f;
            }
            on_tilt_(std::clamp((filtered_x - neutral_x) / 0.28f, -1.0f, 1.0f),
                     std::clamp((filtered_y - neutral_y) / 0.28f, -1.0f, 1.0f));

            const float jerk = std::sqrt(delta_x * delta_x + delta_y * delta_y);
            shake_energy = shake_energy * 0.72f + jerk * 0.28f;

            if (!shaking) {
                if (swings > 0 && (now - sequence_start > kShakeSequenceTimeoutMs ||
                                   now - last_swing > kShakeMaximumSwingGapMs)) {
                    swings = 0;
                    prev_direction = 0;
                }
                const bool strong = jerk >= kStrongShakeJerk && std::fabs(delta_x) >= kStrongShakeAxisDelta;
                const int direction = delta_x >= 0 ? 1 : -1;
                if (strong && swings == 0) {
                    swings = 1;
                    prev_direction = direction;
                    sequence_start = last_swing = now;
                } else if (strong && direction != prev_direction &&
                           now - last_swing >= kShakeMinimumSwingGapMs &&
                           now - last_swing <= kShakeMaximumSwingGapMs) {
                    ++swings;
                    prev_direction = direction;
                    last_swing = now;
                    ESP_LOGI(kTag, "Horizontal swing %d/%d", swings, kRequiredShakeSwings);
                }
                if (swings >= kRequiredShakeSwings) {
                    shaking = true;
                    quiet_since = 0;
                    swings = 0;
                    ESP_LOGI(kTag, "Shake detected: dizzy");
                    on_shake_(true);
                }
            } else if (shake_energy < 0.08f) {
                if (quiet_since == 0) {
                    quiet_since = now;
                } else if (now - quiet_since >= kShakeReleaseDelayMs) {
                    shaking = false;
                    ESP_LOGI(kTag, "Device steady: dizzy released");
                    on_shake_(false);
                }
            } else {
                quiet_since = 0;
            }
        }
    }
};
