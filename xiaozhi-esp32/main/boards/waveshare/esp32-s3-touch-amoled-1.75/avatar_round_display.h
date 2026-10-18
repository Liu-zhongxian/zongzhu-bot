#pragma once
// SPDX-License-Identifier: AGPL-3.0-or-later
// KK-style adaptation; see kk-avatar-NOTICE.md.

#include <esp_random.h>
#include <algorithm>
#include <atomic>
#include <functional>
#include "application.h"
#include "display/lcd_display.h"
#include "kk_avatar.h"

#include <cstring>

// The 466px circular glass clips the corners of the square LVGL framebuffer.
class AvatarRoundDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;

    ~AvatarRoundDisplay() override {
        DisplayLockGuard lock(this);
        if (frame_timer_)
            lv_timer_delete(frame_timer_);
        if (performance_timer_)
            lv_timer_delete(performance_timer_);
    }

    void SetupUI() override {
        if (setup_ui_called_)
            return;
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

        lv_obj_set_size(emoji_box_, 466, 280);
        lv_obj_align(emoji_box_, LV_ALIGN_TOP_MID, 0, 100);
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
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_CLICKABLE);
        for (auto& eye : eyes_) {
            eye.body = Shape(emoji_box_, lv_color_white());
            lv_obj_set_style_clip_corner(eye.body, true, 0);
            eye.lid = Shape(eye.body, lv_color_black());
            eye.brow = Shape(emoji_box_, lv_color_hex(0xbbbbbb));
            for (size_t i = 0; i < eye.rings.size(); ++i) {
                eye.rings[i] = Shape(eye.body, i % 2 ? lv_color_white() : lv_color_black());
                lv_obj_add_flag(eye.rings[i], LV_OBJ_FLAG_HIDDEN);
            }
        }
        ApplyMonochrome();
        ShowAnimation("neutral");
        Render();
        frame_timer_ = lv_timer_create(
            [](lv_timer_t* timer) {
                static_cast<AvatarRoundDisplay*>(lv_timer_get_user_data(timer))->Render();
            },
            33, this);
        ESP_LOGI("AvatarUI", "KK eyes ready: 466x466, procedural LVGL, 33ms timer");
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
        ShowAnimation(emotion);
    }

    void SetTheme(Theme* theme) override {
        SpiLcdDisplay::SetTheme(theme);
        if (setup_ui_called_) {
            DisplayLockGuard lock(this);
            ApplyMonochrome();
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
                auto self = static_cast<AvatarRoundDisplay*>(lv_timer_get_user_data(timer));
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
        compact_ = has_text;
        lv_obj_set_size(emoji_box_, 466, has_text ? 140 : 280);
        lv_obj_align(emoji_box_, LV_ALIGN_TOP_MID, 0, has_text ? 108 : 100);
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
        Render();
        if (!performance_timer_ && content && content[0] && role && strcmp(role, "user") == 0) {
            ShowAnimation("thinking");
        }
    }

    void ClearChatMessages() override {
        SpiLcdDisplay::ClearChatMessages();
        SetChatMessage("system", "");
    }

    // Motion inputs come from the IMU task; Render() reads them on the LVGL task.
    void SetTilt(float x, float y) {
        tilt_x_.store(x, std::memory_order_relaxed);
        tilt_y_.store(y, std::memory_order_relaxed);
    }
    void SetDizzy(bool active) { dizzy_.store(active, std::memory_order_relaxed); }
    void OnTouch(std::function<void()> callback) { on_touch_ = std::move(callback); }

private:
    struct EyeWidgets {
        lv_obj_t* body = nullptr;
        lv_obj_t* lid = nullptr;
        lv_obj_t* brow = nullptr;
        std::array<lv_obj_t*, 4> rings{};
    };
    std::array<EyeWidgets, 2> eyes_{};
    kk::Pose pose_ = kk::PoseAt(kk::Emotion::Idle, 0);
    kk::Emotion emotion_ = kk::Emotion::Idle;
    lv_timer_t* frame_timer_ = nullptr;
    lv_timer_t* performance_timer_ = nullptr;
    bool compact_ = false;
    uint32_t last_blink_ = 0;
    uint32_t blink_interval_ = 3500;

    // Short touch/IMU reactions sit on top of the device-state emotion and then expire.
    kk::Emotion reaction_ = kk::Emotion::Idle;
    uint32_t reaction_until_ = 0;
    std::atomic<float> tilt_x_{0}, tilt_y_{0};
    std::atomic<bool> dizzy_{false};
    float gaze_x_ = 0, gaze_y_ = 0;
    std::function<void()> on_touch_;

    // Gesture thresholds follow the upstream StopWatch firmware.
    static constexpr int kGestureDirectionLockPx = 12;
    static constexpr int kGestureCommitPx = 52;
    static constexpr uint32_t kDragHoldMs = 250;
    static constexpr uint32_t kLongPressMs = 700;
    static constexpr uint32_t kDoubleTapMs = 300;
    static constexpr uint32_t kReactionMs = 1800;
    enum class Gesture { None, Horizontal, Vertical, Follow };
    lv_indev_t* touch_ = nullptr;
    bool pressed_ = false;
    bool committed_ = false;
    Gesture gesture_ = Gesture::None;
    lv_point_t press_point_{}, touch_point_{};
    uint32_t press_time_ = 0;
    uint32_t pending_tap_ = 0;
    size_t swipe_index_ = 0;

    void React(kk::Emotion emotion, uint32_t now, uint32_t duration = kReactionMs) {
        reaction_ = emotion;
        reaction_until_ = now + duration;
        ESP_LOGI("AvatarUI", "Reaction: %d", static_cast<int>(emotion));
    }

    void PollTouch(uint32_t now) {
        if (!touch_) {
            for (auto indev = lv_indev_get_next(nullptr); indev; indev = lv_indev_get_next(indev)) {
                if (lv_indev_get_type(indev) == LV_INDEV_TYPE_POINTER) {
                    touch_ = indev;
                    break;
                }
            }
            if (!touch_)
                return;
        }
        if (pending_tap_ && now - pending_tap_ > kDoubleTapMs) {
            pending_tap_ = 0;
            React(kk::Emotion::Happy, now);
        }
        const bool down = lv_indev_get_state(touch_) == LV_INDEV_STATE_PRESSED;
        if (down)
            lv_indev_get_point(touch_, &touch_point_);
        if (down && !pressed_) {
            pressed_ = true;
            committed_ = false;
            gesture_ = Gesture::None;
            press_point_ = touch_point_;
            press_time_ = now;
            if (on_touch_)
                on_touch_();
            return;
        }
        if (!down) {
            if (pressed_ && !committed_ && gesture_ == Gesture::None && now - press_time_ < kLongPressMs) {
                if (pending_tap_) {
                    pending_tap_ = 0;
                    React(kk::Emotion::Surprised, now);
                } else {
                    pending_tap_ = std::max<uint32_t>(now, 1);
                }
            }
            pressed_ = false;
            gesture_ = Gesture::None;
            return;
        }
        const int dx = touch_point_.x - press_point_.x;
        const int dy = touch_point_.y - press_point_.y;
        if (gesture_ == Gesture::None && std::max(std::abs(dx), std::abs(dy)) >= kGestureDirectionLockPx) {
            if (now - press_time_ >= kDragHoldMs)
                gesture_ = Gesture::Follow;
            else
                gesture_ = std::abs(dx) >= std::abs(dy) ? Gesture::Horizontal : Gesture::Vertical;
        }
        if (committed_)
            return;
        if (gesture_ == Gesture::Horizontal && std::abs(dx) >= kGestureCommitPx) {
            static constexpr kk::Emotion kCycle[] = {
                kk::Emotion::Happy, kk::Emotion::Excited, kk::Emotion::Curious,
                kk::Emotion::Confused, kk::Emotion::Angry, kk::Emotion::Surprised,
                kk::Emotion::Sad, kk::Emotion::Sleepy, kk::Emotion::Dizzy};
            constexpr size_t n = sizeof(kCycle) / sizeof(kCycle[0]);
            swipe_index_ = (swipe_index_ + (dx > 0 ? 1 : n - 1)) % n;
            React(kCycle[swipe_index_], now, 3000);
            committed_ = true;
        } else if (gesture_ == Gesture::Vertical && std::abs(dy) >= kGestureCommitPx) {
            React(dy < 0 ? kk::Emotion::Surprised : kk::Emotion::Sleepy, now, 3000);
            committed_ = true;
        } else if (gesture_ == Gesture::None && now - press_time_ >= kLongPressMs) {
            React(kk::Emotion::Angry, now);
            committed_ = true;
            gesture_ = Gesture::Follow;
        }
    }

    kk::Emotion CurrentEmotion(uint32_t now) const {
        if (dizzy_.load(std::memory_order_relaxed))
            return kk::Emotion::Dizzy;
        if (static_cast<int32_t>(reaction_until_ - now) > 0)
            return reaction_;
        return emotion_;
    }

    static lv_obj_t* Shape(lv_obj_t* parent, lv_color_t color) {
        auto obj = lv_obj_create(parent);
        lv_obj_remove_style_all(obj);
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_style_bg_color(obj, color, 0);
        lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(obj, LV_RADIUS_CIRCLE, 0);
        return obj;
    }

    void ApplyMonochrome() {
        for (auto obj : {lv_screen_active(), container_, bottom_bar_}) {
            lv_obj_set_style_bg_color(obj, lv_color_black(), 0);
            lv_obj_set_style_bg_image_src(obj, nullptr, 0);
        }
        lv_obj_set_style_bg_opa(top_bar_, LV_OPA_TRANSP, 0);
        for (auto label :
             {status_label_, notification_label_, network_label_, mute_label_, battery_label_}) {
            lv_obj_set_style_text_color(label, lv_color_hex(0xbdbdbd), 0);
        }
        lv_obj_set_style_text_color(chat_message_label_, lv_color_white(), 0);
    }

    void ShowAnimation(const char* name) {
        if (!name)
            name = "neutral";
        kk::Emotion next = kk::Emotion::Idle;
        if (!strcmp(name, "thinking"))
            next = kk::Emotion::Thinking;
        else if (!strcmp(name, "listening"))
            next = kk::Emotion::Listening;
        else if (!strcmp(name, "speaking"))
            next = kk::Emotion::Speaking;
        else if (!strcmp(name, "happy") || !strcmp(name, "laughing") || !strcmp(name, "loving") ||
                 !strcmp(name, "singing"))
            next = kk::Emotion::Happy;
        else if (!strcmp(name, "excited") || !strcmp(name, "dancing") || !strcmp(name, "rapper") ||
                 !strcmp(name, "basketball"))
            next = kk::Emotion::Excited;
        else if (!strcmp(name, "curious") || !strcmp(name, "confident"))
            next = kk::Emotion::Curious;
        else if (!strcmp(name, "confused") || !strcmp(name, "embarrassed"))
            next = kk::Emotion::Confused;
        else if (!strcmp(name, "angry"))
            next = kk::Emotion::Angry;
        else if (!strcmp(name, "surprised") || !strcmp(name, "shocked"))
            next = kk::Emotion::Surprised;
        else if (!strcmp(name, "sad") || !strcmp(name, "crying"))
            next = kk::Emotion::Sad;
        else if (!strcmp(name, "sleepy") || !strcmp(name, "relaxed"))
            next = kk::Emotion::Sleepy;
        else if (!strcmp(name, "dizzy") || !strcmp(name, "silly") || !strcmp(name, "funny"))
            next = kk::Emotion::Dizzy;
        else {
            switch (Application::GetInstance().GetDeviceState()) {
                case kDeviceStateListening:
                    next = kk::Emotion::Listening;
                    break;
                case kDeviceStateSpeaking:
                case kDeviceStateNotifying:
                    next = kk::Emotion::Speaking;
                    break;
                case kDeviceStateConnecting:
                    next = kk::Emotion::Thinking;
                    break;
                default:
                    break;
            }
        }
        if (next != emotion_) {
            emotion_ = next;
            ESP_LOGI("AvatarUI", "Expression: %s", name);
        }
    }

    void Render() {
        if (!eyes_[0].body)
            return;
        const uint32_t now = lv_tick_get();
        PollTouch(now);
        const kk::Emotion emotion = CurrentEmotion(now);
        uint32_t age = now - last_blink_;
        if (age > blink_interval_ + 280) {
            last_blink_ = now;
            blink_interval_ = 3400 + esp_random() % 2800;
            age = 0;
        }
        float blink = 1.0f;
        if (age > blink_interval_ && emotion != kk::Emotion::Surprised &&
            emotion != kk::Emotion::Dizzy) {
            const float phase = (age - blink_interval_) / 280.0f;
            blink = std::max(0.05f, std::abs(2.0f * phase - 1.0f));
        }
        auto target = kk::PoseAt(emotion, now);
        const float scale = compact_ ? 0.28f : 0.466f;
        const int center_y = compact_ ? 70 : 140;
        // Gaze: a held finger wins over device tilt; both are in -1..1.
        float gx = tilt_x_.load(std::memory_order_relaxed);
        float gy = tilt_y_.load(std::memory_order_relaxed);
        if (pressed_ && gesture_ == Gesture::Follow) {
            const int eye_center_y = (compact_ ? 108 : 100) + center_y;
            gx = std::clamp((touch_point_.x - 233) / 160.0f, -1.0f, 1.0f);
            gy = std::clamp((touch_point_.y - eye_center_y) / 160.0f, -1.0f, 1.0f);
        }
        gaze_x_ += (gx - gaze_x_) * 0.25f;
        gaze_y_ += (gy - gaze_y_) * 0.25f;
        for (auto& eye : target) {
            eye.x += gaze_x_ * 80;
            eye.y += gaze_y_ * 60;
        }
        for (size_t i = 0; i < eyes_.size(); ++i) {
            pose_[i] = kk::Blend(pose_[i], target[i], 0.16f);
            const auto& p = pose_[i];
            auto& eye = eyes_[i];
            const int w = std::max(4, static_cast<int>(p.width * scale));
            const int h = std::max(4, static_cast<int>(p.height * scale * blink));
            const int x = 233 + static_cast<int>(p.x * scale) - w / 2;
            const int y = center_y + static_cast<int>(p.y * scale) - h / 2;
            lv_obj_set_size(eye.body, w, h);
            lv_obj_set_pos(eye.body, x, y);
            lv_obj_set_style_transform_pivot_x(eye.body, w / 2, 0);
            lv_obj_set_style_transform_pivot_y(eye.body, h / 2, 0);
            lv_obj_set_style_transform_rotation(eye.body, static_cast<int>(p.angle * 10), 0);
            const int lid = static_cast<int>(h * p.lid);
            lv_obj_set_size(eye.lid, w, std::max(1, lid));
            lv_obj_set_style_radius(eye.lid, 0, 0);
            lv_obj_set_pos(eye.lid, 0, 0);
            lv_obj_set_style_bg_opa(eye.lid, lid > 0 ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
            lv_obj_set_size(eye.brow, w, 3);
            lv_obj_set_pos(eye.brow, x, y - 12);
            lv_obj_set_style_transform_pivot_x(eye.brow, w / 2, 0);
            lv_obj_set_style_transform_rotation(eye.brow, static_cast<int>(p.angle * 10), 0);
            lv_obj_set_style_bg_opa(eye.brow, static_cast<lv_opa_t>(p.brow * 255), 0);
            for (size_t r = 0; r < eye.rings.size(); ++r) {
                auto ring = eye.rings[r];
                if (emotion == kk::Emotion::Dizzy) {
                    lv_obj_remove_flag(ring, LV_OBJ_FLAG_HIDDEN);
                    const int diameter =
                        std::max(2, static_cast<int>(std::min(w, h) * (0.78f - r * 0.17f)));
                    lv_obj_set_size(ring, diameter, diameter);
                    const float phase = now / 180.0f + i * 3.14f + r;
                    lv_obj_set_pos(ring, (w - diameter) / 2 + static_cast<int>(3 * std::sin(phase)),
                                   (h - diameter) / 2 + static_cast<int>(3 * std::cos(phase)));
                } else
                    lv_obj_add_flag(ring, LV_OBJ_FLAG_HIDDEN);
            }
        }
    }
};
