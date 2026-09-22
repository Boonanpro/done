#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef esp_err_t (*wifi_audio_read_t)(uint8_t*,size_t,size_t*,void*);
typedef esp_err_t (*wifi_audio_write_t)(uint8_t*,size_t,void*);
void wifi_audio_init(wifi_audio_read_t read_cb,wifi_audio_write_t write_cb);
bool wifi_audio_active(void);
bool wifi_audio_requested(void);
bool wifi_audio_requested_with_cue(bool *local);
bool wifi_audio_ready(void);
void wifi_audio_set_requested(bool enabled);
void wifi_audio_status(char *out,size_t size);
esp_err_t wifi_audio_configure(const char *json);
void wifi_audio_scan(char *out,size_t size);
