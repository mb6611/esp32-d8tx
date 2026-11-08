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
