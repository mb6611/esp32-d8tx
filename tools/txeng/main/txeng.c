/* Behavioural test of the candidate classic-ESP32 I/Q TX playback engine at
 * 0x60033d98 (DUMP_CTRL + 8; the register census found RW mask 0x8ff8bfff = the ESP32-S3 engine's).
 *
 * PHY bring-up is esp-sdr's ESP32 backend (as in the register census). The firmware is a line
 * command server on UART0 (921600); the host (run.py) drives the experiments.
 * The RTC WDT (about 3 s, reset-system) is fed in the command loop, so a hang reboots the
 * chip; the host sees "I,boot" in place of "OK" and records the command as a HANG.
 *
 * Commands (numbers accept 0x..):
 *   R a                 read word            -> V,a,val
 *   W a v               write word (refuses 0x60033d00..0x60033d20, which hang the chip)
 *   G m                 DPORT MAC_DUMP_MODE = m (0..3)
 *   F kind n p1 p2      fill sample memory (grant released while the CPU writes):
 *                         0: n words = p1 (rest untouched)    2: all 16384 words = sentinel
 *                         1: n words complex exp, amp p1, p2 cycles over n (I=cos,Q=sin, 10-bit)
 *                         3: n words I = p1*cos, Q = 0, p2 cycles
 *   C capctrl           capture DUMP_CTRL word for concurrent capture (flag CAP), 0 = none
 *   T ctrl reps tmo flags gmode pwr   (flags: 1 one-write, 2 no clear, 4 key, 8 clear tone
 *                       bit 18, 16 concurrent capture, 32 RX on after key, 64 DUMP_BYTES)
 *                       run the engine `reps` times: write ctrl&~run, then ctrl|run (one write if
 *                       flag ONEWRITE), poll bit 18 up to tmo us, write ctrl&~run (unless NOCLR).
 *                       gmode: MAC_DUMP_MODE during the run (0..3; 9 = leave). pwr: PBUS (5,1)
 *                       after keying (-1 = leave). Prints E (stats) and S (register snapshots).
 *   D off n             dump n sample words from word offset off -> X,off,w0,w1,... (16/line)
 *   P n clk             esp-sdr style capture of n samples (clk 0=16,1=80,2=40 MS/s) -> Pc,...
 *   B row col           read PBUS -> V,pbus,row,col,val (B alone: rows 0-7 x cols 0-3; some hang)
 *   K mode [gain]       keying method for T/M: 0 txcal_debuge_mode+tone (libphy wifiscwout),
 *                       1 rom_pbus_xpd_tx_on(pwr,288)+tone, 2 tone only; gain = forced RX gain for M
 *   M n half mode pwr   loopback positive control: key, capture n @40 MS/s while the CPU toggles
 *                       the tone register every `half` cycles (see cmd_modtest) -> Mc,...
 *   L ctrl capctrl nr gmode off   CPU-read timing of sample memory idle / engine / capture
 *   H off w0 w1 ...     write up to 14 hex sample words at word offset `off` (grant released while
 *                       the CPU writes) -> V,H,next_off; used to load a waveform
 *   Y ctrl count gap_ms pwr clr18   burst train for BLE trials: `count` (<=250) times: key (per K),
 *                       run the engine once (ctrl, timeout 1 ms), clear, unkey; `gap_ms` (>=20) between
 *                       bursts, so a trial is at most ~5 s with duty < 2%. Prints Y,ndone,count,total_us.
 *   Q [mhz]            select the RF channel: 2402 (BLE ch37) or 2412 (boot default, Wi-Fi ch1); no arg =
 *                       report only. Same retune path as esp-sdr's receiver.c tune_rx (set_chanfreq(2412), release
 *                       cap-code pin, rom_set_rf_freq_offset) minus its RX recalibration. Never keys TX; the next
 *                       key may or may not keep the setting (see README). -> V,freq,req,cap_reg,... Reset = 2412.
 * Every command ends with "OK" or "ERR <why>".
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_attr.h"
#include "esp_rom_sys.h"
#include "esp_cpu.h"
#include "nvs_flash.h"
#include "soc/soc.h"
#include "soc/rtc.h"
#include "soc/dport_reg.h"
#include "soc/dport_access.h"
#include "hal/wdt_hal.h"
#include "heap_memory_layout.h"
#include "esp_rom_serial_output.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"

SOC_RESERVE_MEMORY_REGION(0x3ffe8000, 0x3fff8000, txeng_rf_dump);

#define DUMP_CTRL   0x60033d90u
#define DUMP_STATUS 0x60033d94u
#define TXE         0x60033d98u
#define CAND2       0x60033dc0u
#define DUMP_BYTES  0x60033dc4u
#define TONE0       0x600060b8u /* classic start_tx_tone_step register; bit 18 = tone enable */
#define CAPACITY    16384u
#define SENTINEL    0xa55aa55au
#define RUN         BIT(31)
#define DONE        BIT(18)

enum { F_ONEWRITE = 1, F_NOCLR = 2, F_KEY = 4, F_CLR18 = 8, F_CAP = 16, F_RXON = 32, F_BYTES = 64, F_KREAD = 128 };

extern void rom_pbus_workmode(void);
extern void rom_pbus_xpd_rx_on(int);
extern void rom_pbus_xpd_tx_off(void);
extern void rom_pbus_xpd_tx_on(int, int);
extern void rom_set_rxclk_en(int);
extern void rom_start_tx_tone_step(int en, int f, int g, int en2, int f2, int g2);
extern void rom_stop_tx_tone(int which);
extern void rom_pbus_force_test(int row, int col, int val);
extern unsigned rom_pbus_rd(int row, int col);
extern void txcal_debuge_mode(int);

static uint32_t *const samples = (void *)0x3ffe8000;
static wdt_hal_context_t rwdt = RWDT_HAL_CONTEXT_DEFAULT();
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static uint32_t cap_ctrl;

/* Registers snapshotted around a run (never d00..d20). */
static const uint32_t snap_regs[] = {0x60033d80, 0x60033d84, 0x60033d88, 0x60033d8c, DUMP_CTRL,
                                     DUMP_STATUS, TXE,        0x60033db4, 0x60033db8, CAND2,
                                     0x60033dd0, 0x60033dd4,  TONE0};
#define NSNAP (sizeof snap_regs / sizeof snap_regs[0])

static void flush_out(void) { fflush(stdout); }

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

static void grant(unsigned m) {
    uint32_t v = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG) & ~DPORT_MAC_DUMP_MODE_M;
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, v | ((m & 3u) << DPORT_MAC_DUMP_MODE_S));
}

static bool forbidden(uint32_t a) { return a >= 0x60033d00u && a <= 0x60033d23u; }

static uint32_t iq10(int i, int q) { return ((uint32_t)i & 0x3ff) | (((uint32_t)q & 0x3ff) << 10); }

static void cmd_fill(unsigned kind, unsigned n, int p1, int p2) {
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    grant(0);
    if (n > CAPACITY) n = CAPACITY;
    if (kind == 2) {
        for (unsigned j = 0; j < CAPACITY; j++) samples[j] = SENTINEL;
    } else {
        for (unsigned j = 0; j < n; j++) {
            if (kind == 0) {
                samples[j] = (uint32_t)p1;
            } else {
                double ph = 2.0 * M_PI * (double)p2 * j / n;
                int i = (int)lrint(p1 * cos(ph));
                int q = kind == 1 ? (int)lrint(p1 * sin(ph)) : 0;
                samples[j] = iq10(i, q);
            }
        }
    }
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
}

/* Key the TX chain the way libphy's wifiscwout() does on the classic ESP32 (channel already
 * set): txcal_debuge_mode(0), then the tone generator via start_tx_tone_step. */
static unsigned key_mode; /* 0: txcal_debuge_mode + tone; 1: rom_pbus_xpd_tx_on + tone; 2: tone only */
static int rx_gain_force = -1; /* M test: force RX gain code (esp-sdr RX_GAIN bit 23), -1 = AGC */
#define RX_GAIN 0x3ff5c02cu

static void key(int pwr) {
    if (key_mode == 0) txcal_debuge_mode(0);
    else if (key_mode == 1) rom_pbus_xpd_tx_on(pwr >= 0 ? pwr : 127, 288);
    rom_start_tx_tone_step(1, 0, 127, 0, 0, 0);
    if (pwr >= 0 && key_mode == 0) rom_pbus_force_test(5, 1, pwr);
}

/* libphy's stop path (wifiscwout(0,..) in librftest.a, not linked here): tone off + the PHY's own restore), then esp-sdr's
 * receive-only PBUS setup again. */
extern void **g_phyFuns; /* libphy's function table (wifiscwout calls entries 68/4 and 0x124/4) */
static void unkey(void) {
    ((void (*)(int, int, int, int, int, int))g_phyFuns[68 / 4])(0, 0, 0, 0, 0, 0);
    ((void (*)(void))g_phyFuns[0x124 / 4])();
    rom_stop_tx_tone(1);
    rx_mode();
}

/* Channel select, from esp-sdr targets/esp32/receiver.c tune_rx(). Only 2402 and 2412 are accepted. */
extern void set_chanfreq(unsigned mhz, unsigned mode);
extern void rom_set_rf_freq_offset(unsigned crystal, unsigned mhz, int offset);
extern unsigned ram_chip_i2c_readReg(unsigned, unsigned, unsigned);
extern void ram_chip_i2c_writeReg(unsigned, unsigned, unsigned, unsigned);
static unsigned sel_mhz = 2412;

static void cmd_freq(int mhz) {
    if (mhz >= 0) {
        if (mhz != 2402 && mhz != 2412) { printf("ERR freq (2402|2412)\n"); return; }
        portENTER_CRITICAL(&mux);
        set_chanfreq(2412, 0); /* PHY entry point on a real channel first, as esp-sdr does */
        if (mhz == 2402) {
            unsigned xtal = rtc_clk_xtal_freq_get();
            unsigned cap = ram_chip_i2c_readReg(0x62, 1, 0);
            ram_chip_i2c_writeReg(0x62, 1, 0, cap & ~0x80u);
            rom_set_rf_freq_offset(xtal == 26 ? 1 : xtal == 24 ? 2 : 0, 2402, 0);
        }
        portEXIT_CRITICAL(&mux);
        sel_mhz = mhz;
    }
    /* Readback is indirect: requested value, xtal MHz, and the cap-code register (bit 7 = pinned). */
    printf("V,freq,%u,xtal=%u,cap_reg=%02x\nOK\n", sel_mhz, (unsigned)rtc_clk_xtal_freq_get(),
           ram_chip_i2c_readReg(0x62, 1, 0));
}

/* I: read-only BBPLL (I2C block 102, host 4) regs 10/11 and DPORT_WIFI_BB_CFG. No writes. */
static void cmd_dacclk(void) {
    portENTER_CRITICAL(&mux);
    unsigned r10 = ram_chip_i2c_readReg(102, 4, 10);
    unsigned r11 = ram_chip_i2c_readReg(102, 4, 11);
    portEXIT_CRITICAL(&mux);
    printf("V,bbpll,reg10=%02x,reg11=%02x,div_dac=%u,bbcfg=%08" PRIx32 "\nOK\n", r10 & 0xff, r11 & 0xff,
           r11 & 1u, REG_READ(0x3ff00024u));
}

/* F_KREAD: read-only keyed-state probes (five registers x five phases). */
static const uint32_t kr_regs[5] = {0x600060b8u, 0x600060bcu, 0x600060c4u, 0x600060a0u, 0x600050f0u};
static uint32_t kr[5][5];
static inline void kread(int ph) { for (int k = 0; k < 5; k++) kr[ph][k] = REG_READ(kr_regs[k]); }

static void print_snap(const char *tag, const uint32_t *v) {
    printf("S,%s", tag);
    for (unsigned k = 0; k < NSNAP; k++) printf(",%08" PRIx32, v[k]);
    printf("\n");
}

static void take_snap(uint32_t *v) {
    for (unsigned k = 0; k < NSNAP; k++) v[k] = REG_READ(snap_regs[k]);
}

#define MAXREP 256
static uint32_t t_done[MAXREP], t_start[MAXREP];

static void cmd_tx(uint32_t ctrl, unsigned reps, unsigned tmo_us, unsigned flags, unsigned gmode, int pwr) {
    if (reps < 1 || reps > MAXREP) { printf("ERR reps\n"); return; }
    if ((flags & F_KEY) && (uint64_t)reps * tmo_us > 1000) { printf("ERR keyed>1ms\n"); return; }
    uint32_t base = ctrl & ~RUN;
    uint32_t pre[NSNAP], mid[NSNAP], atdone[NSNAP], post[NSNAP];
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t bytes = REG_READ(DUMP_BYTES);
    const uint32_t tmo = tmo_us * 240u;
    unsigned ndone = 0;
    uint32_t first_done_ctrl = 0, after_clr = 0, tone_before = 0, tone_after = 0;
    unsigned pb41 = 0, pb51 = 0, pb11 = 0, pb12 = 0, pb01 = 0;
    int64_t tk0 = 0, tk1 = 0;
    uint32_t cap_res = 0, cap_stat = 0;
    int cap_cyc = -1;

    take_snap(pre);
    portENTER_CRITICAL(&mux);
    if (flags & F_KEY) {
        tk0 = esp_timer_get_time();
        key(pwr);
        tone_before = REG_READ(TONE0);
        if (flags & F_KREAD) kread(0);
        if (flags & F_CLR18) REG_CLR_BIT(TONE0, BIT(18));
        tone_after = REG_READ(TONE0);
        if (flags & F_KREAD) kread(1);
        if (flags & F_RXON) { rom_pbus_xpd_rx_on(1); rom_set_rxclk_en(1); }
        pb01 = rom_pbus_rd(0, 1); pb11 = rom_pbus_rd(1, 1); pb12 = rom_pbus_rd(1, 2);
        pb41 = rom_pbus_rd(4, 1); pb51 = rom_pbus_rd(5, 1);
    }
    if (gmode <= 3) grant(gmode);
    if (flags & F_BYTES) REG_WRITE(DUMP_BYTES, 0x03020100);
    if ((flags & F_CAP) && cap_ctrl) REG_WRITE(DUMP_CTRL, 0);
    for (unsigned r = 0; r < reps; r++) {
        if (!(flags & F_ONEWRITE)) REG_WRITE(TXE, base);
        uint32_t t0 = esp_cpu_get_cycle_count();
        REG_WRITE(TXE, base | RUN);
        uint32_t tc = 0;
        if (r == 0 && (flags & F_CAP) && cap_ctrl) {
            REG_WRITE(DUMP_CTRL, cap_ctrl | RUN);
            REG_SET_BIT(DUMP_CTRL, BIT(19));
            REG_CLR_BIT(DUMP_CTRL, BIT(19));
        }
        if (r == 0) { if (flags & F_KREAD) kread(2); take_snap(mid); }
        uint32_t v, t;
        do {
            v = REG_READ(TXE);
            t = esp_cpu_get_cycle_count() - t0;
        } while (!(v & DONE) && t < tmo);
        t_start[r] = t0;
        if (v & DONE) {
            ndone++;
            t_done[r] = t;
            if (r == 0) { first_done_ctrl = v; if (flags & F_KREAD) kread(3); take_snap(atdone); }
        } else {
            t_done[r] = UINT32_MAX;
            if (r == 0) { first_done_ctrl = v; take_snap(atdone); }
        }
        if (r == 0 && (flags & F_CAP) && cap_ctrl) {
            /* wait for the capture too */
            uint32_t c0 = esp_cpu_get_cycle_count();
            while (!(REG_READ(DUMP_CTRL) & DONE) && (tc = esp_cpu_get_cycle_count() - c0) < tmo) {}
            cap_res = REG_READ(DUMP_CTRL);
            cap_stat = REG_READ(DUMP_STATUS);
            cap_cyc = (cap_res & DONE) ? (int)tc : -1;
            REG_WRITE(DUMP_CTRL, 0);
        }
        if (!(flags & F_NOCLR)) REG_WRITE(TXE, base);
        if (r == 0) after_clr = REG_READ(TXE);
    }
    REG_WRITE(TXE, 0);
    if (flags & F_KEY) { unkey(); tk1 = esp_timer_get_time(); if (flags & F_KREAD) kread(4); }
    esp_rom_delay_us(10);
    if (flags & F_BYTES) REG_WRITE(DUMP_BYTES, bytes);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    portEXIT_CRITICAL(&mux);
    take_snap(post);

    /* stats over reps that completed (cycles from run write to done seen) */
    uint32_t mn = UINT32_MAX, mx = 0;
    uint64_t sum = 0;
    for (unsigned r = 0; r < reps; r++)
        if (t_done[r] != UINT32_MAX) {
            if (t_done[r] < mn) mn = t_done[r];
            if (t_done[r] > mx) mx = t_done[r];
            sum += t_done[r];
        }
    /* start-to-start period between consecutive reps */
    uint32_t pmn = UINT32_MAX, pmx = 0;
    uint64_t psum = 0;
    for (unsigned r = 1; r < reps; r++) {
        uint32_t p = t_start[r] - t_start[r - 1];
        if (p < pmn) pmn = p;
        if (p > pmx) pmx = p;
        psum += p;
    }
    printf("E,%08" PRIx32 ",%u,%u,%u,%u,%" PRIu32 ",%" PRIu32 ",%" PRIu64 ",%08" PRIx32 ",%08" PRIx32
           ",%" PRIu32 ",%" PRIu32 ",%" PRIu64 ",%08" PRIx32 ",%08" PRIx32 ",%" PRId64
           ",%u,%u,%u,%u,%u,%08" PRIx32 ",%08" PRIx32 ",%d\n",
           ctrl, reps, flags, gmode, ndone, ndone ? mn : 0, ndone ? mx : 0, ndone ? sum / ndone : 0,
           first_done_ctrl, after_clr, reps > 1 ? pmn : 0, reps > 1 ? pmx : 0,
           reps > 1 ? psum / (reps - 1) : 0, tone_before, tone_after, tk1 - tk0, pb01, pb11, pb12, pb41,
           pb51, cap_res, cap_stat, cap_cyc);
    print_snap("pre", pre);
    print_snap("mid", mid);
    print_snap("done", atdone);
    print_snap("post", post);
    if ((flags & F_KEY) && (flags & F_KREAD))
        for (int p = 0; p < 5; p++) {
            printf("K,%d", p);
            for (int k = 0; k < 5; k++) printf(",%08" PRIx32, kr[p][k]);
            printf("\n");
        }
    printf("OK\n");
}

static void cmd_dump(unsigned off, unsigned n) {
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    grant(0);
    if (off >= CAPACITY) off = CAPACITY;
    if (off + n > CAPACITY) n = CAPACITY - off;
    for (unsigned j = 0; j < n; j += 16) {
        printf("X,%u", off + j);
        for (unsigned k = j; k < j + 16 && k < n; k++) printf(",%08" PRIx32, samples[off + k]);
        printf("\n");
        if ((j & 1023) == 0) feed();
    }
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    printf("OK\n");
}

/* esp-sdr acquire_iq. */
static void cmd_cap(unsigned n, unsigned clk) {
    if (n < 1 || n > CAPACITY - 4 || clk > 2) { printf("ERR args\n"); return; }
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t bytes = REG_READ(DUMP_BYTES);
    REG_WRITE(DUMP_CTRL, 0);
    grant(0);
    for (unsigned j = 0; j < CAPACITY; j++) samples[j] = SENTINEL;
    portENTER_CRITICAL(&mux);
    grant(3);
    REG_WRITE(DUMP_BYTES, 0x03020100);
    uint32_t ctrl = n | ((clk == 0) << 16) | ((clk == 2) << 15);
    REG_WRITE(DUMP_CTRL, ctrl | RUN);
    uint32_t t0 = esp_cpu_get_cycle_count(), t = 0;
    REG_SET_BIT(DUMP_CTRL, BIT(19));
    REG_CLR_BIT(DUMP_CTRL, BIT(19));
    while (!(REG_READ(DUMP_CTRL) & DONE) && (t = esp_cpu_get_cycle_count() - t0) < 240u * 20000u) {}
    uint32_t r = REG_READ(DUMP_CTRL), s = REG_READ(DUMP_STATUS);
    REG_WRITE(DUMP_CTRL, 0);
    esp_rom_delay_us(10);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    REG_WRITE(DUMP_BYTES, bytes);
    portEXIT_CRITICAL(&mux);
    unsigned written = 0;
    for (unsigned j = 0; j < CAPACITY; j++) written += samples[j] != SENTINEL;
    printf("Pc,%08" PRIx32 ",%08" PRIx32 ",%u,%" PRIu32 "\nOK\n", r, s, written, t);
}

/* Bus-contention probe: time `nr` CPU reads of sample memory (word offset off, stride 1) while
 * (a) idle, (b) the TX engine runs `ctrl`, (c) a capture runs `capctrl` (positive control).
 * -> Lc,<idle>,<engine>,<capture>,<engine_done>,<cap_done>,<first words read idle/engine> */
static uint32_t time_reads(unsigned off, unsigned nr, uint32_t *x) {
    volatile uint32_t *p = samples + off;
    uint32_t acc = 0, t0 = esp_cpu_get_cycle_count();
    for (unsigned j = 0; j < nr; j++) acc ^= p[j];
    *x = acc;
    return esp_cpu_get_cycle_count() - t0;
}

static void cmd_contention(uint32_t ctrl, uint32_t capctrl, unsigned nr, unsigned gmode, unsigned off) {
    if (nr > 4096 || off + nr > CAPACITY) { printf("ERR args\n"); return; }
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t bytes = REG_READ(DUMP_BYTES);
    uint32_t xi, xe, xc, ti, te, tc, de, dc;
    portENTER_CRITICAL(&mux);
    grant(gmode);
    REG_WRITE(DUMP_BYTES, 0x03020100);
    ti = time_reads(off, nr, &xi);
    REG_WRITE(TXE, ctrl & ~RUN);
    REG_WRITE(TXE, ctrl | RUN);
    te = time_reads(off, nr, &xe);
    de = REG_READ(TXE);
    uint32_t t0 = esp_cpu_get_cycle_count();
    while (!(REG_READ(TXE) & DONE) && esp_cpu_get_cycle_count() - t0 < 240u * 2000u) {}
    REG_WRITE(TXE, 0);
    REG_WRITE(DUMP_CTRL, 0);
    REG_WRITE(DUMP_CTRL, capctrl | RUN);
    REG_SET_BIT(DUMP_CTRL, BIT(19));
    REG_CLR_BIT(DUMP_CTRL, BIT(19));
    tc = time_reads(off, nr, &xc);
    dc = REG_READ(DUMP_CTRL);
    t0 = esp_cpu_get_cycle_count();
    while (!(REG_READ(DUMP_CTRL) & DONE) && esp_cpu_get_cycle_count() - t0 < 240u * 2000u) {}
    REG_WRITE(DUMP_CTRL, 0);
    esp_rom_delay_us(10);
    REG_WRITE(DUMP_BYTES, bytes);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    portEXIT_CRITICAL(&mux);
    printf("Lc,%" PRIu32 ",%" PRIu32 ",%" PRIu32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32
           ",%08" PRIx32 "\nOK\n", ti, te, tc, de, dc, xi, xe, xc);
}

/* Self-loopback positive control: key, RX on, capture n samples at 40 MS/s while the CPU
 * toggles TONE0 every `half` CPU cycles (mode 0: bit 18; 1: field [17:10] 0x81<->0xff;
 * 2: field [9:0] 0 <-> 0x1ff; 3: no toggle), unkey. Then D dumps the capture.
 * -> Mc,<cap ctrl>,<status>,<toggles>,<keyed_us>,<tone0 a>,<tone0 b> */
static void cmd_modtest(unsigned n, unsigned half, unsigned mode, int pwr) {
    if (n < 256 || n > 8192 || half < 24) { printf("ERR args\n"); return; }
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t bytes = REG_READ(DUMP_BYTES);
    REG_WRITE(DUMP_CTRL, 0);
    grant(0);
    for (unsigned j = 0; j < CAPACITY; j++) samples[j] = SENTINEL;
    portENTER_CRITICAL(&mux);
    int64_t tk0 = esp_timer_get_time();
    key(pwr);
    rom_pbus_xpd_rx_on(1);
    rom_set_rxclk_en(1);
    uint32_t gain_saved = REG_READ(RX_GAIN);
    if (rx_gain_force >= 0) REG_WRITE(RX_GAIN, (gain_saved & 0x7fffff) | ((uint32_t)rx_gain_force << 24) | BIT(23));
    uint32_t v = REG_READ(TONE0), a = v, b = v;
    if (mode == 0) { a = v | BIT(18); b = v & ~BIT(18); }
    else if (mode == 1) { a = (v & ~(0xffu << 10)) | (0x81u << 10); b = (v & ~(0xffu << 10)) | (0xffu << 10); }
    else if (mode == 2) { a = v & ~0x3ffu; b = (v & ~0x3ffu) | 0x1ff; }
    grant(3);
    REG_WRITE(DUMP_BYTES, 0x03020100);
    REG_WRITE(DUMP_CTRL, n | BIT(15) | RUN);
    REG_SET_BIT(DUMP_CTRL, BIT(19));
    REG_CLR_BIT(DUMP_CTRL, BIT(19));
    uint32_t t0 = esp_cpu_get_cycle_count(), next = half, toggles = 0;
    bool ph = false;
    while (!(REG_READ(DUMP_CTRL) & DONE) && esp_cpu_get_cycle_count() - t0 < 240u * 400u) {
        if (mode < 3 && esp_cpu_get_cycle_count() - t0 >= next) {
            REG_WRITE(TONE0, ph ? a : b);
            ph = !ph;
            next += half;
            toggles++;
        }
    }
    uint32_t r = REG_READ(DUMP_CTRL), s = REG_READ(DUMP_STATUS);
    REG_WRITE(DUMP_CTRL, 0);
    REG_WRITE(RX_GAIN, gain_saved);
    unkey();
    int64_t tk1 = esp_timer_get_time();
    esp_rom_delay_us(10);
    REG_WRITE(DUMP_BYTES, bytes);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    portEXIT_CRITICAL(&mux);
    printf("Mc,%08" PRIx32 ",%08" PRIx32 ",%" PRIu32 ",%" PRId64 ",%08" PRIx32 ",%08" PRIx32 "\nOK\n", r, s,
           toggles, tk1 - tk0, a, b);
}

static void cmd_load(unsigned off, char **save) {
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    grant(0);
    char *t;
    unsigned n = 0;
    while ((t = strtok_r(NULL, " \t", save)) && off < CAPACITY) { samples[off++] = (uint32_t)strtoul(t, NULL, 16); n++; }
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    printf("V,H,%u,%u\nOK\n", off, n);
}

static void cmd_train(uint32_t ctrl, unsigned count, unsigned gap_ms, int pwr, unsigned clr18) {
    if (count < 1 || count > 250 || gap_ms < 20 || gap_ms > 1000) { printf("ERR train limits\n"); return; }
    uint32_t base = ctrl & ~RUN;
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    unsigned ndone = 0;
    int64_t t0 = esp_timer_get_time();
    for (unsigned i = 0; i < count; i++) {
        feed();
        portENTER_CRITICAL(&mux);
        key(pwr);
        if (clr18) REG_CLR_BIT(TONE0, BIT(18));
        grant(0);
        REG_WRITE(TXE, base);
        uint32_t c0 = esp_cpu_get_cycle_count();
        REG_WRITE(TXE, base | RUN);
        while (!(REG_READ(TXE) & DONE) && esp_cpu_get_cycle_count() - c0 < 1000u * 240u) {}
        if (REG_READ(TXE) & DONE) ndone++;
        REG_WRITE(TXE, base);
        REG_WRITE(TXE, 0);
        unkey();
        DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
        portEXIT_CRITICAL(&mux);
        vTaskDelay(pdMS_TO_TICKS(gap_ms));
    }
    printf("Y,%u,%u,%" PRId64 "\nOK\n", ndone, count, esp_timer_get_time() - t0);
}

static unsigned long arg(char **p) {
    char *t = strtok_r(NULL, " \t", p);
    return t ? strtoul(t, NULL, 0) : 0;
}

void app_main(void) {
    printf("\nI,boot,reason=%d\n", (int)esp_reset_reason());
    flush_out();
    phy_up();
    vTaskDelay(pdMS_TO_TICKS(100));
    uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0);
    uart_vfs_dev_use_driver(UART_NUM_0);
    setvbuf(stdin, NULL, _IONBF, 0);
    rwdt_start();
    printf("I,ready,ahb_sel=%08" PRIx32 " txe=%08" PRIx32 " tone0=%08" PRIx32 "\n",
           DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG), REG_READ(TXE), REG_READ(TONE0));
    flush_out();
    char line[160];
    size_t len = 0;
    for (;;) {
        feed();
        int c = fgetc(stdin);
        if (c == EOF) { vTaskDelay(1); continue; }
        if (c != '\n' && c != '\r') {
            if (len < sizeof line - 1) line[len++] = (char)c;
            continue;
        }
        if (!len) continue;
        line[len] = 0;
        len = 0;
        char *save, *op = strtok_r(line, " \t", &save);
        if (!op) continue;
        if (!strcmp(op, "R")) {
            uint32_t a = arg(&save);
            if (forbidden(a) || (a & 3)) printf("ERR addr\n");
            else printf("V,%08" PRIx32 ",%08" PRIx32 "\nOK\n", a, REG_READ(a));
        } else if (!strcmp(op, "W")) {
            uint32_t a = arg(&save), v = arg(&save);
            if (forbidden(a) || (a & 3)) printf("ERR addr\n");
            else { REG_WRITE(a, v); printf("V,%08" PRIx32 ",%08" PRIx32 "\nOK\n", a, REG_READ(a)); }
        } else if (!strcmp(op, "G")) {
            grant(arg(&save));
            printf("V,ahb_sel,%08" PRIx32 "\nOK\n", DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG));
        } else if (!strcmp(op, "F")) {
            unsigned k = arg(&save), n = arg(&save);
            int p1 = (int)arg(&save), p2 = (int)arg(&save);
            cmd_fill(k, n, p1, p2);
            printf("OK\n");
        } else if (!strcmp(op, "C")) {
            cap_ctrl = arg(&save) & ~RUN & ~BIT(19);
            printf("OK\n");
        } else if (!strcmp(op, "T")) {
            uint32_t ctrl = arg(&save);
            unsigned reps = arg(&save), tmo = arg(&save), fl = arg(&save), gm = arg(&save);
            char *pw = strtok_r(NULL, " \t", &save);
            int pwr = pw ? (int)strtol(pw, NULL, 0) : -1;
            cmd_tx(ctrl, reps, tmo ? tmo : 2000, fl, gm, pwr);
        } else if (!strcmp(op, "H")) {
            unsigned off = arg(&save);
            cmd_load(off, &save);
        } else if (!strcmp(op, "Y")) {
            uint32_t ctrl = arg(&save);
            unsigned count = arg(&save), gap = arg(&save);
            char *pw = strtok_r(NULL, " \t", &save);
            int pwr = pw ? (int)strtol(pw, NULL, 0) : -1;
            unsigned c18 = arg(&save);
            cmd_train(ctrl, count, gap, pwr, c18);
        } else if (!strcmp(op, "D")) {
            unsigned off = arg(&save), n = arg(&save);
            cmd_dump(off, n);
        } else if (!strcmp(op, "P")) {
            unsigned n = arg(&save), clk = arg(&save);
            cmd_cap(n, clk);
        } else if (!strcmp(op, "K")) {
            key_mode = arg(&save);
            char *g = strtok_r(NULL, " \t", &save);
            rx_gain_force = g ? (int)strtol(g, NULL, 0) : -1;
            printf("V,key_mode,%u,%d,gain_max=%" PRIu32 "\nOK\n", key_mode, rx_gain_force, (REG_READ(RX_GAIN) >> 8) & 127);
        } else if (!strcmp(op, "M")) {
            unsigned n = arg(&save), half = arg(&save), mode = arg(&save);
            char *pw = strtok_r(NULL, " \t", &save);
            cmd_modtest(n, half, mode, pw ? (int)strtol(pw, NULL, 0) : -1);
        } else if (!strcmp(op, "L")) {
            uint32_t c1 = arg(&save), c2 = arg(&save);
            unsigned nr = arg(&save), gm = arg(&save), off = arg(&save);
            cmd_contention(c1, c2 & ~RUN & ~BIT(19), nr, gm, off);
        } else if (!strcmp(op, "B")) {
            char *rs = strtok_r(NULL, " \t", &save);
            int r = rs ? (int)strtol(rs, NULL, 0) : -1, c2 = arg(&save);
            if (r < 0) {
                for (int rr = 0; rr < 8; rr++)
                    for (int cc = 0; cc < 4; cc++) printf("V,pbus,%d,%d,%u\n", rr, cc, rom_pbus_rd(rr, cc));
                printf("OK\n");
            } else printf("V,pbus,%d,%d,%u\nOK\n", r, c2, rom_pbus_rd(r, c2));
        } else if (!strcmp(op, "I")) {
            cmd_dacclk();
        } else if (!strcmp(op, "Q")) {
            char *ms = strtok_r(NULL, " \t", &save);
            cmd_freq(ms ? (int)strtol(ms, NULL, 0) : -1);
        } else {
            printf("ERR cmd\n");
        }
        flush_out();
    }
}
