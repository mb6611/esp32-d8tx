idf_component_register(SRCS "d8tone.c" "cmd_parse.c" "packet.c" "tlm_cap.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event nvs_flash esp_phy esp_hw_support esp_timer esp_hal_wdt esp_rom esp_driver_uart heap)
# Capture hot loop must keep up with 16 MS/s (8064 pairs per ~121k cycles); the project builds -Og.
set_source_files_properties(tlm_cap.c PROPERTIES COMPILE_OPTIONS "-O2")
