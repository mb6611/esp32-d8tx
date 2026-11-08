/* See tlm_cap.h. Ring/marks logic ported from main/targets/esp32/iq_stream.c (single core here). */
#include "tlm_cap.h"
#include <stdbool.h>
#include <string.h>
#include "esp_attr.h"
#include "esp_cpu.h"
#include "soc/soc.h"
#include "soc/dport_reg.h"
#include "soc/dport_access.h"
#include "heap_memory_layout.h"

/* The capture aperture: keep the heap (Wi-Fi buffers) out of both 32 KiB banks. */
SOC_RESERVE_MEMORY_REGION(0x3ffe8000, 0x3fff8000, d8_rf_dump);

#define DUMP_CTRL    0x60033d90u
#define DUMP_STATUS  0x60033d94u
#define DUMP_BYTES   0x60033dc4u
#define WINDOW       ((volatile uint32_t *)0x3ffe8000)
#define BANK         8192u
#define BANK_MASK    (BANK - 1u)
#define ZW           64u
#define SESSION      (BANK - 2u * ZW)
#define MARK         0xa5c33c5au
#define CYC_PER_PAIR 15u /* 240 MHz / 16 MS/s */

static int16_t buf[2 * TCAP_MAX_OUT];
int16_t *tcap_buffer(void) { return buf; }

static struct {
    uint32_t n_pairs, log2dec, next_in;
    bool synced;
    tcap_res_t *r;
} st;

static IRAM_ATTR inline void memw(void) { __asm__ volatile("memw" ::: "memory"); }

static IRAM_ATTR inline void select_bank(uint32_t v) {
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, v);
    memw();
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, v); /* CPU-3.16: an access may be lost */
    memw();
}

/* n contiguous ring pairs at p (no bank wrap), first pair index a: add into the output blocks. */
static IRAM_ATTR void boxcar(const volatile uint32_t *vp, uint32_t a, uint32_t n) {
    const uint32_t *p = (const uint32_t *)vp;
    const uint32_t sh = st.log2dec, dm = (1u << sh) - 1u;
    while (n && (a & dm)) { /* head: single pairs into a partial block */
        uint32_t w = *p++;
        buf[2 * (a >> sh)] += (int16_t)((int32_t)(w << 22) >> 22);
        buf[2 * (a >> sh) + 1] += (int16_t)((int32_t)(w << 12) >> 22);
        a++;
        n--;
    }
    while (n > dm) { /* whole blocks */
        int32_t si = 0, sq = 0;
        for (uint32_t j = 0; j <= dm; j += 16) {
#pragma GCC unroll 16
            for (uint32_t k = 0; k < 16; k++) {
                uint32_t w = p[j + k];
                si += (int32_t)(w << 22) >> 22;
                sq += (int32_t)(w << 12) >> 22;
            }
        }
        buf[2 * (a >> sh)] += (int16_t)si;
        buf[2 * (a >> sh) + 1] += (int16_t)sq;
        p += dm + 1u;
        a += dm + 1u;
        n -= dm + 1u;
    }
    while (n) { /* tail */
        uint32_t w = *p++;
        buf[2 * (a >> sh)] += (int16_t)((int32_t)(w << 22) >> 22);
        buf[2 * (a >> sh) + 1] += (int16_t)((int32_t)(w << 12) >> 22);
        a++;
        n--;
    }
}

/* Pairs [p0, p1) from bank b (clipped to the requested length). */
static IRAM_ATTR void deliver(unsigned b, uint32_t p0, uint32_t p1) {
    if (p1 > st.n_pairs) p1 = st.n_pairs;
    if (p0 >= p1) return;
    if (st.synced && p0 != st.next_in) {
        if (p0 > st.next_in) st.r->lost += p0 - st.next_in;
        else if (st.next_in >= p1) return;
        else p0 = st.next_in;
    } else if (!st.synced && p0) {
        st.r->lost += p0;
    }
    st.synced = true;
    st.next_in = p1;
    const volatile uint32_t *base = WINDOW + b * BANK;
    uint32_t g = (base[p0 & BANK_MASK] >> 20) & 0xffu; /* gain index, as iq_stream (uint8_t) */
    if (!st.r->units) st.r->gain_first = g;
    st.r->gain_last = g;
    st.r->pairs += p1 - p0;
    while (p0 < p1) {
        uint32_t off = p0 & BANK_MASK, n = BANK - off;
        if (n > p1 - p0) n = p1 - p0;
        boxcar(base + off, p0, n);
        p0 += n;
    }
}

static IRAM_ATTR void mark_zone(unsigned b, uint32_t start) {
    volatile uint32_t *w = WINDOW + b * BANK;
    for (uint32_t k = 0; k < 3u * ZW; k++) w[(start + k) & BANK_MASK] = MARK;
}

/* Bank b finished the session planned for [a0, a1): the marks left between its end and its start
 * give both switch points (see iq_stream.c finish_session). */
static IRAM_ATTR void finish_session(unsigned b, uint32_t a0, uint32_t a1) {
    const volatile uint32_t *w = WINDOW + b * BANK;
    uint32_t zs = a1 & BANK_MASK, first = ~0u, last = ~0u;
    for (uint32_t k = 0; k < 3u * ZW; k++) {
        if (w[(zs + k) & BANK_MASK] == MARK) {
            if (first == ~0u) first = k;
            last = k;
        }
    }
    bool ok = first < 2u * ZW && last + 1u >= 2u * ZW && last + 1u < 3u * ZW;
    for (uint32_t k = first; ok && k <= last; k++) ok = w[(zs + k) & BANK_MASK] == MARK;
    if (ok)
        deliver(b, a0 + (last + 1u - 2u * ZW), a1 + first);
    else
        st.r->bad++;
    mark_zone(b, (a1 + 2u * SESSION) & BANK_MASK);
}

void tcap_prepare(unsigned n_out) {
    REG_WRITE(DUMP_CTRL, 0);
    for (uint32_t j = 0; j < 2u * BANK; j++) WINDOW[j] = MARK; /* CPU-owned: no RF dump mode */
    memset(buf, 0, 4u * (n_out > TCAP_MAX_OUT ? TCAP_MAX_OUT : n_out));
}

IRAM_ATTR void tcap_run(unsigned n_out, unsigned dec, tcap_res_t *r) {
    memset(r, 0, sizeof *r);
    if (n_out > TCAP_MAX_OUT) n_out = TCAP_MAX_OUT;
    st.log2dec = dec == 64 ? 6 : dec == 16 ? 4 : 5;
    st.n_pairs = n_out << st.log2dec;
    st.next_in = 0;
    st.synced = false;
    st.r = r;
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t base = owner & ~DPORT_MAC_DUMP_MODE_M;
    const uint32_t sel[2] = {base | (2u << DPORT_MAC_DUMP_MODE_S), base | (1u << DPORT_MAC_DUMP_MODE_S)};
    uint32_t byte_select = REG_READ(DUMP_BYTES);
    REG_WRITE(DUMP_BYTES, 0x03020100); /* as acquire_iq / mac_init */
    select_bank(sel[0]);
    uint32_t ctrl = BIT(16) | BANK | BIT(17); /* 16 MS/s, 8192-word ring */
    REG_WRITE(DUMP_CTRL, ctrl | BIT(18));
    REG_WRITE(DUMP_CTRL, ctrl);
    REG_WRITE(DUMP_CTRL, ctrl | BIT(31));
    uint32_t last_cc = esp_cpu_get_cycle_count();
    r->start_cyc = last_cc;
    const uint32_t cap = (st.n_pairs + 4u * SESSION) * CYC_PER_PAIR;
    uint32_t last_ptr = 0, abs_ptr = 0, a0 = 0, a1 = SESSION;
    unsigned rf = 0;
    while (a0 < st.n_pairs) {
        for (;;) {
            uint32_t p = REG_READ(DUMP_STATUS) & BANK_MASK, cc = esp_cpu_get_cycle_count();
            uint32_t d = (p - last_ptr) & BANK_MASK, est = (cc - last_cc) / CYC_PER_PAIR;
            if (est > BANK / 2u) d += ((est - d + BANK / 2u) / BANK) * BANK;
            abs_ptr += d;
            last_ptr = p;
            last_cc = cc;
            if (abs_ptr >= a1) break;
            if (cc - r->start_cyc > cap) { r->timeout = 1; goto out; }
            uint32_t t = esp_cpu_get_cycle_count();
            while (esp_cpu_get_cycle_count() - t < 64u) {}
        }
        select_bank(sel[rf ^ 1u]);
        uint32_t late = abs_ptr - a1;
        if (late > r->late_max) r->late_max = late;
        uint32_t t0 = esp_cpu_get_cycle_count();
        finish_session(rf, a0, a1);
        uint32_t work = esp_cpu_get_cycle_count() - t0;
        if (work > r->work_max) r->work_max = work;
        r->units++;
        rf ^= 1u;
        a0 = a1;
        a1 += SESSION;
    }
out:
    REG_WRITE(DUMP_CTRL, 0);
    r->end_cyc = esp_cpu_get_cycle_count();
    while (esp_cpu_get_cycle_count() - r->end_cyc < 2400u) {} /* 10 us */
    select_bank(owner);
    REG_WRITE(DUMP_BYTES, byte_select);
    if (st.next_in < st.n_pairs) r->lost += st.n_pairs - (st.synced ? st.next_in : 0);
}
