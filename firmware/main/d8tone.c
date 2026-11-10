/* d8tone: bounded tone bench app for the classic ESP32 DevKit V1 (U2).
 *
 * PHY bring-up, keying and unkeying are adapted from the read-only reference
 * tools/txeng (K 0 keying: txcal_debuge_mode(0) + ROM start_tx_tone_step + PBUS(5,1)).
 * Boot and idle are RF-silent: nothing keys until a keying command (LINK, BIND, HOP 0, or in a bench build TONE/ALT/
 * PKT/HOP n/keyed TCAP) arrives.
 *
 * Build configurations (firmware/main/Kconfig.projbuild; INFO reports bench=<0|1> at the end of its line):
 *   release (CONFIG_D8_BENCH=n, default): LINK (continuous 47-channel hopping), BIND, HOP 0 (continuous hop), S, STOP/U,
 *     FOFS, ARMOK, INFO, STAT, TLM, TLMX, TID, ID, PING, STICKS, receive-only TCAP. The fixed-channel / CW bench
 *     commands below marked [bench] are not compiled in; the parser answers "ERR bench-only" (protocol v1 TCAP with a
 *     pwr: "ERR bench-only bench build required").
 *   bench (CONFIG_D8_BENCH=y): additionally TONE, ALT, RETUNE, PKT, HOP n_slots>0 and keyed TCAP [bench]. pwr is optional
 *     (default PWR_MAX) as before. They are fixed-channel / CW modes (47 CFR 15.249 case), not LINK.
 *   CONFIG_D8_PWR_MAX (default 127) caps the pwr of every keying command (LINK, BIND, HOP, bench modes); INFO pwr_max=.
 *   pwr is a raw PBUS(5,1) code, not dBm; no calibration exists.
 * Channel is the PHY default Wi-Fi ch1 (2412 MHz); the tone offset is added to that.
 *
 * Serial 921600 8N1, line commands (decimal only). Every command ends with "OK" or "ERR <why>":
 *   PING                       -> P,d8tone,1
 *   STAT                       -> S,keyed=0,b8=XXXXXXXX,a8=XXXXXXXX
 *   U                          unkey unconditionally (idempotent)
 *   [bench] TONE f dur_us [pwr] key one tone at step offset f (|f|<=511, 0 = center), for dur_us
 *                              (50..200000), pwr 0..PWR_MAX (default PWR_MAX), then unkey
 *   [bench] ALT fa fb half_us dur_us [pwr]   key at fa, switch fa<->fb every half_us (>=50, <=255 switches)
 *   [bench] PKT hex [pwr]      18-byte length+payload (CRC appended) or 20-byte full U3
 *                             packet including CRC (transmitted verbatim), pwr default PWR_MAX.
 *                             Example: PKT 1142b2000001cacacaca8888cacacaca8888
 *   [bench] RETUNE khz         move the LO to khz (2404000..2478000) with the fast retune (capacitor-code
 *                              release + rom_set_rf_freq_offset, ~0.27 ms, no recalibration); no keying.
 *                              Afterwards TONE/ALT (tone offset f=0 is the LO) are capped at 150 ms until
 *                              RETUNE 2412000 restores the boot LO. Refused while keyed.
 *   FOFS hz                    signed LO offset (|hz|<=200000, default 0, RAM only) added to RETUNE and HOP retunes
 *   STICKS c1..c8              eight stick values in us (800..2200) for HOP packets (default 1500 each)
 *   HOP 0 pwr [timeout_ms]     continuous 47-channel hop (release); [bench] HOP n_slots [pwr]: (n<=940) stream D8 data packets, one per ~8.994 ms slot, on the identity's hop table
 *                              (d8_hop_table(start, step), entry 0 = 0; channel n = 2404 MHz + n*299.93 kHz), packet
 *                              counter (byte 4) +1 per packet, the identity's txid, byte-identical to host d8hop
 *                              build(counter_index=4). Per slot: retune, key, 208 bits, unkey (one
 *                              critical section), then WDT feed + UART poll; any UART byte aborts. LO is
 *                              restored to 2412 MHz afterwards. Reply:
 *                              K,hop,slots=N,late_max_us=X,retune_max_us=Y then OK. ERR -> unkeyed.
 *   TLM every [cap_us] [gain] [dec] [same] [stream] [ack]   telemetry listen for later LINKs (default off;
 *                              protocol/PROTOCOL.md): every Nth slot sends byte3=2, byte4=tid, then unkeys, retunes to the
 *                              listen channel and runs a 16 MS/s ring capture (tlm_cap.c), shipped as EV tlm + binary.
 *                              stream=0: int16 dump, blocking (LINK sends nothing for ~0.2 s). stream=1: int8 (bits=8,
 *                              sh=right shift) pushed into the UART FIFO between slots while LINK keeps its schedule; the
 *                              next trigger waits until the capture is out. ack=1: the id is not advanced by the
 *                              firmware; the host sends TID n after each capture (n = id+1 if the reply was received,
 *                              else the same id) and the next trigger waits for it (<=1 s, then resends the same id).
 *   TID n                      telemetry id for the next trigger (0..31). Silent during LINK; idle: sets the first id.
 *   TCAP khz [cap_us] [gain] [dec] [pwr]     one such capture; [bench] pwr>=0 keys one data packet first (release: receive-only).
 *   ID | ID new | ID XXXX start step   per-ESP identity (txid + hop table start/step, NVS; random on first boot)
 *   BIND [pwr]                 bind packets on hop channel 0 every slot until STOP or 30 s; pwr default PWR_MAX (protocol/PROTOCOL.md "Bind")
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
#include "nvs.h"
#include "esp_random.h"
#include "soc/soc.h"
#include "soc/rtc.h"
#include "hal/wdt_hal.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "cmd_parse.h"
#include "packet.h"
#include "line_in.h"
#include "tlm_cap.h"
#include "esp_rom_crc.h"

#define TONE0 0x600060b8u /* tone NCO: [27:0] f, bit18 enable, [17:10] -gain */
#define TONE_FINE 0x600050a8u /* low f bits when TONE0 bit29 set */
#define CYC_PER_US 240u
#define RX_GAIN 0x3ff5c02cu /* bits [30:24] forced gain code, bit 23 force (else hardware AGC), [14:8] max */

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

/* libphy's stop path (as txeng unkeys), then receive-only PBUS setup. Idempotent. */
static void unkey(void) {
    ((void (*)(int, int, int, int, int, int))g_phyFuns[68 / 4])(0, 0, 0, 0, 0, 0);
    ((void (*)(void))g_phyFuns[0x124 / 4])();
    rom_stop_tx_tone(1);
    rx_mode();
    keyed = false;
}

/* Key one D8 air frame (208 bits, hard 2-FSK at f=+-1) plus tail alternating 1,0,.. bits after the CRC (TLMX);
 * leaves the radio keyed. Caller holds the mux. */
static inline uint32_t cyc(void);
static void key_air(const uint8_t air[D8_AIR_BYTES], int pwr, unsigned tail) {
    keyed = true;
    key((air[0] & 0x80) ? 1 : -1, pwr);
    uint32_t t0 = cyc();
    const unsigned nb = D8_AIR_BITS + tail;
    for (unsigned i = 1; i < nb; i++) {
        uint32_t due = i * D8_BIT_CYCLES;
        int bit = i < D8_AIR_BITS ? (air[i >> 3] & (0x80u >> (i & 7))) != 0 : !((i - D8_AIR_BITS) & 1u);
        while ((int32_t)(cyc() - t0 - due) < 0) { }
        tone_set(bit ? 1 : -1);
    }
    while ((int32_t)(cyc() - t0 - nb * D8_BIT_CYCLES) < 0) { }
}

static inline uint32_t cyc(void) { return esp_cpu_get_cycle_count(); }

#if D8_BENCH /* TONE / ALT / PKT: fixed-channel bench modes, compiled out of the release build */
typedef struct { uint32_t due, actual, rb; } trans_t;
static trans_t trans[ALT_MAX_TRANS + 1];

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

#endif /* D8_BENCH: run_window */

#if D8_BENCH
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
#endif /* D8_BENCH: run_packet */

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
#define FW_ID "d8tx-v1"
#ifndef D8TX_FW_VER /* set by main/CMakeLists.txt: semver + hash of the firmware sources */
#define D8TX_FW_VER "0.0.0+unknown"
#endif

static bool v1_link; /* current run_hop was started by LINK (protocol v1 events/replies) */

/* ---- per-ESP identity (txid + hop table start/step), NVS namespace "d8tx" key "ident" (4-byte blob) ---- */
static d8_ident_t ident;
static uint32_t rnd32(void) { return esp_random(); }

static bool ident_store(const d8_ident_t *id) {
    nvs_handle_t h;
    if (nvs_open("d8tx", NVS_READWRITE, &h) != ESP_OK) return false;
    uint8_t b[4] = {id->id0, id->id1, id->start, id->step};
    bool ok = nvs_set_blob(h, "ident", b, sizeof b) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
    return ok;
}

/* Boot: stored identity if present and valid, else a new random one (stored). */
static void ident_load(void) {
    nvs_handle_t h;
    uint8_t b[4];
    size_t n = sizeof b;
    if (nvs_open("d8tx", NVS_READONLY, &h) == ESP_OK) {
        esp_err_t e = nvs_get_blob(h, "ident", b, &n);
        nvs_close(h);
        if (e == ESP_OK && n == sizeof b) {
            d8_ident_t id = {b[0], b[1], b[2], b[3]};
            if (d8_ident_valid(&id)) { ident = id; return; }
        }
    }
    d8_ident_generate(rnd32, &ident);
    ident_store(&ident);
}

static void print_ident(void) {
    printf("OK txid=%02x%02x start=%u step=%u\n", ident.id0, ident.id1, ident.start, ident.step);
}

/* ---- telemetry listen state (TLM / TCAP; off unless TLM every > 0 was sent) ---- */
static struct { unsigned every, cap_us, dec, skip_us; int gain, same, stream, ack, mark, retry, bits; } tlm = {0, TLM_CAP_US_DEF, TLM_DEC_DEF, 0, TLM_GAIN_DEF, 0, 0, 0, 0, 0, 8};
static unsigned tlm_tid, tlm_tid_init, tlm_n, gain_max = 127;
static bool tid_ready; /* ack mode: a TID arrived since the last capture */
static unsigned tlmx_tail, tlmx_settle; /* TLMX experiments: tail bits on trigger packets, unkey->listen retune wait */
static int tlmx_all;                    /* TLMX: tail on every LINK packet */
static int tlmx_probe;                  /* TLMX: one marked data packet + silent slot half-way between triggers */

/* Background shipping (TLM stream=1): header line, raw bytes, "\n", pushed into the UART TX FIFO with
 * uart_tx_chars (never blocks) from the LINK idle gaps. Nothing else may print while busy. */
static struct { char hdr[400]; unsigned hlen, blen, pos; const uint8_t *data; bool busy; } shp;
/* A finished capture waiting for its int8 conversion (~1.3 ms of CPU), done in the idle gap after the resume slot
 * so it never delays a packet. */
static struct { bool on; unsigned after_k, k, ch, tid, n_out, dec, skip, bits; uint32_t u0; unsigned phase, i, m, sh; int mean_i, mean_q; int32_t sum_i, sum_q;
                unsigned tries, nb, fit, sl, rt; int gap, pgap; } shp_pend;
#define GAP_NONE 99999 /* no previous slot within 3 slots */

static void ship_pump(void) {
    while (shp.busy) {
        const char *p;
        unsigned n;
        if (shp.pos < shp.hlen) { p = shp.hdr + shp.pos; n = shp.hlen - shp.pos; }
        else if (shp.pos < shp.hlen + shp.blen) { p = (const char *)shp.data + (shp.pos - shp.hlen); n = shp.hlen + shp.blen - shp.pos; }
        else { p = "\n"; n = 1; }
        int w = uart_tx_chars(UART_NUM_0, p, n);
        if (w <= 0) return;
        shp.pos += (unsigned)w;
        if (shp.pos >= shp.hlen + shp.blen + 1u) shp.busy = false;
    }
}

static void ship_finish(void) {
    while (shp.busy) { ship_pump(); feed(); }
    uart_wait_tx_done(UART_NUM_0, pdMS_TO_TICKS(1000));
}

/* Protocol v1 error line: ERR <code> <text>. */
static void print_err_v1(const char *why) {
    const char *code = err_code(why);
    const char *text = !strcmp(why, "busy") ? "link active" : !strcmp(why, "long") ? "line too long" :
                       !strcmp(why, "bench-only") ? "bench build required" : why;
    printf("ERR %s %s\n", code, text);
}

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
        if (c.kind == CMD_TID) { tlm_tid = c.tid; tid_ready = true; continue; }
        if (c.kind == CMD_STAT) {
            if (shp.busy) continue; /* a capture is going out: no text in the middle of it */
            printf("OK keyed=%d link=1 fofs=%d armok=%d bind=0\n", keyed, fofs_hz, arm_ok);
            fflush(stdout);
            continue;
        }
        *err = c.kind == CMD_ERR ? c.err : v1_link ? "busy" : "hop_busy";
        return 1;
    }
    return 0;
}

/* ---- telemetry listen: capture and shipping ---- */
/* Called with the mux held, right after the last air bit: unkey, retune to f10, set RX gain, capture.
 * Returns CCOUNT at unkey start (turnaround = r->start_cyc - return value). */
static uint32_t tlm_listen(uint32_t f10, int gain, unsigned n_out, unsigned dec, tcap_res_t *r) {
    uint32_t u0 = cyc();
    unkey();
    if (tlmx_settle) { uint32_t t = cyc(); while (cyc() - t < tlmx_settle * CYC_PER_US) { } }
    lo_retune(f10);
    uint32_t g = REG_READ(RX_GAIN);
    if (gain < 0) REG_WRITE(RX_GAIN, g & ~BIT(23));
    else REG_WRITE(RX_GAIN, (g & 0x7fffffu) | ((uint32_t)(gain > (int)gain_max ? (int)gain_max : gain) << 24) | BIT(23));
    tcap_run(n_out, dec, r);
    REG_WRITE(RX_GAIN, g);
    return u0;
}

/* EV tlm line, then exactly bytes= raw bytes (int16 LE I,Q interleaved; Q not negated), then "\n". */
static void tlm_dump(unsigned k, unsigned ch, unsigned tid, unsigned n_out, unsigned dec, uint32_t u0, const tcap_res_t *r) {
    const uint8_t *b = (const uint8_t *)tcap_buffer();
    unsigned bytes = 4u * n_out;
    uint32_t crc = esp_rom_crc32_le(0, b, bytes);
    uint32_t turn = r->start_cyc - u0;
    feed();
    printf("EV tlm k=%u ch=%u tid=%u fs=%u n=%u dec=%u turn_ns=%" PRIu32 " run_us=%" PRIu32 " g0=%" PRIu32 " g1=%" PRIu32
           " lost=%" PRIu32 " bad=%" PRIu32 " late=%" PRIu32 " work=%" PRIu32 " units=%" PRIu32 " to=%d bytes=%u crc=%08" PRIx32 "\n",
           k, ch, tid, TCAP_RATE_HZ / dec, n_out, dec, turn * 1000u / CYC_PER_US, (r->end_cyc - r->start_cyc) / CYC_PER_US,
           r->gain_first, r->gain_last, r->lost, r->bad, r->late_max, r->work_max, r->units, r->timeout, bytes, crc);
    fflush(stdout);
    uart_write_bytes(UART_NUM_0, b, bytes);
    uart_write_bytes(UART_NUM_0, "\n", 1);
    uart_wait_tx_done(UART_NUM_0, pdMS_TO_TICKS(1000));
    feed();
}

/* Stream mode: int16 capture -> int8 in place (common right shift sh so the peak fits), then queue header + bytes.
 * Done in chunks of 512 values (phase 0: peak scan, 1: convert) so it fits the ~1.9 ms idle gaps between packets.
 * Returns true when the capture has been queued for shipping. */
static bool tlm_ship_step(const tcap_res_t *r) {
    /* Ships samples skip..n_out-1 of the capture. bits=8: int8 with a common right shift; bits=4: mean removed, scaled to
     * +-7, I in the low nibble and Q in the high nibble of each byte. Conversion is in place (output never passes the input). */
    int16_t *s = tcap_buffer() + 2u * shp_pend.skip; /* first shipped value */
    int8_t *d = (int8_t *)tcap_buffer();
    const unsigned ns = shp_pend.n_out - shp_pend.skip; /* shipped samples */
    const unsigned n = shp_pend.bits == 4 ? ns : 2u * ns; /* shipped bytes */
    const unsigned nv = 2u * ns;
    unsigned i0 = shp_pend.i, e = i0 + 512u < nv ? i0 + 512u : nv;
    if (shp_pend.phase == 0) {
        for (unsigned i = i0; i < e; i++) {
            int v = s[i] < 0 ? -s[i] : s[i];
            if ((i & 1u) == 0) shp_pend.sum_i += s[i]; else shp_pend.sum_q += s[i];
            if ((unsigned)v > shp_pend.m) shp_pend.m = (unsigned)v;
        }
        shp_pend.i = e;
        if (e == nv) {
            shp_pend.sh = 0;
            if (shp_pend.bits == 4) {
                shp_pend.mean_i = (int)(shp_pend.sum_i / (int32_t)ns); shp_pend.mean_q = (int)(shp_pend.sum_q / (int32_t)ns);
                shp_pend.m = 0; /* peak of the mean-removed data: second pass */
                shp_pend.phase = 2;
            } else {
                while ((shp_pend.m >> shp_pend.sh) > 127u) shp_pend.sh++;
                shp_pend.phase = 1;
            }
            shp_pend.i = 0;
        }
        return false;
    }
    if (shp_pend.phase == 2) { /* bits=4: peak after mean removal */
        for (unsigned i = i0; i < e; i++) {
            int v = s[i] - ((i & 1u) ? shp_pend.mean_q : shp_pend.mean_i);
            if (v < 0) v = -v;
            if ((unsigned)v > shp_pend.m) shp_pend.m = (unsigned)v;
        }
        shp_pend.i = e;
        if (e == nv) { shp_pend.sum_i = (int32_t)((7u << 16) / (shp_pend.m ? shp_pend.m : 1u)); shp_pend.phase = 1; shp_pend.i = 0; }
        return false;
    }
    if (shp_pend.bits == 4) { /* i counts values; handle sample pairs */
        const int32_t mul = shp_pend.sum_i;
        for (unsigned i = i0; i < e; i += 2) {
            int qi = ((s[i] - shp_pend.mean_i) * mul + 32768) >> 16, qq = ((s[i + 1] - shp_pend.mean_q) * mul + 32768) >> 16;
            if (qi > 7) qi = 7; else if (qi < -7) qi = -7;
            if (qq > 7) qq = 7; else if (qq < -7) qq = -7;
            d[i / 2] = (int8_t)((qi & 0xf) | ((qq & 0xf) << 4));
        }
    } else {
        for (unsigned i = i0; i < e; i++) d[i] = (int8_t)(s[i] >> shp_pend.sh); /* byte i overwrites a value already read */
    }
    shp_pend.i = e;
    if (e < nv) return false;
    uint32_t crc = esp_rom_crc32_le(0, (const uint8_t *)d, n);
    uint32_t turn = r->start_cyc - shp_pend.u0;
    int h = snprintf(shp.hdr, sizeof shp.hdr, "EV tlm k=%u ch=%u tid=%u fs=%u n=%u dec=%u turn_ns=%" PRIu32 " run_us=%" PRIu32
                     " g0=%" PRIu32 " g1=%" PRIu32 " lost=%" PRIu32 " bad=%" PRIu32 " late=%" PRIu32 " work=%" PRIu32
                     " units=%" PRIu32 " to=%d bits=%u sh=%u try=%u nb=%u fit=%u sl=%u rt=%u gap=%d pgap=%d bytes=%u crc=%08" PRIx32 "\n",
                     shp_pend.k, shp_pend.ch, shp_pend.tid, TCAP_RATE_HZ / shp_pend.dec, ns, shp_pend.dec,
                     turn * 1000u / CYC_PER_US, (r->end_cyc - r->start_cyc) / CYC_PER_US, r->gain_first, r->gain_last, r->lost,
                     r->bad, r->late_max, r->work_max, r->units, r->timeout, shp_pend.bits, shp_pend.sh, shp_pend.tries, shp_pend.nb,
                     shp_pend.fit, shp_pend.sl, shp_pend.rt, shp_pend.gap, shp_pend.pgap, n, crc);
    shp.hlen = h < (int)sizeof shp.hdr ? (unsigned)h : sizeof shp.hdr - 1;
    shp.data = (const uint8_t *)d;
    shp.blen = n;
    shp.pos = 0;
    shp.busy = true;
    shp_pend.on = false;
    return true;
}

static void run_tcap(const cmd_t *c) {
    if (keyed) { print_err_v1("keyed"); return; }
    uint32_t f10 = (uint32_t)((int)c->khz * 100 + fofs_hz / 10);
    unsigned n_out = c->cap_us * 16u / c->dec;
    uint8_t body[D8_BODY_BYTES], air[D8_AIR_BYTES];
    d8_build_body(ident.id0, ident.id1, 0, sticks_raw, body);
    if (!d8_air_bytes(body, D8_BODY_BYTES, air)) { print_err_v1("packet"); return; }
    tcap_prepare(n_out);
    tcap_res_t r;
    feed();
    lo_retune(f10);
    portENTER_CRITICAL(&mux);
#if D8_BENCH
    if (c->pwr >= 0) key_air(air, c->pwr, 0); /* keyed capture: bench build only (the parser refuses it in release) */
#endif
    uint32_t u0 = tlm_listen(f10, c->gain, n_out, c->dec, &r); /* unkey() is idempotent when not keyed */
    portEXIT_CRITICAL(&mux);
    tlm_dump(0, c->khz, c->pwr >= 0 ? 1u : 0u, n_out, c->dec, u0, &r);
    lo_retune(241200000u);
    lo_off = false;
    printf("OK\n");
}

static void run_hop(const cmd_t *c) {
    uint8_t tab[D8_HOP_CHANNELS], body[D8_BODY_BYTES], air[D8_AIR_BYTES];
    d8_hop_table(ident.start, ident.step, tab);
    uint32_t late_max = 0, rt_max = 0;
    unsigned sent = 0;
    bool abort = false, abort_pkt = false;
    const bool cont = !D8_BENCH || c->kind == CMD_LINK || c->n_slots == 0; /* release: always continuous */
    const char *why = "done", *err = NULL;
    static line_in_t hli;
    hli.len = 0;
    v1_link = c->kind == CMD_LINK;
    const bool tlm_link = v1_link && tlm.every; /* TLM applies to LINK only */
    const unsigned n_out = tlm.cap_us * 16u / tlm.dec;
    tcap_res_t tr;
    tlm_tid = tlm_tid_init;
    tid_ready = true;
    unsigned next_trig = tlm.every;
    int64_t ack_t0 = 0;
    /* re-trigger (TLM retry>0): after an on-chip "no reply" verdict the next free slot repeats the request, same tid */
    unsigned tries = 0, n_trig = 0, n_retry = 0;
    bool retry_due = false;
    /* packet start timing: key start minus the previous key start minus the nominal slots in between (us) */
    uint32_t prev_kc = 0;
    unsigned prev_k = ~0u;
    int prev_gap = GAP_NONE, gap_max = -GAP_NONE, g2_max = -GAP_NONE, g2_min = GAP_NONE;
    unsigned gap_n50 = 0, gap_n100 = 0, gap_n200 = 0;
    unsigned probe_k = ~0u; /* TLMX probe: next probe slot (set half-way to the next trigger) */
    if (v1_link) { printf("OK\n"); fflush(stdout); }
    feed();
    int64_t last_s_us = esp_timer_get_time(), last_st_us = last_s_us;
    uint32_t base = cyc();
    uint32_t slot_start = base; /* scheduled start of the current slot */
    for (unsigned k = 0; (cont || k < c->n_slots) && !abort; k++) {
        const bool due = tlm.stream ? k >= next_trig && !shp.busy && !shp_pend.on : k >= tlm.every && k % tlm.every == 0;
        const bool trig = tlm_link && (retry_due || (due && (!tlm.ack || tid_ready || esp_timer_get_time() - ack_t0 > 1000000)));
        const bool probe = tlm_link && tlm.stream && tlmx_probe && !trig && k >= probe_k && !shp.busy;
        uint16_t raw[D8_STICKS];
        memcpy(raw, sticks_raw, sizeof raw);
        if (tlm_link && tlm.mark) /* ch8 marker, below every aux range */
            raw[7] = d8_us_to_raw(trig ? (retry_due ? 1600 : 1500) : probe ? 1400 : 1000);
        d8_build_body(ident.id0, ident.id1, (uint8_t)k, raw, body);
        if (trig) { d8_mark_telemetry(body, (uint8_t)tlm_tid); tcap_prepare(n_out); }
        if (!d8_air_bytes(body, D8_BODY_BYTES, air)) { printf("ERR packet\n"); abort = true; abort_pkt = true; why = "packet"; break; }
        uint32_t f10 = d8_channel_f10(tab[k % D8_HOP_CHANNELS]);
        while ((int32_t)(cyc() - slot_start) < 0) { /* wait for the slot (interrupts on) */
            if (shp_pend.on && !shp.busy && k >= shp_pend.after_k && (int32_t)(cyc() - slot_start) < -(int32_t)(400u * CYC_PER_US))
                tlm_ship_step(&tr);
            ship_pump();
            if (cont && hop_drain(&hli, &err, &last_s_us)) { abort = true; break; }
        }
        ship_pump();
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
        uint32_t kc = cyc();
        key_air(air, c->pwr, tlm_link && (trig || tlmx_all) ? tlmx_tail : 0);
        uint32_t u0 = 0;
        if (trig) u0 = tlm_listen(d8_channel_f10(tab[(k + (tlm.same ? 0 : 1)) % D8_HOP_CHANNELS]) + (uint32_t)(fofs_hz / 10),
                                  tlm.gain, n_out, tlm.dec, &tr);
        else unkey();
        portEXIT_CRITICAL(&mux);
        sent++;
        int gap = GAP_NONE;
        if (prev_k != ~0u && k - prev_k <= 3u)
            gap = (int)((int32_t)(kc - prev_kc - (k - prev_k) * HOP_SLOT_CYC)) / (int)CYC_PER_US;
        if (gap != GAP_NONE && k - prev_k == 1u) {
            if (gap > gap_max) gap_max = gap;
            int ag = gap < 0 ? -gap : gap;
            gap_n50 += ag > 50; gap_n100 += ag > 100; gap_n200 += ag > 200;
        } else if (gap != GAP_NONE && k - prev_k == 2u) { /* first slot after a listen slot */
            if (gap > g2_max) g2_max = gap;
            if (gap < g2_min) g2_min = gap;
        }
        const int pgap = prev_gap;
        prev_gap = gap; prev_kc = kc; prev_k = k;
        if (probe) { /* a line for the host, then leave slot k+1 silent like a listen slot */
            int h = snprintf(shp.hdr, sizeof shp.hdr, "EV probe k=%u ch=%u gap=%d pgap=%d", k, tab[k % D8_HOP_CHANNELS], gap, pgap);
            shp.hlen = h < (int)sizeof shp.hdr ? (unsigned)h : sizeof shp.hdr - 1;
            shp.data = NULL; shp.blen = 0; shp.pos = 0; shp.busy = true;
            probe_k = ~0u;
            slot_start += 2u * HOP_SLOT_CYC;
            k++;
            continue;
        }
        if (trig && tlm.stream) { /* resume at the first future slot >= k+2 (k+1 was the listen slot); the capture
                                   * goes out in the background from the following idle gaps */
            uint32_t next = slot_start + 2u * HOP_SLOT_CYC;
            unsigned j = k + 2;
            while ((int32_t)(cyc() - next) >= 0) { next += HOP_SLOT_CYC; j++; }
            unsigned lch = tab[(k + (tlm.same ? 0 : 1)) % D8_HOP_CHANNELS];
            unsigned fit, nb = d8_reply_blocks(tcap_buffer(), n_out, tlm.dec, &fit);
            n_trig++;
            if (!d8_reply_seen(nb, fit) && tries < (unsigned)tlm.retry) {
                /* no reply energy: drop this capture (one short line instead) and repeat the request at slot j */
                if (!shp.busy) {
                    int h = snprintf(shp.hdr, sizeof shp.hdr, "EV tlm_drop k=%u ch=%u tid=%u try=%u nb=%u fit=%u sl=%" PRIu32
                                     " rt=%" PRIu32 " gap=%d pgap=%d", k, lch, tlm_tid, tries, nb, fit, late / CYC_PER_US,
                                     r1 / CYC_PER_US, gap, pgap);
                    shp.hlen = h < (int)sizeof shp.hdr ? (unsigned)h : sizeof shp.hdr - 1;
                    shp.data = NULL; shp.blen = 0; shp.pos = 0; shp.busy = true; /* ship_pump adds the "\n" */
                }
                tries++; n_retry++;
                retry_due = true;
                slot_start = next;
                k = j - 1; /* loop ++ */
                continue;
            }
            shp_pend.tries = tries; shp_pend.nb = nb; shp_pend.fit = fit; shp_pend.sl = late / CYC_PER_US;
            shp_pend.rt = r1 / CYC_PER_US; shp_pend.gap = gap; shp_pend.pgap = pgap;
            tries = 0; retry_due = false;
            shp_pend.on = true; shp_pend.after_k = j + 1; shp_pend.k = k; shp_pend.ch = lch; shp_pend.tid = tlm_tid;
            shp_pend.n_out = n_out; shp_pend.dec = tlm.dec; shp_pend.u0 = u0;
            shp_pend.skip = tlm.skip_us * 16u / tlm.dec; shp_pend.bits = (unsigned)tlm.bits;
            shp_pend.phase = 0; shp_pend.i = 0; shp_pend.m = 0; shp_pend.sum_i = shp_pend.sum_q = 0;
            if (!tlm.ack) tlm_tid = (tlm_tid + 1u) & 0x1fu;
            tid_ready = false;
            ack_t0 = esp_timer_get_time();
            tlm_n++;
            next_trig = k + tlm.every;
            probe_k = k + tlm.every / 2u;
            slot_start = next;
            k = j - 1; /* loop ++ */
            continue;
        }
        if (trig) { /* ship the capture, then resume at the first future slot >= k+2 (k+1 was the listen slot) */
            unsigned lch = tab[(k + (tlm.same ? 0 : 1)) % D8_HOP_CHANNELS];
            tlm_dump(k, lch, tlm_tid, n_out, tlm.dec, u0, &tr);
            if (!tlm.ack) tlm_tid = (tlm_tid + 1u) & 0x1fu;
            tid_ready = false;
            ack_t0 = esp_timer_get_time();
            tlm_n++;
            if (hop_drain(&hli, &err, &last_s_us)) { abort = true; why = err ? "err" : "stop"; break; }
            uint32_t next = slot_start + 2u * HOP_SLOT_CYC;
            unsigned j = k + 2;
            while ((int32_t)(cyc() - next) >= 0) { next += HOP_SLOT_CYC; j++; }
            slot_start = next;
            k = j - 1; /* loop ++ */
            continue;
        }
        slot_start += HOP_SLOT_CYC;
        if (cont) {
            int64_t now = esp_timer_get_time();
            if (now - last_st_us >= 1000000 && !shp.busy) { /* <=1 short status line per second */
                last_st_us = now;
                if (v1_link) printf("EV link slots=%u late_max_us=%" PRIu32 "\n", sent, late_max / CYC_PER_US);
                else printf("K,hop,s=%u\n", sent);
            }
        } else {
            uint8_t b;
            if (uart_read_bytes(UART_NUM_0, &b, 1, 0) == 1) { abort = true; why = "byte"; }
        }
    }
    if (keyed) unkey();
    while (shp_pend.on) { /* LINK ended before the capture went out */
        while (shp.busy) { ship_pump(); feed(); }
        tlm_ship_step(&tr);
    }
    ship_finish();
    lo_retune(241200000u); /* 2412 MHz = 241,200,000 x 10 Hz */
    lo_off = false;
    if (v1_link) {
        const char *w = err || abort_pkt ? "err" : !strcmp(why, "timeout") ? "timeout" : "stop";
        printf("EV link_end why=%s slots=%u late_max_us=%" PRIu32 " retune_max_us=%" PRIu32 " gap_max_us=%d gap50=%u"
               " gap100=%u gap200=%u g2_min_us=%d g2_max_us=%d trig=%u retry=%u\n", w, sent, late_max / CYC_PER_US,
               rt_max / CYC_PER_US, gap_max, gap_n50, gap_n100, gap_n200, g2_min, g2_max, n_trig, n_retry);
        if (err) print_err_v1(err);
        else if (!strcmp(w, "stop")) printf("OK\n");
        v1_link = false;
        return;
    }
    if (err) printf("ERR %s\n", err);
    printf("K,hop,slots=%u,late_max_us=%" PRIu32 ",retune_max_us=%" PRIu32 ",why=%s\nOK\n", sent,
           late_max / CYC_PER_US, rt_max / CYC_PER_US, why);
}

static void print_info(void) {
    printf("OK proto=1 fw=" FW_ID " slot_us=8994 channels=%u pwr_max=%d fofs_max_hz=%d timeout_max_ms=%d txid=%02x%02x ver=" D8TX_FW_VER " bench=%d\n",
           (unsigned)D8_HOP_CHANNELS, PWR_MAX, FOFS_HZ_MAX, HOP_TIMEOUT_MAX_MS, ident.id0, ident.id1, D8_BENCH);
}

/* BIND: one bind packet per 8994 us slot on hop channel 0 (+ FOFS), idx 0,5,..,45 cycling (Multiprotocol FrSkyD
 * bind phase), until STOP/U or BIND_TIMEOUT_MS. Every other request still gets its one reply: PING/INFO/STAT/S are
 * answered, anything else is ERR busy (the bind keeps running). */
static void run_bind(const cmd_t *c) {
    uint8_t tab[D8_HOP_CHANNELS], body[D8_BODY_BYTES], air[D8_AIR_BYTES];
    d8_hop_table(ident.start, ident.step, tab);
    const uint32_t f10 = d8_channel_f10(0) + (uint32_t)(fofs_hz / 10);
    static line_in_t bli;
    bli.len = 0;
    bool stop = false;
    unsigned sent = 0, idx = 0;
    printf("OK\n");
    fflush(stdout);
    feed();
    const int64_t t_start = esp_timer_get_time();
    uint32_t slot_start = cyc();
    while (!stop) {
        d8_build_bind(ident.id0, ident.id1, idx, tab, body);
        if (!d8_air_bytes(body, D8_BODY_BYTES, air)) break;
        while (!stop && (int32_t)(cyc() - slot_start) < 0) { /* wait for the slot, answering requests */
            uint8_t b;
            if (uart_read_bytes(UART_NUM_0, &b, 1, 0) != 1) continue;
            if (b != '\n' && b != '\r') {
                if (bli.len < sizeof bli.buf - 1) bli.buf[bli.len++] = (char)b;
                else bli.len = sizeof bli.buf;
                continue;
            }
            if (!bli.len) continue;
            int over = bli.len >= sizeof bli.buf;
            bli.buf[over ? 0 : bli.len] = 0;
            bli.len = 0;
            if (over) { print_err_v1("long"); fflush(stdout); continue; }
            cmd_t r = cmd_parse(bli.buf);
            switch (r.kind) {
            case CMD_NONE: break;
            case CMD_UNKEY: stop = true; break;
            case CMD_PING: printf("OK proto=1\n"); break;
            case CMD_INFO: print_info(); break;
            case CMD_STAT: printf("OK keyed=%d link=0 fofs=%d armok=%d bind=1\n", keyed, fofs_hz, arm_ok); break;
            case CMD_S:
                for (unsigned i = 0; i < D8_STICKS; i++) sticks_raw[i] = d8_us_to_raw(i == 6 ? ch7_gate(r.sticks[i]) : r.sticks[i]);
                printf("OK\n");
                break;
            case CMD_ERR: print_err_v1(r.err); break;
            default: printf("ERR busy binding\n"); break;
            }
            fflush(stdout);
        }
        if (stop) break;
        if (esp_timer_get_time() - t_start > (int64_t)BIND_TIMEOUT_MS * 1000) break;
        if (cyc() - slot_start > HOP_SLOT_CYC) slot_start = cyc(); /* overran a whole slot: resync */
        feed();
        portENTER_CRITICAL(&mux);
        lo_retune(f10);
        key_air(air, c->pwr, 0);
        unkey();
        portEXIT_CRITICAL(&mux);
        sent++;
        idx = idx >= D8_BIND_IDX_MAX ? 0 : idx + D8_BIND_IDX_STEP;
        slot_start += HOP_SLOT_CYC;
    }
    if (keyed) unkey();
    lo_retune(241200000u);
    lo_off = false;
    printf("EV bind_end why=%s slots=%u\n", stop ? "stop" : "timeout", sent);
    if (stop) printf("OK\n");
}

/* Bounded 10 ms read straight from the UART driver (not stdin): returns -1 when idle. */
static int rd_byte(void *ctx) {
    (void)ctx;
    uint8_t b;
    return uart_read_bytes(UART_NUM_0, &b, 1, pdMS_TO_TICKS(10)) == 1 ? b : -1;
}
static void feed_cb(void *ctx) { (void)ctx; feed(); }

void app_main(void) {
    printf("\nEV boot reason=%d\n", (int)esp_reset_reason());
    fflush(stdout);
    phy_up();
    ident_load();
    rom_stop_tx_tone(1); /* tone enable off: RF-silent regardless of prior state */
    gain_max = (REG_READ(RX_GAIN) >> 8) & 127;
    vTaskDelay(pdMS_TO_TICKS(100));
    uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0);
    uart_vfs_dev_use_driver(UART_NUM_0); /* stdout only; input is polled via uart_read_bytes */
    rwdt_start();
    static line_in_t li;
    for (;;) {
        line_res_t r = line_poll(&li, rd_byte, feed_cb, NULL);
        if (r == LINE_NONE) continue;
        if (r == LINE_LONG) { print_err_v1("long"); fflush(stdout); continue; }
        char *line = li.buf;
        cmd_t c = cmd_parse(line);
        switch (c.kind) {
        case CMD_NONE: break;
        case CMD_ERR:
            if (keyed) unkey();
            if (c.legacy) printf("ERR %s\n", c.err); else print_err_v1(c.err);
            break;
        case CMD_PING: printf("OK proto=1\n"); break;
        case CMD_INFO:
            print_info();
            break;
        case CMD_STAT:
            printf("OK keyed=%d link=0 fofs=%d armok=%d bind=0\n", keyed, fofs_hz, arm_ok);
            break;
        case CMD_UNKEY: unkey(); printf("OK\n"); break;
#if D8_BENCH
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
#endif
        case CMD_STICKS:
        case CMD_S:
            for (unsigned i = 0; i < D8_STICKS; i++)
                sticks_raw[i] = d8_us_to_raw(i == 6 && c.sticks[i] > S_CH7_US_MAX ? S_CH7_US_MAX : c.sticks[i]);
            printf("OK\n");
            break;
        case CMD_FOFS: fofs_hz = c.hz; printf("OK\n"); break;
        case CMD_ARMOK: arm_ok = true; printf("OK\n"); break;
        case CMD_HOP:
        case CMD_LINK:
            if (keyed) { if (c.kind == CMD_LINK) print_err_v1("keyed"); else printf("ERR keyed\n"); break; }
            run_hop(&c);
            arm_ok = false;
            for (unsigned i = 0; i < D8_STICKS; i++) /* never leave ARM high in stored sticks */
                if (i == 6 && sticks_raw[i] > d8_us_to_raw(S_CH7_US_MAX)) sticks_raw[i] = d8_us_to_raw(1000);
            break;
#if D8_BENCH
        case CMD_PKT: run_packet(&c); break;
#endif
        case CMD_TLM:
            tlm.every = c.tlm_every; tlm.cap_us = c.cap_us; tlm.gain = c.gain; tlm.dec = c.dec; tlm.same = c.same;
            tlm.stream = c.stream; tlm.ack = c.ack; tlm.mark = c.mark; tlm.retry = c.retry; tlm.skip_us = c.skip_us; tlm.bits = c.bits;
            printf("OK every=%u cap_us=%u gain=%d dec=%u same=%d stream=%d ack=%d mark=%d retry=%d n=%u gain_max=%u skip=%u bits=%d\n", tlm.every,
                   tlm.cap_us, tlm.gain, tlm.dec, tlm.same, tlm.stream, tlm.ack, tlm.mark, tlm.retry, tlm.cap_us * 16u / tlm.dec,
                   gain_max, tlm.skip_us, tlm.bits);
            break;
        case CMD_TID: tlm_tid_init = c.tid; printf("OK tid=%u\n", c.tid); break;
        case CMD_TLMX:
            tlmx_tail = c.tail_bits; tlmx_settle = c.settle_us; tlmx_all = c.tail_all; tlmx_probe = c.probe;
            printf("OK tail=%u settle=%u all=%d probe=%d\n", tlmx_tail, tlmx_settle, tlmx_all, tlmx_probe);
            break;
        case CMD_TCAP: run_tcap(&c); break;
        case CMD_ID:
            if (c.id_op == ID_GET) { print_ident(); break; }
            if (c.id_op == ID_NEW) d8_ident_generate(rnd32, &c.ident);
            if (!ident_store(&c.ident)) { printf("ERR range nvs write failed\n"); break; }
            ident = c.ident;
            print_ident();
            break;
        case CMD_BIND:
            if (keyed) { print_err_v1("keyed"); break; }
            run_bind(&c);
            break;
        default: /* TONE/ALT/PKT/RETUNE in a release build: the parser already answered ERR bench-only */
            printf("ERR bench-only\n");
            break;
        }
        fflush(stdout);
    }
}
