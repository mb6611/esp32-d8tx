#include "packet.h"
#include <string.h>

uint16_t d8_crc(const uint8_t *p, size_t n) {
    uint16_t c = 0xffff;
    for (size_t i = 0; i < n; i++) {
        c ^= (uint16_t)p[i] << 8;
        for (int b = 0; b < 8; b++) c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x8005) : (uint16_t)(c << 1);
    }
    return c;
}

int d8_air_bytes(const uint8_t *p, size_t n, uint8_t out[D8_AIR_BYTES]) {
    if ((n != D8_BODY_BYTES && n != D8_PACKET_BYTES) || p[0] != 0x11) return 0;
    /* Betaflight cc2500FrskyDConfig: MDMCFG1=0x23 -> four 0xaa preamble bytes;
     * SYNC1/0 reset defaults d3 91; PKTCTRL0=0x05 (WHITE_DATA bit6=0),
     * MDMCFG2=0x11 (MANCHESTER_EN bit3=0): MSB-first, no encoding/whitening. */
    memset(out, 0xaa, 4);
    out[4] = 0xd3; out[5] = 0x91;
    memcpy(out + 6, p, n);
    if (n == D8_BODY_BYTES) {
        uint16_t crc = d8_crc(p, n);
        out[24] = (uint8_t)(crc >> 8); out[25] = (uint8_t)crc;
    }
    return 1;
}

void d8_hop_table(unsigned start, unsigned step, uint8_t out[D8_HOP_CHANNELS]) {
    out[0] = 0;
    for (unsigned i = 1; i < D8_HOP_CHANNELS; i++) out[i] = (uint8_t)(start + step * i);
}

int d8_ident_valid(const d8_ident_t *id) {
    if (!id->step) return 0;
    uint8_t tab[D8_HOP_CHANNELS], seen[256] = {0};
    d8_hop_table(id->start, id->step, tab);
    for (unsigned i = 1; i < D8_HOP_CHANNELS; i++) {
        if (tab[i] < 2u || tab[i] > D8_HOP_CH_MAX || seen[tab[i]]) return 0;
        seen[tab[i]] = 1;
    }
    return 1;
}

int d8_ident_good(const d8_ident_t *id) {
    if (id->id0 == 0x00 || id->id0 == 0x03 || id->id0 == 0xff || !d8_ident_valid(id)) return 0;
    uint8_t tab[D8_HOP_CHANNELS];
    d8_hop_table(id->start, id->step, tab);
    for (unsigned i = 1; i < D8_HOP_CHANNELS; i++)
        if (tab[i] > D8_GEN_CH_MAX || tab[i] == 0x5a || tab[i] == 0xdc) return 0;
    return 1;
}

void d8_ident_generate(uint32_t (*rnd)(void), d8_ident_t *out) {
    for (unsigned n = 0; n < 100000u; n++) {
        uint32_t r = rnd();
        d8_ident_t c = {(uint8_t)r, (uint8_t)(r >> 8), (uint8_t)(r >> 16), (uint8_t)(r >> 24)};
        if (d8_ident_good(&c)) { *out = c; return; }
    }
    const d8_ident_t fallback = {0x5c, 0x31, 7, 86}; /* d8_ident_good (test_packet) */
    *out = fallback;
}

void d8_build_bind(uint8_t id0, uint8_t id1, unsigned idx, const uint8_t hop[D8_HOP_CHANNELS], uint8_t out[D8_BODY_BYTES]) {
    memset(out, 0, D8_BODY_BYTES);
    out[0] = 0x11; out[1] = 0x03; out[2] = 0x01; out[3] = id0; out[4] = id1; out[5] = (uint8_t)idx;
    for (unsigned n = 0; n < 5; n++) out[6 + n] = idx + n < D8_HOP_CHANNELS ? hop[idx + n] : 0;
    out[17] = D8_BIND_BYTE17;
}

uint32_t d8_channel_f10(unsigned n) { return 240400000u + n * 29993u; }

uint16_t d8_us_to_raw(int us) {
    int v = (us * 3 + 1) / 2; /* us >= 0 */
    return (uint16_t)(v < 0 ? 0 : v > 4095 ? 4095 : v);
}

void d8_build_body(uint8_t id0, uint8_t id1, uint8_t counter, const uint16_t raw[D8_STICKS],
                   uint8_t out[D8_BODY_BYTES]) {
    static const uint8_t lo[8] = {6, 7, 8, 9, 12, 13, 14, 15};
    static const uint8_t hi[8] = {10, 10, 11, 11, 16, 16, 17, 17};
    static const uint8_t sh[8] = {0, 4, 0, 4, 0, 4, 0, 4};
    memset(out, 0, D8_BODY_BYTES);
    out[0] = 0x11; out[1] = id0; out[2] = id1; out[3] = 0x00; out[4] = counter; out[5] = 0x01; /* observed E8 layout, as d8_vectors.build */
    for (unsigned i = 0; i < 8; i++) {
        out[lo[i]] = (uint8_t)(raw[i] & 0xff);
        out[hi[i]] |= (uint8_t)(((raw[i] >> 8) & 0xf) << sh[i]);
    }
}

void d8_mark_telemetry(uint8_t body[D8_BODY_BYTES], uint8_t tid) {
    body[3] = D8_TLM_REQ;
    body[4] = (uint8_t)(tid & 0x1f);
}

unsigned d8_reply_blocks(const int16_t *iq, unsigned n_out, unsigned dec, unsigned *fit) {
    *fit = 0;
    if (!dec) return 0;
    const unsigned b = 8000u / dec, a = 32000u / dec; /* 0.5 ms block, 2.0 ms start (fs = 16 MHz / dec) */
    const uint64_t thr = (uint64_t)D8_REPLY_POW * dec * dec / 1024u * b;
    unsigned nb = 0;
    for (unsigned k = 0; k < D8_REPLY_BLOCKS; k++) {
        unsigned i0 = a + k * b;
        if (i0 + b > n_out) break;
        ++*fit;
        uint64_t s = 0;
        for (unsigned i = i0; i < i0 + b; i++) {
            int32_t x = iq[2 * i], y = iq[2 * i + 1];
            s += (uint32_t)(x * x) + (uint32_t)(y * y);
        }
        if (s > thr) nb++;
    }
    return nb;
}
