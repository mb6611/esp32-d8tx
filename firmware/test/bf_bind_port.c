/* SPDX-License-Identifier: GPL-3.0-or-later
 * Port of Betaflight src/main/rx/cc2500_frsky_shared.c (getBind1/getBind2),
 * https://github.com/betaflight/betaflight. Test-only; not linked into the firmware. */
#include <string.h>
#include "bf_bind_port.h"

void bf_init(bf_rx_t *r) { memset(r, 0, sizeof *r); r->bind_idx = 5; r->state = 1; }
void bf_feed(bf_rx_t *r, const uint8_t body[D8_BODY_BYTES]) {
    uint8_t p[20];
    memcpy(p, body, 18); p[18] = 0x40; p[19] = 0x80 | 60; /* CRC ok, LQI 60 */
    const unsigned cc_len = 20;
    if (p[1] != 0x03 || !(p[cc_len - 1] & 0x80) || p[2] != 0x01) return;
    if (r->state == 1) {
        if (p[5] != 0x00) return;
        r->txid[0] = p[3]; r->txid[1] = p[4];
        for (unsigned n = 0; n < 5; n++) r->hop[p[5] + n] = p[6 + n];
        r->rxnum = p[12];
        r->state = 2;
    } else if (r->state == 2) {
        if (r->bind_idx > 120) { r->state = 3; return; }
        if (p[3] != r->txid[0] || p[4] != r->txid[1] || p[5] != r->bind_idx) return;
        for (unsigned n = 0; n < 5; n++) {
            if (p[6 + n] == p[cc_len - 3] || p[6 + n] == 0) {
                if (r->bind_idx >= 0x2d) { r->list_len = p[5] + n; r->state = 3; return; }
            }
            r->hop[p[5] + n] = p[6 + n];
        }
        r->bind_idx += 5;
    }
}
