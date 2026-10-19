#pragma once
// QMI8658 motion input for the Zongzhu boards: tilt for eye gaze and a
// left-right shake gesture. Shares the codec I2C bus. The including board's
// config.h maps chip axes to screen axes with QMI8658_SCREEN_X/Y.

#include <driver/i2c_master.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>

#if !defined(QMI8658_SCREEN_X) || !defined(QMI8658_SCREEN_Y)
#error "Define QMI8658_SCREEN_X/Y in the board config.h before including qmi8658_motion.h"
#endif

class Qmi8658Motion {
public:
    // tilt_x/tilt_y are -1..1 in screen coordinates (+x right, +y down).
    using TiltCallback = std::function<void(float tilt_x, float tilt_y)>;
    using ShakeCallback = std::function<void(bool active)>;

    explicit Qmi8658Motion(i2c_master_bus_handle_t bus) : bus_(bus) {}

    bool Start(TiltCallback on_tilt, ShakeCallback on_shake) {
        for (uint8_t addr : {0x6B, 0x6A}) {
            if (i2c_master_probe(bus_, addr, 50) == ESP_OK && Attach(addr))
                break;
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
    static constexpr uint32_t kPeriodMs = 20;
    static constexpr float kLsbPerG = 8192.0f;  // +-4g range

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
        // CTRL1 auto-increment/little endian; CTRL2 accel +-4g 125Hz;
        // CTRL3 gyro 512dps 125Hz; CTRL7 enable accel + gyro.
        const bool ok = Read(0x00, &who, 1) && who == 0x05 && Write(0x02, 0x40) &&
                        Write(0x03, 0x16) && Write(0x04, 0x56) && Write(0x08, 0x03);
        if (!ok) {
            ESP_LOGW(kTag, "0x%02x not usable (WHO_AM_I=0x%02x)", addr, who);
            i2c_master_bus_rm_device(dev_);
            dev_ = nullptr;
            return false;
        }
        ESP_LOGI(kTag, "QMI8658 at 0x%02x ready", addr);
        return true;
    }

    static float Shape(float d) {
        const float m = std::max(0.0f, std::fabs(d) - kDeadZoneG) / kFullTiltG;
        return std::copysign(std::min(1.0f, m), d);
    }

    void Loop() {
        float lp_x = 0, lp_y = 0;          // smoothed gravity on screen axes
        float slow_x = 0;                  // very slow baseline for the high-pass
        float centre_x = 0, centre_y = 0;  // resting attitude
        float activity = 0;
        int settled = 0;
        uint32_t still_since = 0;

        int lobes = 0, last_sign = 0;
        bool lobe_open = false;
        uint32_t last_lobe = 0, calm_since = 0;
        bool shaking = false;

        while (true) {
            vTaskDelay(pdMS_TO_TICKS(kPeriodMs));
            uint8_t raw[6];
            if (!Read(0x35, raw, sizeof(raw)))
                continue;
            float a[3];
            for (int i = 0; i < 3; ++i)
                a[i] = static_cast<int16_t>(raw[i * 2] | (raw[i * 2 + 1] << 8)) / kLsbPerG;
            const float sx = QMI8658_SCREEN_X(a);
            const float sy = QMI8658_SCREEN_Y(a);
            const uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;

            if (settled == 0) {
                lp_x = slow_x = sx;
                lp_y = sy;
            }
            lp_x += (sx - lp_x) * 0.15f;
            lp_y += (sy - lp_y) * 0.15f;
            slow_x += (sx - slow_x) * 0.05f;
            const float hp = sx - slow_x;
            activity = activity * 0.9f + std::fabs(hp) * 0.1f;

            if (settled < kSettleSamples) {
                centre_x = lp_x;
                centre_y = lp_y;
                if (++settled == kSettleSamples)
                    ESP_LOGI(kTag, "Motion ready, rest (%.2f, %.2f)", centre_x, centre_y);
                continue;
            }

            // Re-centre only after the board has rested for a while (e.g. on a stand).
            if (activity < kCalmG) {
                if (still_since == 0)
                    still_since = now;
                if (now - still_since > kRecentreAfterMs) {
                    centre_x += (lp_x - centre_x) * 0.02f;
                    centre_y += (lp_y - centre_y) * 0.02f;
                }
            } else {
                still_since = 0;
            }
            on_tilt_(Shape(lp_x - centre_x), Shape(lp_y - centre_y));

            if (!shaking) {
                if (lobes > 0 && now - last_lobe > kLobeMaxGapMs)
                    lobes = 0;
                if (lobe_open && std::fabs(hp) < kLobeResetG)
                    lobe_open = false;
                const int sign = hp > 0 ? 1 : -1;
                if (!lobe_open && std::fabs(hp) > kLobeG) {
                    lobe_open = true;
                    const uint32_t gap = now - last_lobe;
                    if (lobes == 0 || (sign != last_sign && gap >= kLobeMinGapMs))
                        ++lobes;
                    else
                        lobes = 1;
                    last_sign = sign;
                    last_lobe = now;
                    ESP_LOGI(kTag, "Shake lobe %d/%d", lobes, kLobesToTrigger);
                }
                if (lobes >= kLobesToTrigger) {
                    shaking = true;
                    lobes = 0;
                    calm_since = 0;
                    ESP_LOGI(kTag, "Shake: dizzy");
                    on_shake_(true);
                }
            } else if (activity < kCalmG) {
                if (calm_since == 0)
                    calm_since = now;
                else if (now - calm_since >= kCalmForMs) {
                    shaking = false;
                    ESP_LOGI(kTag, "Steady again");
                    on_shake_(false);
                }
            } else {
                calm_since = 0;
            }
        }
    }
};
