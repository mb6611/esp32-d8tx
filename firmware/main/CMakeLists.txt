idf_component_register(SRCS "d8tone.c" "cmd_parse.c" "packet.c" "tlm_cap.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event nvs_flash esp_phy esp_hw_support esp_timer esp_hal_wdt esp_rom esp_driver_uart heap)
# Capture hot loop must keep up with 16 MS/s (8064 pairs per ~121k cycles); the project builds -Og.
set_source_files_properties(tlm_cap.c PROPERTIES COMPILE_OPTIONS "-O2")

# Firmware version for INFO (ver=<semver>+<hash>): D8TX_FW_SEMVER plus the first 8 hex digits of a SHA-256 over the
# firmware sources, so it changes exactly when the firmware does. firmware/tools/fw_version.mjs computes the same
# value (keep them in sync): sha256 of "<path>\n<sha256(content)>\n" for each file, sorted by path relative to firmware/.
set(D8TX_FW_SEMVER "1.0.0")
get_filename_component(_fw_root "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
file(GLOB _fw_files RELATIVE "${_fw_root}" "${_fw_root}/main/*.c" "${_fw_root}/main/*.h" "${_fw_root}/main/CMakeLists.txt"
    "${_fw_root}/CMakeLists.txt" "${_fw_root}/sdkconfig.defaults")
list(SORT _fw_files)
set(_fw_cat "")
foreach(f ${_fw_files})
    file(SHA256 "${_fw_root}/${f}" _h)
    string(APPEND _fw_cat "${f}\n${_h}\n")
    # re-run this hash when a source changes (CMakeLists and sdkconfig.defaults already re-run configure)
    if(f MATCHES "\\.[ch]$")
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_fw_root}/${f}")
    endif()
endforeach()
string(SHA256 _fw_hash "${_fw_cat}")
string(SUBSTRING "${_fw_hash}" 0 8 _fw_hash8)
set(D8TX_FW_VER "${D8TX_FW_SEMVER}+${_fw_hash8}")
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE D8TX_FW_VER="${D8TX_FW_VER}")
    file(WRITE "${CMAKE_BINARY_DIR}/d8tx_fw_version.txt" "${D8TX_FW_VER}\n")
    message(STATUS "d8tx firmware version ${D8TX_FW_VER}")
endif()
