#pragma once

#include "application.h"
#include "assets.h"
#include "display/lcd_display.h"
#include "ikun_assets.h"

#include <cstring>

// The 466px circular glass clips the corners of the square LVGL framebuffer.
class IkunRoundDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;

    void SetupUI() override {
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);
        for (auto bar : {top_bar_, status_bar_}) {
            lv_obj_set_size(bar, 288, 48);
            lv_obj_set_style_pad_all(bar, 0, 0);
            lv_obj_align(bar, LV_ALIGN_TOP_MID, 0, 64);
        }
        lv_obj_set_size(top_bar_, 176, 36);
        lv_obj_align(top_bar_, LV_ALIGN_TOP_MID, 0, 28);
        lv_obj_set_width(status_label_, 280);
        lv_label_set_long_mode(status_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);
        lv_obj_set_width(notification_label_, 280);
        lv_label_set_long_mode(notification_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);
        lv_obj_set_style_bg_opa(top_bar_, LV_OPA_TRANSP, 0);

        lv_obj_set_size(emoji_box_, 216, 234);
        lv_obj_align(emoji_box_, LV_ALIGN_TOP_MID, 0, 102);
        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_SCROLLABLE);

        lv_obj_set_size(bottom_bar_, 284, 90);
        lv_obj_set_style_pad_all(bottom_bar_, 0, 0);
        lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_TRANSP, 0);
        lv_obj_align(bottom_bar_, LV_ALIGN_TOP_MID, 0, 320);
        lv_obj_remove_flag(bottom_bar_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_width(chat_message_label_, 284);
        lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_line_space(chat_message_label_, 4, 0);
        lv_obj_align(chat_message_label_, LV_ALIGN_TOP_MID, 0, 0);

        // Keep the low-battery warning inside the same safe circle.
        lv_obj_set_width(low_battery_popup_, 300);
        lv_obj_center(low_battery_popup_);
        ShowAnimation("neutral");
        ESP_LOGI("IkunUI", "Round layout ready: 466x466, IKUN 216x234, subtitle 284x90");
    }

    void SetStatus(const char* status) override {
        const std::string title = std::string("宗主 · ") + status;
        SpiLcdDisplay::SetStatus(title.c_str());
        SetEmotion(strncmp(status, "等待 Bot", strlen("等待 Bot")) == 0 ? "thinking" : "neutral");
    }

    void SetEmotion(const char* emotion) override {
        if (!setup_ui_called_) {
            return;
        }
        DisplayLockGuard lock(this);
        if (performance_timer_) {
            return;
        }
        static constexpr const char* emotions[] = {
            "happy",       "laughing",  "funny",     "sad",      "angry",   "crying",  "loving",
            "embarrassed", "surprised", "shocked",   "thinking", "winking", "cool",    "relaxed",
            "delicious",   "kissy",     "confident", "sleepy",   "silly",   "confused"};
        for (const auto* name : emotions) {
            if (strcmp(emotion, name) == 0) {
                ShowAnimation(name);
                return;
            }
        }
        switch (Application::GetInstance().GetDeviceState()) {
            case kDeviceStateListening:
                ShowAnimation("listening");
                break;
            case kDeviceStateSpeaking:
            case kDeviceStateNotifying:
                ShowAnimation("speaking");
                break;
            case kDeviceStateConnecting:
                ShowAnimation("thinking");
                break;
            default:
                ShowAnimation("neutral");
        }
    }

    // Called on the application task by the board's MCP tool.
    void PlayPerformance(const std::string& action) {
        DisplayLockGuard lock(this);
        ShowAnimation(action.c_str());
        if (performance_timer_) {
            lv_timer_delete(performance_timer_);
        }
        performance_timer_ = lv_timer_create(
            [](lv_timer_t* timer) {
                auto self = static_cast<IkunRoundDisplay*>(lv_timer_get_user_data(timer));
                self->performance_timer_ = nullptr;
                self->SetEmotion("neutral");
            },
            12000, this);
        lv_timer_set_repeat_count(performance_timer_, 1);
    }

    void SetChatMessage(const char* role, const char* content) override {
        SpiLcdDisplay::SetChatMessage(role, content);
        if (!setup_ui_called_) {
            return;
        }
        DisplayLockGuard lock(this);
        const bool has_text = content && content[0];
        const int text_height = has_text ? 160 : 90;
        lv_obj_set_size(emoji_box_, has_text ? 140 : 216, has_text ? 150 : 234);
        lv_image_set_scale(emoji_image_, has_text ? 154 : 256);
        lv_obj_set_height(bottom_bar_, text_height);
        lv_obj_align(bottom_bar_, LV_ALIGN_TOP_MID, 0, has_text ? 252 : 320);
        lv_obj_align(chat_message_label_, LV_ALIGN_TOP_MID, 0, 0);
        lv_obj_update_layout(chat_message_label_);
        const int overflow = lv_obj_get_height(chat_message_label_) - text_height;
        if (overflow > 0) {
            lv_anim_t scroll;
            lv_anim_init(&scroll);
            lv_anim_set_var(&scroll, chat_message_label_);
            lv_anim_set_values(&scroll, 0, -overflow);
            lv_anim_set_duration(&scroll, overflow * 55);
            lv_anim_set_delay(&scroll, 2500);
            lv_anim_set_playback_duration(&scroll, 300);
            lv_anim_set_playback_delay(&scroll, 3000);
            lv_anim_set_repeat_delay(&scroll, 2500);
            lv_anim_set_repeat_count(&scroll, LV_ANIM_REPEAT_INFINITE);
            lv_anim_set_exec_cb(&scroll, [](void* label, int32_t y) {
                lv_obj_set_y(static_cast<lv_obj_t*>(label), y);
            });
            lv_anim_start(&scroll);
        }
        if (!performance_timer_ && content && content[0] && strcmp(role, "user") == 0) {
            ShowAnimation("thinking");
        }
    }

    void ClearChatMessages() override {
        SpiLcdDisplay::ClearChatMessages();
        SetChatMessage("system", "");
    }

private:
    const uint8_t* current_animation_ = nullptr;
    lv_timer_t* performance_timer_ = nullptr;

    void ShowAnimation(const char* name) {
        void* data = nullptr;
        size_t size = 0;
        if (!Assets::GetInstance().GetAssetData(std::string("ikun_") + name + ".gif", data, size)) {
            ESP_LOGW("IkunUI", "Missing animation: %s", name);
            data = const_cast<uint8_t*>(ikun::idle.data);
            size = ikun::idle.size;
        }
        if (current_animation_ == data) {
            return;
        }
        LvglRawImage image(data, size);
        auto next = std::make_unique<LvglGif>(image.image_dsc());
        if (!next->IsLoaded()) {
            ESP_LOGE("IkunUI", "Could not load animation: %s", name);
            return;
        }
        if (gif_controller_) {
            gif_controller_->Stop();
        }
        gif_controller_ = std::move(next);
        current_animation_ = static_cast<const uint8_t*>(data);
        gif_controller_->SetFrameCallback(
            [this]() { lv_image_set_src(emoji_image_, gif_controller_->image_dsc()); });
        lv_image_set_src(emoji_image_, gif_controller_->image_dsc());
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);
        gif_controller_->Start();
        ESP_LOGI("IkunUI", "Animation: %s", name);
    }
};
