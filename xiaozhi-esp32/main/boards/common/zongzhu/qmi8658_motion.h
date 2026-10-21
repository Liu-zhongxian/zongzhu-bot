#pragma once
// QMI8658 motion input for the Zongzhu boards: tilt for eye gaze and a
// left-right shake gesture (detection in motion_gesture.h). Shares the codec
// I2C bus. The including board's config.h maps chip axes to screen axes with
// QMI8658_SCREEN_X/Y.

#include <driver/i2c_master.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdint>

#include "motion_gesture.h"

#if !defined(QMI8658_SCREEN_X) || !defined(QMI8658_SCREEN_Y)
#error "Define QMI8658_SCREEN_X/Y in the board config.h before including qmi8658_motion.h"
#endif

class Qmi8658Motion {
public:
    using TiltCallback = MotionGesture::TiltCallback;
    using ShakeCallback = MotionGesture::ShakeCallback;

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
        gesture_.SetCallbacks(std::move(on_tilt), std::move(on_shake));
        xTaskCreate([](void* arg) { static_cast<Qmi8658Motion*>(arg)->Loop(); }, "imu_motion",
                    3072, this, 2, nullptr);
        return true;
    }

private:
    static constexpr const char* kTag = "Qmi8658Motion";
    static constexpr uint32_t kPeriodMs = 20;
    static constexpr float kLsbPerG = 8192.0f;  // +-4g range

    i2c_master_bus_handle_t bus_;
    i2c_master_dev_handle_t dev_ = nullptr;
    MotionGesture gesture_;

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

    void Loop() {
        while (true) {
            vTaskDelay(pdMS_TO_TICKS(kPeriodMs));
            uint8_t raw[6];
            if (!Read(0x35, raw, sizeof(raw)))
                continue;
            float a[3];
            for (int i = 0; i < 3; ++i)
                a[i] = static_cast<int16_t>(raw[i * 2] | (raw[i * 2 + 1] << 8)) / kLsbPerG;
            gesture_.Feed(QMI8658_SCREEN_X(a), QMI8658_SCREEN_Y(a),
                          xTaskGetTickCount() * portTICK_PERIOD_MS);
        }
    }
};
