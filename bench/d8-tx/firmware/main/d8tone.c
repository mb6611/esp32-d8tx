/* d8tone: bounded tone bench app for the classic ESP32 DevKit V1 (U2).
 *
 * PHY bring-up, keying and unkeying are adapted from the read-only reference
 * auto-drone/stage2/txeng (K 0 keying: txcal_debuge_mode(0) + ROM start_tx_tone_step + PBUS(5,1)).
 * Boot and idle are RF-silent: nothing keys until a TONE/ALT command arrives.
 * Channel is the PHY default Wi-Fi ch1 (2412 MHz); the tone offset is added to that.
 *
 * Serial 921600 8N1, line commands (decimal only). Every command ends with "OK" or "ERR <why>":
 *   PING                       -> P,d8tone,1
 *   STAT                       -> S,keyed=0,b8=XXXXXXXX,a8=XXXXXXXX
 *   U                          unkey unconditionally (idempotent)
 *   TONE f dur_us [pwr]        key one tone at step offset f (|f|<=511, 0 = center), for dur_us
 *                              (50..200000), pwr 0..127 (default 127), then unkey
 *   ALT fa fb half_us dur_us [pwr]   key at fa, switch fa<->fb every half_us (>=50, <=255 switches)
 *   PKT hex [pwr]             18-byte length+payload (CRC appended) or 20-byte full U3
 *                             packet including CRC (transmitted verbatim), pwr default 127.
 *                             Example: PKT 1142b2000001cacacaca8888cacacaca8888
 *   RETUNE khz                 move the LO to khz (2404000..2478000) with the fast retune (capacitor-code
 *                              release + rom_set_rf_freq_offset, ~0.27 ms, no recalibration); no keying.
 *                              Afterwards TONE/ALT (tone offset f=0 is the LO) are capped at 150 ms until
 *                              RETUNE 2412000 restores the boot LO. Refused while keyed.
 *   FOFS hz                    signed LO offset (|hz|<=200000, default 0, RAM only) added to RETUNE and HOP retunes
 *   STICKS c1..c8              eight stick values in us (800..2200) for HOP packets (default 1500 each)
 *   HOP n_slots [pwr]          (n<=940) stream D8 data packets, one per ~8.994 ms slot, on the E8 hop table
 *                              (start 2, step 55, entry 0 = 0; channel n = 2404 MHz + n*299.93 kHz), packet
 *                              counter (byte 4) +1 per packet, id 42 b2, byte-identical to host d8hop
 *                              build(counter_index=4). Per slot: retune, key, 208 bits, unkey (one
 *                              critical section), then WDT feed + UART poll; any UART byte aborts. LO is
 *                              restored to 2412 MHz afterwards. Reply:
 *                              K,hop,slots=N,late_max_us=X,retune_max_us=Y then OK. ERR -> unkeyed.
 * Results are printed only after unkey:
 *   K,<mode>,fa,fb,half_us,req_us,pwr,on_us,key_total_us,key_cycles,unkey_cycles,b8_on,b8_end,b8_off,a8_on,a8_off,ntrans
 *   T,<i>,<due_us>,<actual_us>,<b8_readback>        one per transition (time since tone on, 240 MHz cycles/240)
 * on_us = device-clock time from end of key() to the start of unkey(). b8_off bit18 must be 0.
 * All timing is the ESP32 CPU cycle counter; none of this is RF evidence (see plan R2/R3).
 * The RTC WDT (~3 s, reset-system) is fed every <=10 ms input poll: a hang reboots into the RF-silent state
 * ("I,boot,reason=N"). The tone window busy-waits with interrupts off, at most 200 ms.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_cpu.h"
#include "nvs_flash.h"
#include "soc/soc.h"
#include "soc/rtc.h"
#include "hal/wdt_hal.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "cmd_parse.h"
#include "packet.h"
#include "line_in.h"

#define TONE0 0x600060b8u /* tone NCO: [27:0] f, bit18 enable, [17:10] -gain */
#define TONE_FINE 0x600050a8u /* low f bits when TONE0 bit29 set */
#define CYC_PER_US 240u

extern void rom_pbus_workmode(void);
extern void rom_pbus_xpd_rx_on(int);
extern void rom_pbus_xpd_tx_off(void);
extern void rom_set_rxclk_en(int);
extern void rom_start_tx_tone_step(int en, int f, int g, int en2, int f2, int g2);
extern void rom_stop_tx_tone(int which);
extern void rom_pbus_force_test(int row, int col, int val);
extern void txcal_debuge_mode(int);
extern void **g_phyFuns;
extern unsigned ram_chip_i2c_readReg(unsigned, unsigned, unsigned);
extern void ram_chip_i2c_writeReg(unsigned, unsigned, unsigned, unsigned);
extern void rom_set_rf_freq_offset(unsigned crystal, unsigned mhz, int offset);

static wdt_hal_context_t rwdt = RWDT_HAL_CONTEXT_DEFAULT();
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static volatile bool keyed;

static void feed(void) {
    wdt_hal_write_protect_disable(&rwdt);
    wdt_hal_feed(&rwdt);
    wdt_hal_write_protect_enable(&rwdt);
}

static void rwdt_start(void) {
    wdt_hal_init(&rwdt, WDT_RWDT, 0, false);
    wdt_hal_write_protect_disable(&rwdt);
    wdt_hal_config_stage(&rwdt, WDT_STAGE0, 450000, WDT_STAGE_ACTION_RESET_SYSTEM);
    wdt_hal_enable(&rwdt);
    wdt_hal_write_protect_enable(&rwdt);
}

static void rx_mode(void) {
    rom_pbus_workmode();
    rom_pbus_xpd_tx_off();
    rom_pbus_xpd_rx_on(1);
    rom_set_rxclk_en(1);
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
    rx_mode();
}

/* Tone offset f (signed step units) into the ROM call. With b8 bit29 set the ROM splits f into
 * 2 fine bits (0x600050a8) + f>>2, so the field is 12 bits wide; otherwise 10. Passing a negative
 * int would sign-extend into the enable/gain bits, so mask first and let the ROM see two's complement. */
static void tone_set(int f) {
    int mask = (REG_READ(TONE0) & BIT(29)) ? 0xfff : 0x3ff;
    rom_start_tx_tone_step(1, f & mask, 127, 0, 0, 0);
}

static void key(int f, int pwr) {
    txcal_debuge_mode(0);
    tone_set(f);
    rom_pbus_force_test(5, 1, pwr);
}

/* libphy's stop path (as stage2 txeng unkey), then receive-only PBUS setup. Idempotent. */
static void unkey(void) {
    ((void (*)(int, int, int, int, int, int))g_phyFuns[68 / 4])(0, 0, 0, 0, 0, 0);
    ((void (*)(void))g_phyFuns[0x124 / 4])();
    rom_stop_tx_tone(1);
    rx_mode();
    keyed = false;
}

typedef struct { uint32_t due, actual, rb; } trans_t;
static trans_t trans[ALT_MAX_TRANS + 1];

static inline uint32_t cyc(void) { return esp_cpu_get_cycle_count(); }

static void run_window(const cmd_t *c) {
    unsigned nt = 0;
    const uint32_t dur = c->dur_us * CYC_PER_US, half = c->half_us * CYC_PER_US;
    const bool alt = c->kind == CMD_ALT;
    uint32_t b8_on, b8_end, b8_off, a8_on, a8_off;
    feed();
    portENTER_CRITICAL(&mux);
    int64_t tk0 = esp_timer_get_time();
    uint32_t c0 = cyc();
    keyed = true; /* set before key so a fault path always unkeys */
    key(c->f_a, c->pwr);
    uint32_t t0 = cyc(); /* tone-on reference */
    uint32_t key_cyc = t0 - c0;
    b8_on = REG_READ(TONE0);
    a8_on = REG_READ(TONE_FINE);
    uint32_t next = half;
    bool onb = false;
    uint32_t el;
    while ((el = cyc() - t0) < dur) {
        if (alt && el >= next && nt < ALT_MAX_TRANS) {
            onb = !onb;
            tone_set(onb ? c->f_b : c->f_a);
            trans[nt].due = next;
            trans[nt].actual = el;
            trans[nt].rb = REG_READ(TONE0);
            nt++;
            next += half;
        }
    }
    b8_end = REG_READ(TONE0);
    uint32_t u0 = cyc();
    unkey();
    uint32_t unkey_cyc = cyc() - u0;
    int64_t tk1 = esp_timer_get_time();
    b8_off = REG_READ(TONE0);
    a8_off = REG_READ(TONE_FINE);
    portEXIT_CRITICAL(&mux);
    printf("K,%s,%d,%d,%" PRIu32 ",%" PRIu32 ",%d,%" PRIu32 ",%" PRId64 ",%" PRIu32 ",%" PRIu32
           ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%u\n",
           alt ? "alt" : "tone", c->f_a, c->f_b, c->half_us, c->dur_us, c->pwr, (u0 - t0) / CYC_PER_US,
           tk1 - tk0, key_cyc, unkey_cyc, b8_on, b8_end, b8_off, a8_on, a8_off, nt);
    for (unsigned i = 0; i < nt; i++)
        printf("T,%u,%" PRIu32 ",%" PRIu32 ",%08" PRIx32 "\n", i, trans[i].due / CYC_PER_US,
               trans[i].actual / CYC_PER_US, trans[i].rb);
    printf("OK\n");
}

/* D8 register values in Betaflight cc2500FrskyDConfig (26 MHz XOSC):
 * MDMCFG4=0xaa, MDMCFG3=0x39: (256+57)*2^10*26MHz/2^28 = 31044.006 baud.
 * DEVIATN=0x42: (8+2)*2^4*26MHz/2^17 = 31738.281 Hz deviation.
 * On-chip f step measured 40MHz/1024=39062.5 Hz: f=+1 for bit 1,
 * f=-1 for bit 0 (closest available signed deviation; f=2 is 78 kHz).
 * 240MHz / 31044.006 = 7730.961 cycles/bit; rounded 7731, total
 * phase drift across 208 bits <9 cycles. Hard key window <7ms (<10ms cap).
 * Hardware GFSK pulse shaping is unavailable via the tone path: this is
 * abrupt 2-FSK, not the CC2500 Gaussian-filtered modulation. */
static void run_packet(const cmd_t *c) {
    uint8_t air[D8_AIR_BYTES];
    if (!d8_air_bytes(c->packet, c->packet_len, air)) { printf("ERR packet\n"); return; }
    const uint32_t duration = D8_AIR_BITS * D8_BIT_CYCLES;
    if (duration > 10000u * CYC_PER_US) { printf("ERR duration\n"); return; }
    uint32_t b8_on, b8_end, b8_off, a8_on, a8_off, max_late = 0;
    unsigned late_count = 0;
    feed();
    portENTER_CRITICAL(&mux);
    uint32_t c0 = cyc();
    keyed = true;
    key((air[0] & 0x80) ? 1 : -1, c->pwr);
    uint32_t t0 = cyc();
    b8_on = REG_READ(TONE0); a8_on = REG_READ(TONE_FINE);
    for (unsigned i = 1; i < D8_AIR_BITS; i++) {
        uint32_t due = i * D8_BIT_CYCLES;
        while ((int32_t)(cyc() - t0 - due) < 0) { }
        tone_set((air[i >> 3] & (0x80u >> (i & 7))) ? 1 : -1);
        uint32_t late = cyc() - t0 - due; /* completion, including ROM tone-set latency */
        if (late) late_count++;
        if (late > max_late) max_late = late;
    }
    while ((int32_t)(cyc() - t0 - duration) < 0) { }
    b8_end = REG_READ(TONE0);
    uint32_t u0 = cyc();
    unkey();
    uint32_t unkey_cyc = cyc() - u0;
    b8_off = REG_READ(TONE0); a8_off = REG_READ(TONE_FINE);
    portEXIT_CRITICAL(&mux);
    printf("K,pkt,bits=%u,pwr=%d,on_us=%" PRIu32 ",key_cycles=%" PRIu32
           ",unkey_cycles=%" PRIu32 ",max_late_ns=%" PRIu32 ",late_bits=%u"
           ",b8_on=%08" PRIx32 ",b8_end=%08" PRIx32 ",b8_off=%08" PRIx32
           ",a8_on=%08" PRIx32 ",a8_off=%08" PRIx32 "\nOK\n",
           D8_AIR_BITS, c->pwr, (u0-t0)/CYC_PER_US, t0-c0, unkey_cyc,
           max_late * 1000u / CYC_PER_US, late_count,
           b8_on, b8_end, b8_off, a8_on, a8_off);
}

static int fofs_hz; /* RAM-only LO offset applied to RETUNE and HOP retunes */
static volatile bool lo_off; /* LO moved off the boot 2412 MHz */
static uint16_t sticks_raw[D8_STICKS] = {2250, 2250, 2250, 2250, 2250, 2250, 2250, 2250};
static bool arm_ok; /* set by ARMOK while idle; cleared when any HOP ends and at boot */
static int ch7_gate(int us) { return (!arm_ok && us > S_CH7_US_MAX) ? S_CH7_US_MAX : us; }


/* Fast retune to f10 (10 Hz units): capacitor-code release, then ROM offset (1/1024 MHz). */
static void lo_retune(uint32_t f10) {
    unsigned mhz = f10 / 100000u, rem = f10 % 100000u;
    int offset = (int)((rem * 1024u + 50000u) / 100000u);
    unsigned xtal = rtc_clk_xtal_freq_get();
    unsigned cap = ram_chip_i2c_readReg(0x62, 1, 0);
    ram_chip_i2c_writeReg(0x62, 1, 0, cap & ~0x80u);
    rom_set_rf_freq_offset(xtal == 26 ? 1 : xtal == 24 ? 2 : 0, mhz, offset);
}

#define HOP_SLOT_CYC (8994u * CYC_PER_US)

/* Non-blocking input drain during continuous HOP. Returns 0 = nothing/applied S, 1 = stop (U/STOP
 * or any other input; *err set for the latter). */
static int hop_drain(line_in_t *li, const char **err, int64_t *last_s_us) {
    uint8_t b;
    while (uart_read_bytes(UART_NUM_0, &b, 1, 0) == 1) {
        if (b != '\n' && b != '\r') {
            if (li->len < sizeof li->buf - 1) li->buf[li->len++] = (char)b;
            else li->len = sizeof li->buf;
            continue;
        }
        if (!li->len) continue;
        int over = li->len >= sizeof li->buf;
        li->buf[over ? 0 : li->len] = 0;
        li->len = 0;
        if (over) { *err = "long"; return 1; }
        cmd_t c = cmd_parse(li->buf);
        if (c.kind == CMD_NONE) continue;
        if (c.kind == CMD_S) {
            for (unsigned i = 0; i < D8_STICKS; i++) sticks_raw[i] = d8_us_to_raw(i == 6 ? ch7_gate(c.sticks[i]) : c.sticks[i]);
            *last_s_us = esp_timer_get_time();
            continue;
        }
        if (c.kind == CMD_UNKEY) return 1;
        *err = c.kind == CMD_ERR ? c.err : "hop_busy";
        return 1;
    }
    return 0;
}

static void run_hop(const cmd_t *c) {
    uint8_t tab[D8_HOP_CHANNELS], body[D8_BODY_BYTES], air[D8_AIR_BYTES];
    d8_hop_table(2, 55, tab);
    uint32_t late_max = 0, rt_max = 0;
    unsigned sent = 0;
    bool abort = false;
    const bool cont = c->n_slots == 0;
    const char *why = "done", *err = NULL;
    static line_in_t hli;
    hli.len = 0;
    feed();
    int64_t last_s_us = esp_timer_get_time(), last_st_us = last_s_us;
    uint32_t base = cyc();
    uint32_t slot_start = base; /* scheduled start of the current slot */
    for (unsigned k = 0; (cont || k < c->n_slots) && !abort; k++) {
        d8_build_body(D8_TXID0, D8_TXID1, (uint8_t)k, sticks_raw, body);
        if (!d8_air_bytes(body, D8_BODY_BYTES, air)) { printf("ERR packet\n"); abort = true; why = "packet"; break; }
        uint32_t f10 = d8_channel_f10(tab[k % D8_HOP_CHANNELS]);
        while ((int32_t)(cyc() - slot_start) < 0) { /* wait for the slot (interrupts on) */
            if (cont && hop_drain(&hli, &err, &last_s_us)) { abort = true; break; }
        }
        if (abort) { why = err ? "err" : "stop"; break; }
        uint32_t late = cyc() - slot_start;
        if (late > HOP_SLOT_CYC) slot_start = cyc(); /* overran a whole slot: resync, don't burst */
        if (late > late_max) late_max = late;
        feed();
        if (cont && esp_timer_get_time() - last_s_us > (int64_t)c->timeout_ms * 1000) { why = "timeout"; break; }
        portENTER_CRITICAL(&mux);
        uint32_t r0 = cyc();
        lo_retune(f10 + (uint32_t)(fofs_hz / 10));
        uint32_t r1 = cyc() - r0;
        if (r1 > rt_max) rt_max = r1;
        keyed = true;
        key((air[0] & 0x80) ? 1 : -1, c->pwr);
        uint32_t t0 = cyc();
        for (unsigned i = 1; i < D8_AIR_BITS; i++) {
            uint32_t due = i * D8_BIT_CYCLES;
            while ((int32_t)(cyc() - t0 - due) < 0) { }
            tone_set((air[i >> 3] & (0x80u >> (i & 7))) ? 1 : -1);
        }
        while ((int32_t)(cyc() - t0 - D8_AIR_BITS * D8_BIT_CYCLES) < 0) { }
        unkey();
        portEXIT_CRITICAL(&mux);
        sent++;
        slot_start += HOP_SLOT_CYC;
        if (cont) {
            int64_t now = esp_timer_get_time();
            if (now - last_st_us >= 1000000) { /* <=1 short status line per second */
                last_st_us = now;
                printf("K,hop,s=%u\n", sent);
            }
        } else {
            uint8_t b;
            if (uart_read_bytes(UART_NUM_0, &b, 1, 0) == 1) { abort = true; why = "byte"; }
        }
    }
    if (keyed) unkey();
    lo_retune(241200000u); /* 2412 MHz = 241,200,000 x 10 Hz */
    lo_off = false;
    if (err) printf("ERR %s\n", err);
    printf("K,hop,slots=%u,late_max_us=%" PRIu32 ",retune_max_us=%" PRIu32 ",why=%s\nOK\n", sent,
           late_max / CYC_PER_US, rt_max / CYC_PER_US, why);
}

/* Bounded 10 ms read straight from the UART driver (not stdin): returns -1 when idle. */
static int rd_byte(void *ctx) {
    (void)ctx;
    uint8_t b;
    return uart_read_bytes(UART_NUM_0, &b, 1, pdMS_TO_TICKS(10)) == 1 ? b : -1;
}
static void feed_cb(void *ctx) { (void)ctx; feed(); }

void app_main(void) {
    printf("\nI,boot,reason=%d\n", (int)esp_reset_reason());
    fflush(stdout);
    phy_up();
    rom_stop_tx_tone(1); /* tone enable off: RF-silent regardless of prior state */
    vTaskDelay(pdMS_TO_TICKS(100));
    uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0);
    uart_vfs_dev_use_driver(UART_NUM_0); /* stdout only; input is polled via uart_read_bytes */
    rwdt_start();
    printf("I,ready,b8=%08" PRIx32 "\n", REG_READ(TONE0));
    fflush(stdout);
    static line_in_t li;
    for (;;) {
        line_res_t r = line_poll(&li, rd_byte, feed_cb, NULL);
        if (r == LINE_NONE) continue;
        if (r == LINE_LONG) { printf("ERR long\n"); fflush(stdout); continue; }
        char *line = li.buf;
        cmd_t c = cmd_parse(line);
        switch (c.kind) {
        case CMD_NONE: break;
        case CMD_ERR:
            if (keyed) unkey();
            printf("ERR %s\n", c.err);
            break;
        case CMD_PING: printf("P,d8tone,1\nOK\n"); break;
        case CMD_STAT:
            printf("S,keyed=%d,b8=%08" PRIx32 ",a8=%08" PRIx32 ",fofs=%d\nOK\n", keyed, REG_READ(TONE0),
                   REG_READ(TONE_FINE), fofs_hz);
            break;
        case CMD_UNKEY: unkey(); printf("OK\n"); break;
        case CMD_TONE:
        case CMD_ALT:
            if (lo_off && c.dur_us > RETUNE_TONE_MAX_US) { printf("ERR retuned_dur\n"); break; }
            /* after RETUNE only the bare LO (f=0) is allowed, so keying stays on the retuned D8 channel */
            if (lo_off && (c.f_a != 0 || (c.kind == CMD_ALT && c.f_b != 0))) { printf("ERR retuned_f\n"); break; }
            run_window(&c);
            break;
        case CMD_RETUNE:
            if (keyed) { printf("ERR keyed\n"); break; }
            lo_retune((uint32_t)((int)c.khz * 100 + fofs_hz / 10));
            lo_off = (int)c.khz * 100 + fofs_hz / 10 != 241200000;
            printf("OK\n");
            break;
        case CMD_STICKS:
        case CMD_S:
            for (unsigned i = 0; i < D8_STICKS; i++)
                sticks_raw[i] = d8_us_to_raw(i == 6 && c.sticks[i] > S_CH7_US_MAX ? S_CH7_US_MAX : c.sticks[i]);
            printf("OK\n");
            break;
        case CMD_FOFS: fofs_hz = c.hz; printf("OK\n"); break;
        case CMD_ARMOK: arm_ok = true; printf("OK\n"); break;
        case CMD_HOP:
            if (keyed) { printf("ERR keyed\n"); break; }
            run_hop(&c);
            arm_ok = false;
            for (unsigned i = 0; i < D8_STICKS; i++) /* never leave ARM high in stored sticks */
                if (i == 6 && sticks_raw[i] > d8_us_to_raw(S_CH7_US_MAX)) sticks_raw[i] = d8_us_to_raw(1000);
            break;
        case CMD_PKT: run_packet(&c); break;
        }
        fflush(stdout);
    }
}
