#include "wifi_board.h"
#include "backlight.h"
#include "display/lcd_display.h"
#include "esp_lcd_co5300.h"
#include "codecs/es8311_audio_codec.h"
#include "application.h"
#include "button.h"
#include "M5IOE1.h"
#include "M5PM1.h"
#include "config.h"
#include "assets/lang_config.h"
#include <esp_log.h>
#include <driver/i2c_master.h>
#include <driver/spi_master.h>
#include <wifi_manager.h>

#if CONFIG_ZONGZHU_EYE_UI
#include "mcp_server.h"
#include "settings.h"
#include "zongzhu/bmi270_motion.h"
#include "zongzhu/eye_display.h"
#include "zongzhu/ota_default.h"
#include <esp_lcd_touch_cst816s.h>
#include <esp_lvgl_port.h>
#include <esp_timer.h>
#endif

#define TAG "M5StackStopwatch"
#define LCD_OPCODE_WRITE_CMD (0x02ULL)

// CO5300 AMOLED: initialize at full brightness, then restore the saved setting.
static const co5300_lcd_init_cmd_t vendor_specific_init[] = {
    // {cmd, { data }, data_size, delay_ms}
    {0xFE, (uint8_t []){0x00}, 0, 0},
    {0xC4, (uint8_t []){0x80}, 1, 0},
    {0x3A, (uint8_t []){0x55}, 0, 10}, // RGB565
    {0x35, (uint8_t []){0x00}, 0, 10},
    {0x53, (uint8_t []){0x20}, 1, 10},
    {0x51, (uint8_t []){0xFF}, 1, 10},
    {0x63, (uint8_t []){0xFF}, 1, 10},
    {0x2A, (uint8_t []){0x00, 0x00, 0x01, 0xD1}, 4, 0}, // Column address: 0-465
    {0x2B, (uint8_t []){0x00, 0x00, 0x01, 0xD1}, 4, 0}, // Row address: 0-465
    {0x11, (uint8_t []){0x00}, 0, 120}, // Exit sleep
    {0x29, (uint8_t []){0x00}, 0, 20},  // Display on
};

class RoundLcdDisplay : public SpiLcdDisplay {
public:
    static void rounder_event_cb(lv_event_t* e) {
        lv_area_t* area = static_cast<lv_area_t*>(lv_event_get_param(e));
        area->x1 = (area->x1 >> 1) << 1;
        area->y1 = (area->y1 >> 1) << 1;
        area->x2 = ((area->x2 >> 1) << 1) + 1;
        area->y2 = ((area->y2 >> 1) << 1) + 1;
    }

    RoundLcdDisplay(esp_lcd_panel_io_handle_t io_handle,
                    esp_lcd_panel_handle_t panel_handle,
                    int width,
                    int height,
                    int offset_x,
                    int offset_y,
                    bool mirror_x,
                    bool mirror_y,
                    bool swap_xy)
        : SpiLcdDisplay(io_handle, panel_handle, width, height, offset_x, offset_y, mirror_x, mirror_y, swap_xy) {}

    void SetupUI() override {
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);

        // Horizontal inset so labels stay inside the round mask
        lv_obj_set_style_pad_left(status_bar_, LV_HOR_RES * 0.2, 0);
        lv_obj_set_style_pad_right(status_bar_, LV_HOR_RES * 0.2, 0);

        // Status bar: upper half, below top icon bar (not at screen bottom)
        lv_obj_align(status_bar_, LV_ALIGN_TOP_MID, 0, DISPLAY_STATUS_BAR_TOP_OFF);
        lv_obj_set_width(status_label_, LV_HOR_RES * 0.6);
        lv_obj_set_width(notification_label_, LV_HOR_RES * 0.6);
        lv_obj_align(status_label_, LV_ALIGN_CENTER, 0, 0);
        lv_obj_align(notification_label_, LV_ALIGN_CENTER, 0, 0);

        // Chat/subtitle text: a bit higher, away from bottom arc
        if (bottom_bar_ != nullptr) {
            lv_obj_align(bottom_bar_, LV_ALIGN_BOTTOM_MID, 0, -DISPLAY_CHAT_BAR_BOTTOM_OFF);
            lv_obj_set_width(chat_message_label_, LV_HOR_RES * 0.75);
        }

        // emoji_box_: keep default LV_ALIGN_CENTER from SpiLcdDisplay::SetupUI()

        // Top icons: move the top bar down inside the round display safe area
        if (top_bar_ != nullptr) {
            lv_obj_align(top_bar_, LV_ALIGN_TOP_MID, 0, DISPLAY_ROUND_EDGE_INSET / 2);
            lv_obj_set_style_pad_top(top_bar_, DISPLAY_ROUND_EDGE_INSET / 4, 0);
        }

        lv_display_add_event_cb(display_, rounder_event_cb, LV_EVENT_INVALIDATE_AREA, NULL);
    }
};

#if CONFIG_ZONGZHU_EYE_UI
// Zongzhu eyes on the same 466x466 CO5300 as the Waveshare 1.75C, so the
// default EyeScreen layout applies unchanged.
class StopwatchEyeDisplay : public EyeDisplay {
public:
    using EyeDisplay::EyeDisplay;

    void SetupUI() override {
        EyeDisplay::SetupUI();
        DisplayLockGuard lock(this);
        lv_display_add_event_cb(display_, RoundLcdDisplay::rounder_event_cb, LV_EVENT_INVALIDATE_AREA, NULL);
    }
};
using BoardLcdDisplay = StopwatchEyeDisplay;
#else
using BoardLcdDisplay = RoundLcdDisplay;
#endif

class StopwatchBacklight : public Backlight {
public:
    StopwatchBacklight(esp_lcd_panel_io_handle_t panel_io, Display* display)
        : panel_io_(panel_io), display_(display) {}

protected:
    void SetBrightnessImpl(uint8_t brightness) override {
        DisplayLockGuard lock(display_);
        uint8_t data[] = {static_cast<uint8_t>((255 * brightness) / 100)};
        int lcd_cmd = 0x51;
        lcd_cmd &= 0xff;
        lcd_cmd <<= 8;
        lcd_cmd |= LCD_OPCODE_WRITE_CMD << 24;

        esp_err_t err = esp_lcd_panel_io_tx_param(panel_io_, lcd_cmd, data, sizeof(data));
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to set display brightness: %s", esp_err_to_name(err));
        }
    }

private:
    esp_lcd_panel_io_handle_t panel_io_;
    Display* display_;
};

class M5StackStopwatchBoard : public WifiBoard {
private:
    i2c_master_bus_handle_t i2c_bus_;
    M5PM1 pmic_;
    M5IOE1 ioe_;
    Button button1_;
    Button button2_;
    BoardLcdDisplay* display_;
    StopwatchBacklight* backlight_;
#if CONFIG_ZONGZHU_EYE_UI
    Bmi270Motion* motion_ = nullptr;
    esp_timer_handle_t motor_timer_ = nullptr;
    bool motor_ready_ = false;
    bool vibration_on_ = true;

    // Vibration motor on M5IOE1 IO9 (PWM channel 1), as in the community KK firmware.
    void InitializeMotor() {
        motor_ready_ = ioe_.setPwmFrequency(200) == M5IOE1_OK &&
                       ioe_.setPwmDuty12bit(M5IOE1_PWM_CH1, 0, false, true) == M5IOE1_OK;
        if (!motor_ready_) {
            ESP_LOGW(TAG, "Vibration motor PWM not available");
            return;
        }
        const esp_timer_create_args_t args = {
            .callback = [](void* arg) {
                auto self = static_cast<M5StackStopwatchBoard*>(arg);
                self->ioe_.setPwmDuty12bit(M5IOE1_PWM_CH1, 0, false, true);
            },
            .arg = this,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "motor_off",
            .skip_unhandled_events = true,
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &motor_timer_));
        Settings settings("board");
        vibration_on_ = settings.GetInt("vibration", 1) != 0;
    }

    // strength 0..255; ignored while vibration is switched off.
    void Vibrate(uint8_t strength, uint32_t duration_ms) {
        if (!motor_ready_ || !vibration_on_)
            return;
        esp_timer_stop(motor_timer_);
        ioe_.setPwmDuty12bit(M5IOE1_PWM_CH1, static_cast<uint16_t>(strength) * 0x0FFF / 0xFF, false, true);
        esp_timer_start_once(motor_timer_, duration_ms * 1000);
    }

    void InitializeTouch() {
        // CST820B: reset through M5IOE1, interrupt on G13; the CST816S driver speaks its protocol.
        ioe_.pinMode(IOE_PIN_TOUCH_RST, OUTPUT);
        ioe_.setDriveMode(IOE_PIN_TOUCH_RST, M5IOE1_DRIVE_PUSHPULL);
        ioe_.digitalWrite(IOE_PIN_TOUCH_RST, LOW);
        vTaskDelay(pdMS_TO_TICKS(10));
        ioe_.digitalWrite(IOE_PIN_TOUCH_RST, HIGH);
        vTaskDelay(pdMS_TO_TICKS(50));

        esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH - 1,
            .y_max = DISPLAY_HEIGHT - 1,
            .rst_gpio_num = GPIO_NUM_NC,
            .int_gpio_num = TOUCH_INT_PIN,
            .levels = {
                .reset = 0,
                .interrupt = 0,
            },
            .flags = {
                .swap_xy = 0,
                .mirror_x = 0,
                .mirror_y = 0,
            },
        };
        esp_lcd_panel_io_handle_t tp_io = nullptr;
        // ESP_LCD_TOUCH_IO_I2C_CST816S_CONFIG() uses C designator order, so fill it here.
        esp_lcd_panel_io_i2c_config_t tp_io_config = {};
        tp_io_config.dev_addr = ESP_LCD_TOUCH_IO_I2C_CST816S_ADDRESS;
        tp_io_config.scl_speed_hz = 100 * 1000;
        tp_io_config.control_phase_bytes = 1;
        tp_io_config.lcd_cmd_bits = 8;
        tp_io_config.flags.disable_control_phase = 1;
        esp_lcd_touch_handle_t tp = nullptr;
        if (esp_lcd_new_panel_io_i2c(i2c_bus_, &tp_io_config, &tp_io) != ESP_OK ||
            esp_lcd_touch_new_i2c_cst816s(tp_io, &tp_cfg, &tp) != ESP_OK) {
            ESP_LOGE(TAG, "CST820B touch init failed");
            return;
        }
        const lvgl_port_touch_cfg_t touch_cfg = {
            .disp = lv_display_get_default(),
            .handle = tp,
        };
        lvgl_port_add_touch(&touch_cfg);
        ESP_LOGI(TAG, "Touch panel initialized");
        display_->OnReaction([this](eyes::Mood mood) {
            Vibrate(mood == eyes::Mood::Angry ? 200 : 130, mood == eyes::Mood::Angry ? 120 : 40);
        });
    }

    void InitializeMotion() {
        motion_ = new Bmi270Motion(i2c_bus_);
        motion_->Start([this](float x, float y) { display_->SetTilt(x, y); },
                       [this](bool active) {
                           display_->SetDizzy(active);
                           if (active)
                               Vibrate(220, 200);
                       });
    }

    void InitializeTools() {
        auto& mcp_server = McpServer::GetInstance();
        mcp_server.AddTool("self.zongzhu.play_animation",
            "Play Zongzhu eye reactions for 12 seconds. Use when asked to sing, "
            "dance, rap or play basketball. This changes the screen, not the audio. "
            "action must be singing, dancing, rapper or basketball.",
            PropertyList({Property("action", kPropertyTypeString)}),
            [this](const PropertyList& properties) -> ReturnValue {
                const auto action = properties["action"].value<std::string>();
                if (action != "singing" && action != "dancing" && action != "rapper" &&
                    action != "basketball") {
                    return std::string("Unsupported animation action");
                }
                Application::GetInstance().Schedule([this, action]() {
                    display_->PlayPerformance(action);
                });
                return true;
            });
    }
#endif

    void InitializeI2c() {
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = I2C_NUM_0,
            .sda_io_num = AUDIO_CODEC_I2C_SDA_PIN,
            .scl_io_num = AUDIO_CODEC_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = {.enable_internal_pullup = 1},
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));

        if (ioe_.begin(i2c_bus_, M5IOE1_I2C_ADDR, M5IOE1_I2C_FREQ_100K, M5IOE1_INT_MODE_POLLING) != M5IOE1_OK) {
            ESP_LOGE(TAG, "M5IOE1 begin failed");
            return;
        }

        if (pmic_.begin(i2c_bus_, M5PM1_DEFAULT_ADDR, M5PM1_I2C_FREQ_100K) != M5PM1_OK) {
            ESP_LOGE(TAG, "M5PM1 begin failed");
            return;
        }

        pmic_.setChargeEnable(true);
        pmic_.setBoostEnable(true);
        pmic_.pinMode(PMIC_PIN_CHARGE_STATE, INPUT);
        pmic_.pinMode(PMIC_PIN_CHARGE_PROG, OUTPUT);
        pmic_.digitalWrite(PMIC_PIN_CHARGE_PROG, LOW); // Set charge current to 425mA

        ioe_.pinMode(IOE_PIN_LCD_POWER, OUTPUT);
        ioe_.setDriveMode(IOE_PIN_LCD_POWER, M5IOE1_DRIVE_PUSHPULL);
        ioe_.digitalWrite(IOE_PIN_LCD_POWER, HIGH);

        ioe_.pinMode(IOE_PIN_LCD_RST, OUTPUT);
        ioe_.setDriveMode(IOE_PIN_LCD_RST, M5IOE1_DRIVE_PUSHPULL);
        ioe_.digitalWrite(IOE_PIN_LCD_RST, HIGH);

        ioe_.pinMode(IOE_PIN_CODEC_POWER, OUTPUT);
        ioe_.setDriveMode(IOE_PIN_CODEC_POWER, M5IOE1_DRIVE_PUSHPULL);
        ioe_.digitalWrite(IOE_PIN_CODEC_POWER, HIGH);

        ioe_.pinMode(IOE_PIN_PA_EN, OUTPUT);
        ioe_.setDriveMode(IOE_PIN_PA_EN, M5IOE1_DRIVE_PUSHPULL);
        ioe_.digitalWrite(IOE_PIN_PA_EN, HIGH);

#if !CONFIG_ZONGZHU_EYE_UI
        ioe_.pinMode(IOE_PIN_MOTOR, OUTPUT);
        ioe_.setDriveMode(IOE_PIN_MOTOR, M5IOE1_DRIVE_PUSHPULL);
        ioe_.digitalWrite(IOE_PIN_MOTOR, LOW);
#endif

        vTaskDelay(pdMS_TO_TICKS(100));
    }

    void InitializeSpi() {
        spi_bus_config_t buscfg = {};
        buscfg.sclk_io_num = DISPLAY_QSPI_SCK;
        buscfg.data0_io_num = DISPLAY_QSPI_D0;
        buscfg.data1_io_num = DISPLAY_QSPI_D1;
        buscfg.data2_io_num = DISPLAY_QSPI_D2;
        buscfg.data3_io_num = DISPLAY_QSPI_D3;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        buscfg.flags = SPICOMMON_BUSFLAG_QUAD;
        ESP_ERROR_CHECK(spi_bus_initialize(DISPLAY_QSPI_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

    void InitializeDisplay() {
        ioe_.digitalWrite(IOE_PIN_LCD_RST, LOW);
        vTaskDelay(pdMS_TO_TICKS(10));
        ioe_.digitalWrite(IOE_PIN_LCD_RST, HIGH);
        vTaskDelay(pdMS_TO_TICKS(120));

        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;

        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = DISPLAY_QSPI_CS;
        io_config.dc_gpio_num = GPIO_NUM_NC;
        io_config.spi_mode = 0;
        io_config.pclk_hz = 40 * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 32;
        io_config.lcd_param_bits = 8;
        io_config.flags.quad_mode = true;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(DISPLAY_QSPI_HOST, &io_config, &panel_io));

        co5300_vendor_config_t vendor_config = {
            .init_cmds = &vendor_specific_init[0],
            .init_cmds_size = sizeof(vendor_specific_init) / sizeof(co5300_lcd_init_cmd_t),
            .flags = {.use_qspi_interface = 1},
        };

        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
        panel_config.bits_per_pixel = 16;
        panel_config.vendor_config = &vendor_config;
        ESP_ERROR_CHECK(esp_lcd_new_panel_co5300(panel_io, &panel_config, &panel));

        esp_lcd_panel_set_gap(panel, 0x06, 0);
        esp_lcd_panel_reset(panel);
        esp_lcd_panel_init(panel);
        esp_lcd_panel_invert_color(panel, false);
        esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        esp_lcd_panel_disp_on_off(panel, true);

        display_ = new BoardLcdDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                       DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X,
                                       DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
        backlight_ = new StopwatchBacklight(panel_io, display_);
        backlight_->RestoreBrightness();
    }

    void InitializeButtons() {
        // Button1 (A, yellow): wake / toggle conversation
        button1_.OnClick([this]() {
#if CONFIG_ZONGZHU_EYE_UI
            Vibrate(130, 40);
#endif
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting && !WifiManager::GetInstance().IsConnected()) {
                EnterWifiConfigMode();
                return;
            }
            app.ToggleChatState();
        });

#if CONFIG_ZONGZHU_EYE_UI
        // A long press: cycle subtitles full -> brief -> off (saved in NVS).
        button1_.OnLongPress([this]() {
            Vibrate(160, 80);
            display_->ShowNotification(display_->CycleSubtitleMode(), 2000);
        });

        // B long press: vibration on / off (saved in NVS).
        button2_.OnLongPress([this]() {
            vibration_on_ = !vibration_on_;
            Settings settings("board", true);
            settings.SetInt("vibration", vibration_on_ ? 1 : 0);
            Vibrate(160, 120);
            display_->ShowNotification(vibration_on_ ? "震动：开" : "震动：关", 2000);
        });
#endif

        // Button2 (B, blue): volume 0 -> 10 -> ... -> 100 -> 0
        button2_.OnClick([this]() {
#if CONFIG_ZONGZHU_EYE_UI
            Vibrate(130, 40);
#endif
            auto* codec = GetAudioCodec();
            int volume = codec->output_volume() + 10;
            if (volume > 100) {
                volume = 0;
            }
            codec->SetOutputVolume(volume);
            GetDisplay()->ShowNotification(std::string(Lang::Strings::VOLUME) + ":" + std::to_string(volume) + "%");
        });
    }

public:
    M5StackStopwatchBoard()
        : i2c_bus_(nullptr),
          button1_(BUTTON1_GPIO),
          button2_(BUTTON2_GPIO),
          display_(nullptr),
          backlight_(nullptr) {
#if CONFIG_ZONGZHU_EYE_UI
        SeedDefaultOtaUrl();
#endif
        InitializeI2c();
        InitializeSpi();
        InitializeDisplay();
#if CONFIG_ZONGZHU_EYE_UI
        InitializeMotor();
        InitializeTouch();
        InitializeMotion();
        InitializeTools();
#endif
        InitializeButtons();
    }

    AudioCodec* GetAudioCodec() override {
        static Es8311AudioCodec audio_codec(
            i2c_bus_,
            I2C_NUM_0,
            AUDIO_INPUT_SAMPLE_RATE,
            AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_GPIO_MCLK,
            AUDIO_I2S_GPIO_BCLK,
            AUDIO_I2S_GPIO_WS,
            AUDIO_I2S_GPIO_DOUT,
            AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_GPIO_PA,
            AUDIO_CODEC_ES8311_ADDR,
            false);
        return &audio_codec;
    }

    Display* GetDisplay() override {
        return display_;
    }

    Backlight* GetBacklight() override {
        return backlight_;
    }

    bool GetBatteryLevel(int& level, bool& charging, bool& discharging) override {
        uint16_t voltage_mv = 0;
        if (pmic_.readVbat(&voltage_mv) != M5PM1_OK) {
            return false;
        }

        int charge_state_level = pmic_.digitalRead(PMIC_PIN_CHARGE_STATE);
        if (charge_state_level < 0) {
            // Charge status read failed; leave charging/discharging unknown
            charging = false;
            discharging = false;
        } else {
            // M5PM1 charge status is active low: 0 means charging, 1 means not charging
            charging = (charge_state_level == 0);
            discharging = !charging;
        }

        const int BATTERY_MIN_VOLTAGE = 3400;
        const int BATTERY_MAX_VOLTAGE = 4200;
        if (voltage_mv < BATTERY_MIN_VOLTAGE) {
            level = 0;
        } else if (voltage_mv > BATTERY_MAX_VOLTAGE) {
            level = 100;
        } else {
            level = ((voltage_mv - BATTERY_MIN_VOLTAGE) * 100) / (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE);
        }
        return true;
    }
};

DECLARE_BOARD(M5StackStopwatchBoard);
