/* Register census of the classic ESP32 PHY capture block
 * (0x60033d00..0x60033dff), looking for an S3-style I/Q TX playback engine.
 *
 * PHY bring-up copies esp-sdr's ESP32 backend (vendor/esp-sdr,
 * main/targets/esp32/receiver.c): Wi-Fi init/start, promiscuous, channel 1,
 * then pbus work mode, TX off, RX on, RX clock on.
 *
 * Each word is probed inside a critical section: read original, read 16x for
 * spontaneous changes, write ones (masked for DUMP_CTRL run/trigger), read
 * immediately and after 20 us, write zero, read twice, restore original.
 * A cursor in RTC no-init memory marks the address in progress; the RTC WDT
 * (and panic reboot) resets the chip on a hang and the next boot logs
 * "H,<pass>,<addr>,<reason>" and resumes past that address.
 *
 * Pass 1: bank not granted (DPORT MAC_DUMP_MODE as found).
 * Pass 2: MAC_DUMP_MODE = 3 (capture bank granted to the MAC) for the whole pass.
 *
 * Output lines (UART0, 921600):
 *   S,<pass>,<addr>,<value>                      read-only snapshot before writes
 *   R,<pass>,<addr>,<orig>,<spont>,<wr1>,<rb1>,<rb1late>,<rb0>,<rb0late>,<final>
 *   H,<pass>,<addr>,<reset_reason>
 *   T,<tag>,<ok>,<ctrl>,<status>,<written_words>  capture self-test
 *   I,<key>,<value>                              info
 *   DONE
 */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_attr.h"
#include "esp_rom_sys.h"
#include "nvs_flash.h"
#include "soc/soc.h"
#include "soc/dport_reg.h"
#include "soc/dport_access.h"
#include "hal/wdt_hal.h"
#include "heap_memory_layout.h"
#include "esp_rom_serial_output.h"

/* Same reservation as esp-sdr: the 64 KiB capture aperture must not hold heap. */
SOC_RESERVE_MEMORY_REGION(0x3ffe8000, 0x3fff8000, census_rf_dump);

#define BLOCK_START 0x60033d00u
#define BLOCK_END   0x60033e00u /* exclusive */
#define DUMP_CTRL   0x60033d90u
#define DUMP_STATUS 0x60033d94u
#define DUMP_BYTES  0x60033dc4u
#define SENTINEL    0xa55aa55au
#define MAGIC       0xce455a17u

extern void rom_pbus_workmode(void);
extern void rom_pbus_xpd_rx_on(int);
extern void rom_pbus_xpd_tx_off(void);
extern void rom_set_rxclk_en(int);

typedef struct {
    uint32_t magic;
    uint32_t pass;    /* 1 or 2; 3 = finished */
    uint32_t addr;    /* next address to probe */
    uint32_t busy;    /* 1 while addr is being probed */
    uint32_t hangs;
} cursor_t;
static RTC_NOINIT_ATTR cursor_t cur;

static uint32_t *const samples = (void *)0x3ffe8000;
static wdt_hal_context_t rwdt = RWDT_HAL_CONTEXT_DEFAULT();
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

static void flush_out(void) {
    fflush(stdout);
    esp_rom_output_tx_wait_idle(0);
}

static void feed(void) {
    wdt_hal_write_protect_disable(&rwdt);
    wdt_hal_feed(&rwdt);
    wdt_hal_write_protect_enable(&rwdt);
}

static void rwdt_start(void) {
    /* RTC slow clock ~150 kHz: 450000 ticks ~ 3 s, reset main system (RTC memory kept). */
    wdt_hal_init(&rwdt, WDT_RWDT, 0, false);
    wdt_hal_write_protect_disable(&rwdt);
    wdt_hal_config_stage(&rwdt, WDT_STAGE0, 450000, WDT_STAGE_ACTION_RESET_SYSTEM);
    wdt_hal_enable(&rwdt);
    wdt_hal_write_protect_enable(&rwdt);
}

static void phy_up(void) {
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        e = nvs_flash_init();
    }
    ESP_ERROR_CHECK(e);
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE));
    rom_pbus_workmode();
    rom_pbus_xpd_tx_off();
    rom_pbus_xpd_rx_on(1);
    rom_set_rxclk_en(1);
}

static void grant(bool on) {
    uint32_t v = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG) & ~DPORT_MAC_DUMP_MODE_M;
    if (on) v |= 3u << DPORT_MAC_DUMP_MODE_S;
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, v);
}

/* esp-sdr acquire_iq, n=256, source 0, 40 MS/s. Proves the block is clocked. */
static void capture_test(const char *tag) {
    const unsigned n = 256;
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    REG_WRITE(DUMP_CTRL, 0);
    grant(true);
    for (unsigned j = 0; j < 1024; j++) samples[j] = SENTINEL;
    uint32_t bytes = REG_READ(DUMP_BYTES);
    REG_WRITE(DUMP_BYTES, 0x03020100);
    uint32_t ctrl = n | BIT(15);
    REG_WRITE(DUMP_CTRL, ctrl | BIT(31));
    int64_t t0 = esp_timer_get_time();
    REG_SET_BIT(DUMP_CTRL, BIT(19));
    REG_CLR_BIT(DUMP_CTRL, BIT(19));
    while (!(REG_READ(DUMP_CTRL) & BIT(18)) && esp_timer_get_time() - t0 < 20000) {}
    uint32_t r = REG_READ(DUMP_CTRL), s = REG_READ(DUMP_STATUS);
    REG_WRITE(DUMP_CTRL, 0);
    esp_rom_delay_us(10);
    unsigned written = 0;
    for (unsigned j = 0; j < 1024; j++) written += samples[j] != SENTINEL;
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    REG_WRITE(DUMP_BYTES, bytes);
    bool ok = (r & BIT(18)) && (s & 0x7fff) == n && written == n;
    printf("T,%s,%d,%08" PRIx32 ",%08" PRIx32 ",%u\n", tag, ok, r, s, written);
    flush_out();
}

static void probe(unsigned pass, uint32_t a) {
    uint32_t wr1 = 0xffffffffu;
    if (a == DUMP_CTRL) wr1 &= ~(BIT(31) | BIT(19)); /* never start a capture */
    uint32_t orig, spont = 0, rb1, rb1l, rb0, rb0l, fin;
    portENTER_CRITICAL(&mux);
    orig = REG_READ(a);
    for (int k = 0; k < 16; k++) {
        esp_rom_delay_us(5);
        spont |= REG_READ(a) ^ orig;
    }
    REG_WRITE(a, wr1);
    rb1 = REG_READ(a);
    esp_rom_delay_us(20);
    rb1l = REG_READ(a);
    REG_WRITE(a, 0);
    rb0 = REG_READ(a);
    esp_rom_delay_us(20);
    rb0l = REG_READ(a);
    REG_WRITE(a, orig);
    fin = REG_READ(a);
    portEXIT_CRITICAL(&mux);
    printf("R,%u,%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32
           ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 "\n",
           pass, a, orig, spont, wr1, rb1, rb1l, rb0, rb0l, fin);
    flush_out();
}

static void snapshot(unsigned pass) {
    for (uint32_t a = BLOCK_START; a < BLOCK_END; a += 4)
        printf("S,%u,%08" PRIx32 ",%08" PRIx32 "\n", pass, a, REG_READ(a));
    flush_out();
}

void app_main(void) {
    esp_reset_reason_t why = esp_reset_reason();
    bool resume = cur.magic == MAGIC && why != ESP_RST_POWERON && why != ESP_RST_EXT &&
                  why != ESP_RST_BROWNOUT && cur.pass >= 1 && cur.pass <= 3;
    printf("\nI,boot,reason=%d resume=%d\n", (int)why, resume);
    if (!resume) {
        cur = (cursor_t){.magic = MAGIC, .pass = 1, .addr = BLOCK_START, .busy = 0, .hangs = 0};
    } else if (cur.busy) {
        printf("H,%" PRIu32 ",%08" PRIx32 ",%d\n", cur.pass, cur.addr, (int)why);
        cur.busy = 0;
        cur.hangs++;
        cur.addr += 4;
    }
    flush_out();
    if (cur.pass == 3) {
        printf("I,state,finished hangs=%" PRIu32 "\nDONE\n", cur.hangs);
        flush_out();
        for (;;) vTaskDelay(portMAX_DELAY);
    }

    phy_up();
    vTaskDelay(pdMS_TO_TICKS(100));
    printf("I,ahb_sel,%08" PRIx32 "\n", DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG));
    if (!resume) capture_test("pre");
    rwdt_start();

    while (cur.pass <= 2) {
        grant(cur.pass == 2);
        printf("I,pass,%" PRIu32 " ahb_sel=%08" PRIx32 "\n", cur.pass,
               DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG));
        if (cur.addr == BLOCK_START) snapshot(cur.pass);
        while (cur.addr < BLOCK_END) {
            feed();
            cur.busy = 1;
            probe(cur.pass, cur.addr);
            vTaskDelay(pdMS_TO_TICKS(5)); /* let a delayed fault land on this address */
            cur.busy = 0;
            cur.addr += 4;
        }
        snapshot(cur.pass + 10); /* post-pass read-back: 11 / 12 */
        grant(false);
        cur.pass++;
        cur.addr = BLOCK_START;
    }
    feed();
    capture_test("post");
    printf("I,state,finished hangs=%" PRIu32 "\nDONE\n", cur.hangs);
    flush_out();
    wdt_hal_write_protect_disable(&rwdt);
    wdt_hal_disable(&rwdt);
    wdt_hal_write_protect_enable(&rwdt);
    for (;;) vTaskDelay(portMAX_DELAY);
}
