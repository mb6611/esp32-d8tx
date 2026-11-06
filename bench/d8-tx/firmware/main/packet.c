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
