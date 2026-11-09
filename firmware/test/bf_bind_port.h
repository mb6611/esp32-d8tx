/* SPDX-License-Identifier: GPL-3.0-or-later
 * Port of Betaflight src/main/rx/cc2500_frsky_shared.c (getBind1/getBind2),
 * https://github.com/betaflight/betaflight. Test-only; not linked into the firmware. */
#pragma once
#include <stdint.h>
#include "../main/packet.h"

/* ---- C port of Betaflight cc2500_frsky_shared.c getBind1/getBind2 (bind state machine after tuning) ----
 * fifo = what the CC2500 FIFO holds: length byte + 17 payload bytes + RSSI + LQI|CRC_OK (CRC stripped, APPEND_STATUS),
 * ccLen = 20. Bind mode filters ADDR 0x03 (PKTCTRL1 0x0D: ADR_CHK=01) -> packet[1] must be 0x03. */
typedef struct { uint8_t txid[2], hop[50], rxnum; unsigned list_len, bind_idx; int state; } bf_rx_t; /* 1 = bind1, 2 = bind2, 3 = done */
void bf_init(bf_rx_t *r);
void bf_feed(bf_rx_t *r, const uint8_t body[D8_BODY_BYTES]);
