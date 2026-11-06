idf_component_register(SRCS "d8tone.c" "cmd_parse.c" "packet.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event nvs_flash esp_phy esp_hw_support esp_timer esp_hal_wdt esp_rom esp_driver_uart)
