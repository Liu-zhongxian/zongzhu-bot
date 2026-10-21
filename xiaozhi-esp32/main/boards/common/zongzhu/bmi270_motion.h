#pragma once
// BMI270 motion input for the Zongzhu boards (M5Stack StopWatch): same tilt and
// shake gestures as qmi8658_motion.h. Only the accelerometer is used. The
// including board's config.h maps chip axes to screen axes with BMI270_SCREEN_X/Y.

#include <driver/i2c_master.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <algorithm>
#include <cstdint>

#include "motion_gesture.h"

#if !defined(BMI270_SCREEN_X) || !defined(BMI270_SCREEN_Y)
#error "Define BMI270_SCREEN_X/Y in the board config.h before including bmi270_motion.h"
#endif

// Bosch's 8 KB feature firmware, linked from the espressif/bmi270_sensor component.
extern "C" const uint8_t bmi270_config_file[];

class Bmi270Motion {
public:
    using TiltCallback = MotionGesture::TiltCallback;
    using ShakeCallback = MotionGesture::ShakeCallback;

    explicit Bmi270Motion(i2c_master_bus_handle_t bus) : bus_(bus) {}

    bool Start(TiltCallback on_tilt, ShakeCallback on_shake) {
        for (uint8_t addr : {0x68, 0x69}) {
            if (i2c_master_probe(bus_, addr, 50) == ESP_OK && Attach(addr))
                break;
        }
        if (!dev_) {
            ESP_LOGW(kTag, "BMI270 not found, motion disabled");
            return false;
        }
        gesture_.SetCallbacks(std::move(on_tilt), std::move(on_shake));
        xTaskCreate([](void* arg) { static_cast<Bmi270Motion*>(arg)->Loop(); }, "imu_motion",
                    3072, this, 2, nullptr);
        return true;
    }

private:
    static constexpr const char* kTag = "Bmi270Motion";
    static constexpr uint32_t kPeriodMs = 20;
    static constexpr float kLsbPerG = 8192.0f;  // +-4g range
    static constexpr size_t kConfigSize = 8192;
    static constexpr size_t kChunk = 64;

    // Registers
    static constexpr uint8_t kChipId = 0x00, kAccData = 0x0C, kInternalStatus = 0x21;
    static constexpr uint8_t kAccConf = 0x40, kAccRange = 0x41, kInitCtrl = 0x59;
    static constexpr uint8_t kInitAddr0 = 0x5B, kInitData = 0x5E, kPwrConf = 0x7C;
    static constexpr uint8_t kPwrCtrl = 0x7D, kCmd = 0x7E;

    i2c_master_bus_handle_t bus_;
    i2c_master_dev_handle_t dev_ = nullptr;
    MotionGesture gesture_;

    bool Write(uint8_t reg, const uint8_t* data, size_t len) {
        uint8_t buf[kChunk + 1];
        buf[0] = reg;
        std::copy(data, data + len, buf + 1);
        return i2c_master_transmit(dev_, buf, len + 1, 50) == ESP_OK;
    }

    bool Write(uint8_t reg, uint8_t value) { return Write(reg, &value, 1); }

    bool Read(uint8_t reg, uint8_t* data, size_t len) {
        return i2c_master_transmit_receive(dev_, &reg, 1, data, len, 50) == ESP_OK;
    }

    // Datasheet init: power save off, upload the config through INIT_DATA, wait
    // for INTERNAL_STATUS = 1, then run the accelerometer only.
    bool Initialize() {
        uint8_t id = 0;
        if (!Read(kChipId, &id, 1) || id != 0x24) {
            ESP_LOGW(kTag, "CHIP_ID=0x%02x", id);
            return false;
        }
        Write(kCmd, 0xB6);  // soft reset; the chip does not ack reliably here
        vTaskDelay(pdMS_TO_TICKS(5));
        if (!Write(kPwrConf, 0x00))
            return false;
        vTaskDelay(pdMS_TO_TICKS(1));
        if (!Write(kInitCtrl, 0x00))
            return false;
        for (size_t offset = 0; offset < kConfigSize; offset += kChunk) {
            // INIT_ADDR counts 16-bit words: bits 0-3 in 0x5B, bits 4-11 in 0x5C.
            const uint16_t word = offset / 2;
            const uint8_t addr[2] = {static_cast<uint8_t>(word & 0x0F), static_cast<uint8_t>(word >> 4)};
            if (!Write(kInitAddr0, addr, 2) || !Write(kInitData, bmi270_config_file + offset, kChunk))
                return false;
        }
        if (!Write(kInitCtrl, 0x01))
            return false;
        uint8_t status = 0;
        for (int i = 0; i < 15 && (status & 0x0F) != 0x01; ++i) {
            vTaskDelay(pdMS_TO_TICKS(10));
            Read(kInternalStatus, &status, 1);
        }
        if ((status & 0x0F) != 0x01) {
            ESP_LOGW(kTag, "Config load failed, INTERNAL_STATUS=0x%02x", status);
            return false;
        }
        // Accel on; 100 Hz, normal averaging, performance mode; +-4g.
        return Write(kPwrCtrl, 0x04) && Write(kAccConf, 0xA8) && Write(kAccRange, 0x01) &&
               Write(kPwrConf, 0x02);
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
        if (!Initialize()) {
            ESP_LOGW(kTag, "0x%02x not usable", addr);
            i2c_master_bus_rm_device(dev_);
            dev_ = nullptr;
            return false;
        }
        ESP_LOGI(kTag, "BMI270 at 0x%02x ready", addr);
        return true;
    }

    void Loop() {
        while (true) {
            vTaskDelay(pdMS_TO_TICKS(kPeriodMs));
            uint8_t raw[6];
            if (!Read(kAccData, raw, sizeof(raw)))
                continue;
            float a[3];
            for (int i = 0; i < 3; ++i)
                a[i] = static_cast<int16_t>(raw[i * 2] | (raw[i * 2 + 1] << 8)) / kLsbPerG;
            gesture_.Feed(BMI270_SCREEN_X(a), BMI270_SCREEN_Y(a),
                          xTaskGetTickCount() * portTICK_PERIOD_MS);
        }
    }
};
