#pragma once
// On first boot, save the firmware's built-in OTA address (CONFIG_OTA_URL) to the
// Wi-Fi settings. The config page only shows a saved address, so otherwise its
// OTA field is empty and looks like it needs filling in. An address that is
// already saved (for example typed on the config page) is left alone.

#include <esp_log.h>

#include "settings.h"

inline void SeedDefaultOtaUrl() {
    Settings settings("wifi", true);
    if (settings.GetString("ota_url").empty()) {
        settings.SetString("ota_url", CONFIG_OTA_URL);
        ESP_LOGI("ZongzhuOta", "Saved built-in OTA URL %s", CONFIG_OTA_URL);
    }
}
