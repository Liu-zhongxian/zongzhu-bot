#pragma once
// Zongzhu UI: procedural eyes, touch reactions and subtitle modes. Screen size and
// layout come from EyeScreen; the defaults are the 466x466 round AMOLED (1.75C).
// Shapes come from eye_model.h.

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_random.h>
#include <esp_timer.h>

#include <algorithm>
#include <atomic>
#include <cstring>
#include <cmath>
#include <functional>
#include <string>

#include "application.h"
#include "display/lcd_display.h"
#include "eye_model.h"
#include "settings.h"

enum class SubtitleMode : int32_t { Full = 0, Brief = 1, Off = 2 };

// Screen geometry for the eye UI. Eye layouts: Large (no text), Medium (brief
// subtitle) and Small (full text); y values are from the top of the screen.
struct EyeScreen {
    struct Layout {
        int box_y, box_h, center_y;  // eye area, and eye centre within it
        float scale;                 // eye size relative to eye_model.h
    };
    int width = 466;
    // Status bars; the round glass needs them inset from the edge.
    int status_bar_w = 288, status_bar_h = 48, status_bar_y = 64;
    int top_bar_w = 176, top_bar_h = 36, top_bar_y = 28;
    int status_w = 280, text_w = 284, popup_w = 300;
    Layout large{100, 280, 140, 1.0f};
    Layout medium{100, 230, 115, 0.82f};
    Layout small{108, 140, 70, 0.6f};
    int text_y = 330, text_h = 80;               // Large/Medium subtitle area
    int text_y_small = 252, text_h_small = 160;  // full-text area
    float follow_px = 150;                       // finger offset for full gaze
};

class EyeDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;

    // Must be called before SetupUI().
    void SetScreen(const EyeScreen& screen) { screen_ = screen; }

    ~EyeDisplay() override {
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
        {
            Settings settings("display");
            subtitle_mode_ = static_cast<SubtitleMode>(
                std::clamp<int32_t>(settings.GetInt("subtitle", 0), 0, 2));
        }
        DisplayLockGuard lock(this);
        // On the round glass the bars are inset so the corners don't clip text.
        for (auto bar : {top_bar_, status_bar_}) {
            lv_obj_set_size(bar, screen_.status_bar_w, screen_.status_bar_h);
            lv_obj_set_style_pad_all(bar, 0, 0);
            lv_obj_align(bar, LV_ALIGN_TOP_MID, 0, screen_.status_bar_y);
        }
        lv_obj_set_size(top_bar_, screen_.top_bar_w, screen_.top_bar_h);
        lv_obj_align(top_bar_, LV_ALIGN_TOP_MID, 0, screen_.top_bar_y);
        lv_obj_set_width(status_label_, screen_.status_w);
        lv_label_set_long_mode(status_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);
        lv_obj_set_width(notification_label_, screen_.status_w);
        lv_label_set_long_mode(notification_label_, LV_LABEL_LONG_SCROLL_CIRCULAR);
        lv_obj_set_style_bg_opa(top_bar_, LV_OPA_TRANSP, 0);

        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_width(bottom_bar_, screen_.text_w);
        lv_obj_set_style_pad_all(bottom_bar_, 0, 0);
        lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_TRANSP, 0);
        lv_obj_remove_flag(bottom_bar_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_width(chat_message_label_, screen_.text_w);
        lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_line_space(chat_message_label_, 4, 0);
        lv_obj_set_style_text_align(chat_message_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_width(low_battery_popup_, screen_.popup_w);
        lv_obj_center(low_battery_popup_);
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);

        // One plain object draws both eyes with solid fills: no transforms, opacity
        // layers or corner clipping, and only the eyes' old+new bounds are redrawn.
        canvas_ = lv_obj_create(emoji_box_);
        lv_obj_remove_style_all(canvas_);
        lv_obj_set_size(canvas_, LV_PCT(100), LV_PCT(100));
        lv_obj_remove_flag(canvas_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_remove_flag(canvas_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_event_cb(
            canvas_,
            [](lv_event_t* e) {
                static_cast<EyeDisplay*>(lv_event_get_user_data(e))->Draw(lv_event_get_layer(e));
            },
            LV_EVENT_DRAW_MAIN, this);
        lv_display_add_event_cb(
            display_,
            [](lv_event_t* e) { ++static_cast<EyeDisplay*>(lv_event_get_user_data(e))->refreshes_; },
            LV_EVENT_REFR_READY, this);
        ApplyMonochrome();
        ApplyLayout(Layout::Large);
        last_tick_ = lv_tick_get();
        if (auto refr = lv_display_get_refr_timer(display_))
            lv_timer_set_period(refr, kFrameMs);
        frame_timer_ = lv_timer_create(
            [](lv_timer_t* timer) {
                static_cast<EyeDisplay*>(lv_timer_get_user_data(timer))->Render();
            },
            kFrameMs, this);
        ESP_LOGI(kTag, "Eyes ready, subtitle mode %d", static_cast<int>(subtitle_mode_));
    }

    void SetStatus(const char* status) override {
        const std::string title = std::string("宗主 · ") + status;
        SpiLcdDisplay::SetStatus(title.c_str());
        SetEmotion(strncmp(status, "等待 Bot", strlen("等待 Bot")) == 0 ? "thinking" : "neutral");
    }

    void SetEmotion(const char* emotion) override {
        if (!setup_ui_called_)
            return;
        DisplayLockGuard lock(this);
        if (!performance_timer_)
            mood_ = MoodFor(emotion);
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
        mood_ = MoodFor(action.c_str());
        if (performance_timer_)
            lv_timer_delete(performance_timer_);
        performance_timer_ = lv_timer_create(
            [](lv_timer_t* timer) {
                auto self = static_cast<EyeDisplay*>(lv_timer_get_user_data(timer));
                self->performance_timer_ = nullptr;
                self->SetEmotion("neutral");
            },
            12000, this);
        lv_timer_set_repeat_count(performance_timer_, 1);
    }

    void SetChatMessage(const char* role, const char* content) override {
        last_role_ = role ? role : "";
        last_text_ = content ? content : "";
        if (!setup_ui_called_) {
            SpiLcdDisplay::SetChatMessage(role, content);
            return;
        }
        DisplayLockGuard lock(this);
        ShowChat();
        if (!performance_timer_ && !last_text_.empty() && last_role_ == "user")
            mood_ = eyes::Mood::Thinking;
    }

    void ClearChatMessages() override {
        SpiLcdDisplay::ClearChatMessages();
        SetChatMessage("system", "");
    }

    // Cycles full -> brief -> off and persists the choice. Returns the new label.
    const char* CycleSubtitleMode() {
        {
            DisplayLockGuard lock(this);
            subtitle_mode_ = static_cast<SubtitleMode>((static_cast<int>(subtitle_mode_) + 1) % 3);
            ShowChat();
        }
        Settings settings("display", true);
        settings.SetInt("subtitle", static_cast<int32_t>(subtitle_mode_));
        ESP_LOGI(kTag, "Subtitle mode -> %d", static_cast<int>(subtitle_mode_));
        return SubtitleLabel();
    }

    const char* SubtitleLabel() const {
        switch (subtitle_mode_) {
            case SubtitleMode::Brief:
                return "字幕：简洁";
            case SubtitleMode::Off:
                return "字幕：关闭";
            default:
                return "字幕：完整";
        }
    }

    // Motion inputs arrive from the IMU task; Render() consumes them on the LVGL task.
    void SetTilt(float x, float y) {
        tilt_x_.store(x, std::memory_order_relaxed);
        tilt_y_.store(y, std::memory_order_relaxed);
    }
    void SetDizzy(bool active) { dizzy_.store(active, std::memory_order_relaxed); }
    void OnTouch(std::function<void()> callback) { on_touch_ = std::move(callback); }

private:
    static constexpr const char* kTag = "EyeUI";

    enum class Layout { Large, Medium, Small };
    EyeScreen screen_;
    const EyeScreen::Layout& Spec(Layout layout) const {
        switch (layout) {
            case Layout::Medium:
                return screen_.medium;
            case Layout::Small:
                return screen_.small;
            default:
                return screen_.large;
        }
    }
    int CenterX() const { return screen_.width / 2; }

    static constexpr uint32_t kFrameMs = 20;

    // Integer geometry of one eye in canvas coordinates; compared frame to frame
    // so unchanged frames cost nothing.
    struct EyeGeom {
        int32_t cx = 0, cy = 0, w = 0, h = 0, tilt10 = 0, body_opa = 0;
        int32_t lid_on = 0, lid_l = 0, lid_r = 0;
        int32_t swirl_opa = 0, swirl_d = 0, swirl_rot = 0;
        int32_t cap_opa = 0, cap_d = 0, cap_w = 0, cap_cy = 0, cap_up = 0, cap_rot = 0;
        lv_area_t box{0, 0, -1, -1};
        bool operator==(const EyeGeom& o) const { return memcmp(this, &o, sizeof(*this)) == 0; }
    };
    lv_obj_t* canvas_ = nullptr;
    EyeGeom geom_[2];

    // Performance counters, logged every 30 s.
    uint32_t refreshes_ = 0, renders_ = 0, max_gap_ms_ = 0, last_stat_ = 0;
    int64_t draw_us_ = 0, max_draw_us_ = 0;
    uint32_t draws_ = 0;
    eyes::Face face_ = eyes::FaceFor(eyes::Mood::Idle, 0);
    eyes::Mood mood_ = eyes::Mood::Idle;
    Layout layout_ = Layout::Large;
    lv_timer_t* frame_timer_ = nullptr;
    lv_timer_t* performance_timer_ = nullptr;
    uint32_t last_tick_ = 0;

    SubtitleMode subtitle_mode_ = SubtitleMode::Full;
    std::string last_role_, last_text_;

    // Blink: quick close, short hold, slower open; sometimes twice in a row.
    uint32_t next_blink_ = 2500;
    uint32_t blink_start_ = 0;
    bool blinking_ = false;
    bool double_blink_ = false;

    // Small idle glances, combined with tilt and touch gaze.
    uint32_t next_glance_ = 1500;
    float glance_x_ = 0, glance_y_ = 0;
    float gaze_x_ = 0, gaze_y_ = 0;
    std::atomic<float> tilt_x_{0}, tilt_y_{0};
    std::atomic<bool> dizzy_{false};

    // Touch reactions sit on top of the device mood, then expire.
    eyes::Mood reaction_ = eyes::Mood::Idle;
    uint32_t reaction_until_ = 0;
    std::function<void()> on_touch_;
    enum class Gesture { None, Horizontal, Vertical, Follow };
    lv_indev_t* touch_ = nullptr;
    bool pressed_ = false;
    bool committed_ = false;
    Gesture gesture_ = Gesture::None;
    lv_point_t press_point_{}, touch_point_{};
    uint32_t press_time_ = 0;
    uint32_t pending_tap_ = 0;
    size_t browse_index_ = 0;

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

    void ApplyLayout(Layout layout) {
        layout_ = layout;
        const auto& spec = Spec(layout);
        lv_obj_set_size(emoji_box_, screen_.width, spec.box_h);
        lv_obj_align(emoji_box_, LV_ALIGN_TOP_MID, 0, spec.box_y);
        const bool small = layout == Layout::Small;
        lv_obj_set_height(bottom_bar_, small ? screen_.text_h_small : screen_.text_h);
        lv_obj_align(bottom_bar_, LV_ALIGN_TOP_MID, 0, small ? screen_.text_y_small : screen_.text_y);
    }

    // First sentence only, at most two short lines.
    static std::string Brief(const std::string& text) {
        static constexpr size_t kMaxChars = 18;
        static const char* kStops[] = {"。", "！", "？", "!", "?", "\n"};
        size_t end = text.size();
        for (auto stop : kStops) {
            auto pos = text.find(stop);
            if (pos != std::string::npos && pos > 0)
                end = std::min(end, pos + (stop[0] == '\n' ? 0 : strlen(stop)));
        }
        std::string out;
        size_t chars = 0, i = 0;
        while (i < end && chars < kMaxChars) {
            size_t len = 1;
            const auto c = static_cast<unsigned char>(text[i]);
            if (c >= 0xF0)
                len = 4;
            else if (c >= 0xE0)
                len = 3;
            else if (c >= 0xC0)
                len = 2;
            out.append(text, i, len);
            i += len;
            ++chars;
        }
        if (i < text.size() && !out.empty())
            out += "...";
        return out;
    }

    // Applies the subtitle mode to the latest message and re-lays out the screen.
    void ShowChat() {
        std::string shown = last_text_;
        const bool system = last_role_ == "system";
        if (!system && subtitle_mode_ == SubtitleMode::Off)
            shown.clear();
        else if (!system && subtitle_mode_ == SubtitleMode::Brief)
            shown = last_role_ == "user" ? std::string() : Brief(last_text_);
        SpiLcdDisplay::SetChatMessage(last_role_.c_str(), shown.c_str());

        const bool has_text = !shown.empty();
        const bool full = system || subtitle_mode_ == SubtitleMode::Full;
        ApplyLayout(!has_text ? Layout::Large : full ? Layout::Small : Layout::Medium);

        lv_anim_delete(chat_message_label_, nullptr);
        lv_obj_align(chat_message_label_, LV_ALIGN_TOP_MID, 0, 0);
        lv_obj_update_layout(chat_message_label_);
        const int overflow = lv_obj_get_height(chat_message_label_) - lv_obj_get_height(bottom_bar_);
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
    }

    static eyes::Mood MoodFor(const char* name) {
        using eyes::Mood;
        struct Alias {
            const char* name;
            Mood mood;
        };
        static constexpr Alias kAliases[] = {
            {"thinking", Mood::Thinking},   {"listening", Mood::Listening},
            {"speaking", Mood::Speaking},   {"happy", Mood::Happy},
            {"laughing", Mood::Happy},      {"loving", Mood::Happy},
            {"singing", Mood::Happy},       {"winking", Mood::Happy},
            {"excited", Mood::Excited},     {"dancing", Mood::Excited},
            {"rapper", Mood::Excited},      {"basketball", Mood::Excited},
            {"cool", Mood::Excited},        {"curious", Mood::Curious},
            {"confident", Mood::Curious},   {"confused", Mood::Confused},
            {"embarrassed", Mood::Confused}, {"angry", Mood::Angry},
            {"surprised", Mood::Surprised}, {"shocked", Mood::Surprised},
            {"sad", Mood::Sad},             {"crying", Mood::Sad},
            {"sleepy", Mood::Sleepy},       {"relaxed", Mood::Sleepy},
            {"dizzy", Mood::Dizzy},         {"silly", Mood::Dizzy},
            {"funny", Mood::Dizzy},
        };
        if (name) {
            for (const auto& alias : kAliases) {
                if (!strcmp(name, alias.name))
                    return alias.mood;
            }
        }
        switch (Application::GetInstance().GetDeviceState()) {
            case kDeviceStateListening:
                return Mood::Listening;
            case kDeviceStateSpeaking:
            case kDeviceStateNotifying:
                return Mood::Speaking;
            case kDeviceStateConnecting:
                return Mood::Thinking;
            default:
                return Mood::Idle;
        }
    }

    void React(eyes::Mood mood, uint32_t now, uint32_t duration_ms = 2000) {
        reaction_ = mood;
        reaction_until_ = now + duration_ms;
        ESP_LOGI(kTag, "Reaction %d", static_cast<int>(mood));
    }

    eyes::Mood CurrentMood(uint32_t now) const {
        if (dizzy_.load(std::memory_order_relaxed))
            return eyes::Mood::Dizzy;
        if (static_cast<int32_t>(reaction_until_ - now) > 0)
            return reaction_;
        return mood_;
    }

    void PollTouch(uint32_t now) {
        static constexpr int kLockPx = 14;
        static constexpr int kSwipePx = 60;
        static constexpr uint32_t kFollowAfterMs = 220;
        static constexpr uint32_t kLongPressMs = 650;
        static constexpr uint32_t kDoubleTapMs = 280;

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
            React(eyes::Mood::Happy, now);
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
            if (pressed_ && !committed_ && gesture_ == Gesture::None) {
                if (pending_tap_) {
                    pending_tap_ = 0;
                    React(eyes::Mood::Surprised, now);
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
        if (gesture_ == Gesture::None && std::max(std::abs(dx), std::abs(dy)) >= kLockPx) {
            if (now - press_time_ >= kFollowAfterMs)
                gesture_ = Gesture::Follow;
            else
                gesture_ = std::abs(dx) >= std::abs(dy) ? Gesture::Horizontal : Gesture::Vertical;
        }
        if (committed_)
            return;
        if (gesture_ == Gesture::Horizontal && std::abs(dx) >= kSwipePx) {
            using eyes::Mood;
            static constexpr Mood kBrowse[] = {Mood::Happy,    Mood::Excited, Mood::Curious,
                                               Mood::Confused, Mood::Angry,   Mood::Surprised,
                                               Mood::Sad,      Mood::Sleepy,  Mood::Dizzy};
            constexpr size_t n = sizeof(kBrowse) / sizeof(kBrowse[0]);
            browse_index_ = (browse_index_ + (dx > 0 ? 1 : n - 1)) % n;
            React(kBrowse[browse_index_], now, 3000);
            committed_ = true;
        } else if (gesture_ == Gesture::Vertical && std::abs(dy) >= kSwipePx) {
            React(dy < 0 ? eyes::Mood::Surprised : eyes::Mood::Sleepy, now, 3000);
            committed_ = true;
        } else if (gesture_ == Gesture::None && now - press_time_ >= kLongPressMs) {
            React(eyes::Mood::Angry, now);
            committed_ = true;
            gesture_ = Gesture::Follow;
        }
    }

    float BlinkFactor(uint32_t now, eyes::Mood mood) {
        using eyes::Mood;
        static constexpr uint32_t kClose = 70, kHold = 30, kOpen = 140;
        const bool allowed = mood != Mood::Happy && mood != Mood::Sleepy && mood != Mood::Dizzy &&
                             mood != Mood::Surprised;
        if (!blinking_) {
            if (static_cast<int32_t>(now - next_blink_) < 0 || !allowed)
                return 1.0f;
            blinking_ = true;
            blink_start_ = now;
        }
        const uint32_t age = now - blink_start_;
        float k;
        if (age < kClose)
            k = 1.0f - static_cast<float>(age) / kClose;
        else if (age < kClose + kHold)
            k = 0;
        else if (age < kClose + kHold + kOpen)
            k = static_cast<float>(age - kClose - kHold) / kOpen;
        else {
            blinking_ = false;
            if (!double_blink_ && esp_random() % 5 == 0) {
                double_blink_ = true;
                next_blink_ = now + 90;
            } else {
                double_blink_ = false;
                next_blink_ = now + 2600 + esp_random() % 3400;
            }
            return 1.0f;
        }
        return std::max(0.06f, k);
    }

    void UpdateGaze(uint32_t now, float dt, eyes::Mood mood, float center_y) {
        using eyes::Mood;
        const bool glancing = mood == Mood::Idle || mood == Mood::Listening || mood == Mood::Speaking;
        if (static_cast<int32_t>(now - next_glance_) >= 0) {
            next_glance_ = now + 1200 + esp_random() % 2300;
            const bool home = !glancing || esp_random() % 3 == 0;
            glance_x_ = home ? 0 : ((esp_random() % 1000) / 1000.0f - 0.5f) * 0.7f;
            glance_y_ = home ? 0 : ((esp_random() % 1000) / 1000.0f - 0.5f) * 0.4f;
        }
        float gx = tilt_x_.load(std::memory_order_relaxed) + glance_x_;
        float gy = tilt_y_.load(std::memory_order_relaxed) + glance_y_;
        if (pressed_ && gesture_ == Gesture::Follow) {
            gx = (touch_point_.x - CenterX()) / screen_.follow_px;
            gy = (touch_point_.y - center_y) / screen_.follow_px;
        }
        // Glances snap (saccade-like); everything else eases.
        const float k = eyes::Ease(dt, pressed_ ? 14 : 18);
        gaze_x_ += (std::clamp(gx, -1.0f, 1.0f) - gaze_x_) * k;
        gaze_y_ += (std::clamp(gy, -1.0f, 1.0f) - gaze_y_) * k;
    }

    EyeGeom ComputeEye(const eyes::Shape& s, float home_x, float center_y, float scale, float blink,
                    uint32_t now, int index) const {
        EyeGeom g;
        const float shape_weight = 1.0f - std::min(1.0f, std::fabs(s.arc));
        g.cx = std::lround(home_x + (s.dx + gaze_x_ * 34) * scale);
        g.cy = std::lround(center_y + (s.dy + gaze_y_ * 26) * scale);
        int32_t x1 = g.cx, y1 = g.cy, x2 = g.cx, y2 = g.cy;
        auto grow = [&](int32_t l, int32_t t, int32_t r, int32_t b) {
            x1 = std::min(x1, l);
            y1 = std::min(y1, t);
            x2 = std::max(x2, r);
            y2 = std::max(y2, b);
        };
        if (shape_weight >= 0.03f) {
            g.w = std::max<int32_t>(4, std::lround(s.w * scale));
            g.h = std::max<int32_t>(4, std::lround(s.h * scale * blink * shape_weight));
            g.body_opa = std::lround(255 * shape_weight);
            g.tilt10 = g.h > g.w ? std::lround(s.tilt * 10) : 0;
            // Tilted bodies are drawn as a round-capped thick line; reach covers both.
            const int32_t reach = std::max(g.w, g.h) / 2 + 2;
            grow(g.cx - reach, g.cy - reach, g.cx + reach, g.cy + reach);
            if (s.lid >= 0.01f) {
                const float edge = g.cy - g.h / 2.0f + s.lid * g.h;
                const float slope = std::tan(s.lid_tilt * 0.0174533f) * g.w / 2;
                g.lid_on = 1;
                g.lid_l = std::lround(edge - slope);
                g.lid_r = std::lround(edge + slope);
            }
            const int32_t d = std::min(g.w, g.h);
            if (s.spin >= 0.05f && d >= 20) {
                g.swirl_opa = std::lround(255 * s.spin);
                g.swirl_d = d;
                g.swirl_rot = static_cast<int32_t>(now * 0.42f) % 360 + index * 90;
            }
        }
        const float arc_weight = std::min(1.0f, std::fabs(s.arc));
        if (arc_weight >= 0.03f) {
            g.cap_up = s.arc > 0;
            g.cap_opa = std::lround(255 * arc_weight);
            g.cap_d = std::max<int32_t>(10, std::lround(s.w * scale));
            g.cap_w = std::max<int32_t>(3, std::lround(g.cap_d * (g.cap_up ? 0.22f : 0.085f)));
            g.cap_cy = g.cy + std::lround(g.cap_d * (g.cap_up ? 0.22f : -0.28f));
            g.cap_rot = std::lround(s.tilt);
            const int32_t r = g.cap_d / 2 + 2;
            grow(g.cx - r, g.cap_cy - r, g.cx + r, g.cap_cy + r);
        }
        g.box = {x1, y1, x2, y2};
        return g;
    }

    void Draw(lv_layer_t* layer) {
        const int64_t start = esp_timer_get_time();
        lv_area_t origin;
        lv_obj_get_coords(canvas_, &origin);
        for (const auto& g : geom_)
            DrawEye(layer, g, origin.x1, origin.y1);
        const int64_t spent = esp_timer_get_time() - start;
        draw_us_ += spent;
        max_draw_us_ = std::max(max_draw_us_, spent);
        ++draws_;
    }

    static void DrawEye(lv_layer_t* layer, const EyeGeom& g, int32_t ox, int32_t oy) {
        const int32_t cx = ox + g.cx, cy = oy + g.cy;
        if (g.body_opa > 0) {
            if (g.tilt10 == 0) {
                lv_draw_rect_dsc_t body;
                lv_draw_rect_dsc_init(&body);
                body.bg_color = lv_color_white();
                body.bg_opa = g.body_opa;
                body.radius = LV_RADIUS_CIRCLE;
                const lv_area_t area = {cx - g.w / 2, cy - g.h / 2, cx - g.w / 2 + g.w - 1,
                                        cy - g.h / 2 + g.h - 1};
                lv_draw_rect(layer, &body, &area);
            } else {
                // Tilted pill: a thick line with round ends along the eye's long axis.
                const float a = g.tilt10 * 0.00174533f;
                const float half = (g.h - g.w) / 2.0f;
                lv_draw_line_dsc_t line;
                lv_draw_line_dsc_init(&line);
                line.color = lv_color_white();
                line.opa = g.body_opa;
                line.width = g.w;
                line.round_start = line.round_end = 1;
                line.p1 = {static_cast<lv_value_precise_t>(cx - std::sin(a) * half),
                           static_cast<lv_value_precise_t>(cy + std::cos(a) * half)};
                line.p2 = {static_cast<lv_value_precise_t>(cx + std::sin(a) * half),
                           static_cast<lv_value_precise_t>(cy - std::cos(a) * half)};
                lv_draw_line(layer, &line);
            }
            if (g.lid_on) {
                // Black wedge over the top of the eye; its lower edge is the lid line.
                const int32_t reach = std::max(g.w, g.h) / 2 + 2;
                const lv_value_precise_t l = cx - reach, r = cx + reach, top = cy - reach;
                const float k = static_cast<float>(g.lid_r - g.lid_l) / std::max<int32_t>(1, g.w);
                const lv_value_precise_t yl = oy + g.lid_l - k * (reach - g.w / 2);
                const lv_value_precise_t yr = oy + g.lid_r + k * (reach - g.w / 2);
                lv_draw_triangle_dsc_t tri;
                lv_draw_triangle_dsc_init(&tri);
                tri.color = lv_color_black();
                tri.opa = LV_OPA_COVER;
                tri.p[0] = {l, top};
                tri.p[1] = {r, top};
                tri.p[2] = {r, yr};
                lv_draw_triangle(layer, &tri);
                tri.p[1] = {r, yr};
                tri.p[2] = {l, yl};
                lv_draw_triangle(layer, &tri);
            }
            if (g.swirl_opa > 0) {
                lv_draw_arc_dsc_t arc;
                lv_draw_arc_dsc_init(&arc);
                arc.color = lv_color_black();
                arc.opa = g.swirl_opa;
                arc.center = {cx, cy};
                arc.width = std::max<int32_t>(3, g.swirl_d / 11);
                arc.rounded = 1;
                for (int r = 0; r < 2; ++r) {
                    const int32_t turn = r ? 360 - g.swirl_rot % 360 : g.swirl_rot;
                    arc.radius = static_cast<uint16_t>(g.swirl_d * (r ? 0.2f : 0.37f));
                    arc.start_angle = turn;
                    arc.end_angle = turn + (r ? 220 : 260);
                    lv_draw_arc(layer, &arc);
                }
            }
        }
        if (g.cap_opa > 0) {
            lv_draw_arc_dsc_t arc;
            lv_draw_arc_dsc_init(&arc);
            arc.color = lv_color_white();
            arc.opa = g.cap_opa;
            arc.center = {cx, oy + g.cap_cy};
            arc.radius = static_cast<uint16_t>(g.cap_d / 2);
            arc.width = g.cap_w;
            arc.rounded = 1;
            arc.start_angle = (g.cap_up ? 182 : 32) + g.cap_rot;
            arc.end_angle = (g.cap_up ? 358 : 148) + g.cap_rot;
            lv_draw_arc(layer, &arc);
        }
    }

    void Invalidate(const lv_area_t& a, const lv_area_t& b) {
        lv_area_t origin;
        lv_obj_get_coords(canvas_, &origin);
        lv_area_t u = a;
        if (b.x2 >= b.x1) {
            if (u.x2 < u.x1)
                u = b;
            else
                u = {std::min(a.x1, b.x1), std::min(a.y1, b.y1), std::max(a.x2, b.x2),
                     std::max(a.y2, b.y2)};
        }
        if (u.x2 < u.x1)
            return;
        lv_area_move(&u, origin.x1, origin.y1);
        lv_obj_invalidate_area(canvas_, &u);
    }

    void LogStats(uint32_t now) {
        if (now - last_stat_ < 30000)
            return;
        const float secs = (now - last_stat_) / 1000.0f;
        ESP_LOGI(kTag, "fps %.1f (logic %.1f), max gap %lums, draw avg %lldus max %lldus, "
                 "internal heap %u (min %u)",
                 refreshes_ / secs, renders_ / secs, static_cast<unsigned long>(max_gap_ms_),
                 draws_ ? draw_us_ / draws_ : 0, max_draw_us_,
                 static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
                 static_cast<unsigned>(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)));
        last_stat_ = now;
        refreshes_ = renders_ = max_gap_ms_ = draws_ = 0;
        draw_us_ = max_draw_us_ = 0;
    }

    void Render() {
        if (!canvas_)
            return;
        const uint32_t now = lv_tick_get();
        const uint32_t gap = now - last_tick_;
        const float dt = std::min<uint32_t>(gap, 100);
        last_tick_ = now;
        ++renders_;
        max_gap_ms_ = std::max(max_gap_ms_, gap);
        PollTouch(now);
        const auto mood = CurrentMood(now);
        const auto& spec = Spec(layout_);
        UpdateGaze(now, dt, mood, spec.box_y + spec.center_y);
        const float blink = BlinkFactor(now, mood);

        const auto target = eyes::FaceFor(mood, now / 1000.0f);
        const float k = eyes::Ease(dt, mood == eyes::Mood::Dizzy ? 16 : 11);
        face_.left = eyes::Mix(face_.left, target.left, k);
        face_.right = eyes::Mix(face_.right, target.right, k);

        const float half = eyes::kHomeX * spec.scale;
        const EyeGeom next[2] = {
            ComputeEye(face_.left, CenterX() - half, spec.center_y, spec.scale, blink, now, 0),
            ComputeEye(face_.right, CenterX() + half, spec.center_y, spec.scale, blink, now, 1)};
        for (int i = 0; i < 2; ++i) {
            if (!(next[i] == geom_[i])) {
                Invalidate(geom_[i].box, next[i].box);
                geom_[i] = next[i];
            }
        }
        LogStats(now);
    }
};
