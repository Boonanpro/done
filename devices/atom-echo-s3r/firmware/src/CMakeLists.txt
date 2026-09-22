idf_component_register(SRCS "main.c" "wifi_audio.c" INCLUDE_DIRS "." REQUIRES driver usb_device_uac espressif__tinyusb esp_wifi esp_netif nvs_flash esp_timer json lwip)
