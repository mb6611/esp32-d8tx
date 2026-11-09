#include "cmd_parse.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static int parse_int(const char *t, long lo, long hi, long *out) {
    if (!t || !*t) return 0;
    char *end;
    errno = 0;
    long v = strtol(t, &end, 10); /* decimal only: no 0x/octal surprises */
    if (errno || *end || v < lo || v > hi) return 0;
    *out = v;
    return 1;
}

static int hex_nibble(char x) {
    if (x >= '0' && x <= '9') return x - '0';
    if (x >= 'a' && x <= 'f') return x - 'a' + 10;
    if (x >= 'A' && x <= 'F') return x - 'A' + 10;
    return -1;
}

static int cur_legacy; /* set per cmd_parse call: line starts with a legacy bench command */

static cmd_t fail(const char *why) {
    cmd_t c = {.kind = CMD_ERR, .err = why, .legacy = cur_legacy};
    return c;
}

const char *err_code(const char *why) {
    if (!strcmp(why, "args") || !strcmp(why, "packet_len") || !strcmp(why, "hex") || !strcmp(why, "length_byte")) return "args";
    if (!strcmp(why, "cmd")) return "unknown";
    if (!strcmp(why, "long") || !strcmp(why, "keyed") || !strcmp(why, "busy")) return why;
    return "range";
}

cmd_t cmd_parse(char *line) {
    cmd_t c = {.kind = CMD_NONE, .pwr = PWR_MAX};
    char *save, *tok[12];
    int n = 0;
    for (char *t = strtok_r(line, " \t", &save); t; t = strtok_r(NULL, " \t", &save)) {
        if (n == 12) return fail("args");
        tok[n++] = t;
    }
    if (!n) return c;
    long v;
    cur_legacy = !strcmp(tok[0], "TONE") || !strcmp(tok[0], "ALT") || !strcmp(tok[0], "PKT") ||
                 !strcmp(tok[0], "RETUNE") || !strcmp(tok[0], "STICKS") || !strcmp(tok[0], "HOP");
    if (!strcmp(tok[0], "INFO")) {
        if (n != 1) return fail("args");
        c.kind = CMD_INFO;
        return c;
    }
    if (!strcmp(tok[0], "ID")) { /* ID | ID new | ID XXXX start step (hex txid, decimal hop start/step) */
        if (n == 1) { c.id_op = ID_GET; c.kind = CMD_ID; return c; }
        if (n == 2) {
            if (strcmp(tok[1], "new")) return fail("args");
            c.id_op = ID_NEW; c.kind = CMD_ID; return c;
        }
        if (n != 4) return fail("args");
        if (strlen(tok[1]) != 4) return fail("txid");
        unsigned id = 0;
        for (int i = 0; i < 4; i++) {
            int x = hex_nibble(tok[1][i]);
            if (x < 0) return fail("txid");
            id = id << 4 | (unsigned)x;
        }
        c.ident.id0 = (uint8_t)(id >> 8); c.ident.id1 = (uint8_t)id;
        if (!parse_int(tok[2], 0, 255, &v)) return fail("start");
        c.ident.start = (uint8_t)v;
        if (!parse_int(tok[3], 1, 255, &v)) return fail("step");
        c.ident.step = (uint8_t)v;
        if (!d8_ident_valid(&c.ident)) return fail("hop_table");
        c.id_op = ID_SET; c.kind = CMD_ID;
        return c;
    }
    if (!strcmp(tok[0], "BIND")) { /* BIND [pwr]: bind packets on channel 0 until STOP or BIND_TIMEOUT_MS */
        if (n > 2) return fail("args");
        if (n == 2) {
            if (!parse_int(tok[1], 0, PWR_MAX, &v)) return fail("pwr");
            c.pwr = (int)v;
        }
        c.kind = CMD_BIND;
        return c;
    }
    if (!strcmp(tok[0], "LINK")) { /* LINK <pwr> [timeout_ms]: continuous hopping (HOP 0) */
        if (n < 2 || n > 3) return fail("args");
        if (!parse_int(tok[1], 0, PWR_MAX, &v)) return fail("pwr");
        c.pwr = (int)v;
        c.timeout_ms = HOP_TIMEOUT_DEF_MS;
        if (n == 3) {
            if (!parse_int(tok[2], 1, HOP_TIMEOUT_MAX_MS, &v)) return fail("timeout");
            c.timeout_ms = (unsigned)v;
        }
        c.n_slots = 0;
        c.kind = CMD_LINK;
        return c;
    }
    if (!strcmp(tok[0], "TLM")) { /* TLM every [cap_us] [gain] [dec] [same] [stream] [ack] [mark] [retry] [skip_us] [bits]: telemetry listen for later LINKs */
        if (n < 2 || n > 12) return fail("args");
        if (!parse_int(tok[1], 0, TLM_EVERY_MAX, &v) || (v && v < TLM_EVERY_MIN)) return fail("every");
        c.tlm_every = (unsigned)v;
        c.cap_us = TLM_CAP_US_DEF; c.gain = TLM_GAIN_DEF; c.dec = TLM_DEC_DEF; c.same = 0; c.skip_us = 0; c.bits = 8;
        if (n >= 3) { if (!parse_int(tok[2], TLM_CAP_US_MIN, TLM_CAP_US_MAX, &v)) return fail("cap_us"); c.cap_us = (unsigned)v; }
        if (n >= 4) { if (!parse_int(tok[3], -1, TLM_GAIN_MAX, &v)) return fail("gain"); c.gain = (int)v; }
        if (n >= 5) { if (!parse_int(tok[4], 16, 64, &v) || (v != 16 && v != 32 && v != 64)) return fail("dec"); c.dec = (unsigned)v; }
        if (n >= 6) { if (!parse_int(tok[5], 0, 1, &v)) return fail("same"); c.same = (int)v; }
        if (n >= 7) { if (!parse_int(tok[6], 0, 1, &v)) return fail("stream"); c.stream = (int)v; }
        if (n >= 8) { if (!parse_int(tok[7], 0, 1, &v)) return fail("ack"); c.ack = (int)v; }
        if (n >= 9) { if (!parse_int(tok[8], 0, 1, &v)) return fail("mark"); c.mark = (int)v; }
        if (n >= 10) { if (!parse_int(tok[9], 0, TLM_RETRY_MAX, &v)) return fail("retry"); c.retry = (int)v; }
        if (n >= 11) { if (!parse_int(tok[10], 0, TLM_SKIP_MAX, &v)) return fail("skip"); c.skip_us = (unsigned)v; }
        if (n >= 12) { if (!parse_int(tok[11], 4, 8, &v) || (v != 4 && v != 8)) return fail("bits"); c.bits = (int)v; }
        if (c.retry && !c.stream) return fail("retry");
        if ((c.skip_us || c.bits != 8) && !c.stream) return fail("skip");
        if (c.skip_us + 500u > c.cap_us) return fail("skip");
        if (c.cap_us * 16u / c.dec > 6000u) return fail("cap_us");
        c.kind = CMD_TLM;
        return c;
    }
    if (!strcmp(tok[0], "TLMX")) { /* TLMX tail_bits settle_us [all] [probe]: trigger experiments (RAM only) */
        if (n < 3 || n > 5) return fail("args");
        if (!parse_int(tok[1], 0, TLMX_TAIL_MAX, &v)) return fail("tail");
        c.tail_bits = (unsigned)v;
        if (!parse_int(tok[2], 0, TLMX_SETTLE_MAX, &v)) return fail("settle");
        c.settle_us = (unsigned)v;
        c.tail_all = 0;
        c.probe = 0;
        if (n >= 4) { if (!parse_int(tok[3], 0, 1, &v)) return fail("all"); c.tail_all = (int)v; }
        if (n >= 5) { if (!parse_int(tok[4], 0, 1, &v)) return fail("probe"); c.probe = (int)v; }
        c.kind = CMD_TLMX;
        return c;
    }
    if (!strcmp(tok[0], "TID")) { /* TID n: telemetry id for the next trigger (host ack/resend; silent during LINK) */
        if (n != 2) return fail("args");
        if (!parse_int(tok[1], 0, 31, &v)) return fail("tid");
        c.tid = (unsigned)v;
        c.kind = CMD_TID;
        return c;
    }
    if (!strcmp(tok[0], "TCAP")) { /* TCAP khz [cap_us] [gain] [dec] [pwr]: one capture; pwr>=0 keys one data packet first */
        if (n < 2 || n > 6) return fail("args");
        if (!parse_int(tok[1], RETUNE_KHZ_MIN, RETUNE_KHZ_MAX, &v)) return fail("khz");
        c.khz = (int)v;
        c.cap_us = TLM_CAP_US_DEF; c.gain = TLM_GAIN_DEF; c.dec = TLM_DEC_DEF; c.pwr = -1;
        if (n >= 3) { if (!parse_int(tok[2], TLM_CAP_US_MIN, TLM_CAP_US_MAX, &v)) return fail("cap_us"); c.cap_us = (unsigned)v; }
        if (n >= 4) { if (!parse_int(tok[3], -1, TLM_GAIN_MAX, &v)) return fail("gain"); c.gain = (int)v; }
        if (n >= 5) { if (!parse_int(tok[4], 16, 64, &v) || (v != 16 && v != 32 && v != 64)) return fail("dec"); c.dec = (unsigned)v; }
        if (n >= 6) { if (!parse_int(tok[5], -1, PWR_MAX, &v)) return fail("pwr"); c.pwr = (int)v; }
        if (c.cap_us * 16u / c.dec > 6000u) return fail("cap_us");
        c.kind = CMD_TCAP;
        return c;
    }
    if (!strcmp(tok[0], "PING") || !strcmp(tok[0], "STAT") || !strcmp(tok[0], "U") || !strcmp(tok[0], "STOP")) {
        if (n != 1) return fail("args");
        c.kind = tok[0][0] == 'P' ? CMD_PING : !strcmp(tok[0], "STAT") ? CMD_STAT : CMD_UNKEY;
        return c;
    }
    if (!strcmp(tok[0], "PKT")) { /* PKT <18/20 bytes hex> [pwr]; CRC appended for 18 bytes */
        if (n < 2 || n > 3) return fail("args");
        size_t len = strlen(tok[1]);
        if (len != 2 * D8_BODY_BYTES && len != 2 * D8_PACKET_BYTES) return fail("packet_len");
        for (size_t i = 0; i < len / 2; i++) {
            int hi = hex_nibble(tok[1][2*i]), lo = hex_nibble(tok[1][2*i+1]);
            if (hi < 0 || lo < 0) return fail("hex");
            c.packet[i] = (uint8_t)((hi << 4) | lo);
        }
        if (c.packet[0] != 0x11) return fail("length_byte");
        c.packet_len = (unsigned)(len / 2);
        if (n == 3) {
            if (!parse_int(tok[2], 0, PWR_MAX, &v)) return fail("pwr");
            c.pwr = (int)v;
        }
        c.kind = CMD_PKT;
        return c;
    }
    if (!strcmp(tok[0], "RETUNE")) { /* RETUNE khz: move the LO (no keying) */
        if (n != 2) return fail("args");
        if (!parse_int(tok[1], RETUNE_KHZ_MIN, RETUNE_KHZ_MAX, &v)) return fail("khz");
        c.khz = (int)v;
        c.kind = CMD_RETUNE;
        return c;
    }
    if (!strcmp(tok[0], "FOFS")) { /* FOFS hz: signed LO offset for RETUNE/HOP */
        if (n != 2) return fail("args");
        if (!parse_int(tok[1], -FOFS_HZ_MAX, FOFS_HZ_MAX, &v)) return fail("hz");
        c.hz = (int)v;
        c.kind = CMD_FOFS;
        return c;
    }
    if (!strcmp(tok[0], "HOP")) { /* HOP n_slots [pwr] | HOP 0 pwr [timeout_ms] (continuous) */
        if (n < 2 || n > 4) return fail("args");
        if (!parse_int(tok[1], 0, HOP_SLOTS_MAX, &v)) return fail("slots");
        c.n_slots = (unsigned)v;
        c.timeout_ms = HOP_TIMEOUT_DEF_MS;
        if (c.n_slots) {
            if (n > 3) return fail("args");
        } else if (n < 3) {
            return fail("args"); /* continuous needs an explicit power */
        }
        if (n >= 3) {
            if (!parse_int(tok[2], 0, PWR_MAX, &v)) return fail("pwr");
            c.pwr = (int)v;
        }
        if (n == 4) {
            if (!parse_int(tok[3], 1, HOP_TIMEOUT_MAX_MS, &v)) return fail("timeout");
            c.timeout_ms = (unsigned)v;
        }
        c.kind = CMD_HOP;
        return c;
    }
    if (!strcmp(tok[0], "ARMOK")) { /* allow ch7 (ARM) high in S during the next HOP only */
        if (n != 1) return fail("args");
        c.kind = CMD_ARMOK;
        return c;
    }
    if (!strcmp(tok[0], "S")) { /* S c1..c8 us: clamped to 1000-2000; ch7 gate applied in d8tone.c */
        if (n != 1 + (int)D8_STICKS) return fail("args");
        for (unsigned i = 0; i < D8_STICKS; i++) {
            if (!parse_int(tok[1 + i], -1000000, 1000000, &v)) return fail("stick");
            if (v < S_US_MIN) v = S_US_MIN;
            if (v > S_US_MAX) v = S_US_MAX;
            c.sticks[i] = (int)v;
        }
        c.kind = CMD_S;
        return c;
    }
    if (!strcmp(tok[0], "STICKS")) { /* STICKS c1..c8 in microseconds */
        if (n != 1 + (int)D8_STICKS) return fail("args");
        for (unsigned i = 0; i < D8_STICKS; i++) {
            if (!parse_int(tok[1 + i], D8_STICK_US_MIN, D8_STICK_US_MAX, &v)) return fail("stick");
            c.sticks[i] = (int)v;
        }
        c.kind = CMD_STICKS;
        return c;
    }
    if (!strcmp(tok[0], "TONE")) { /* TONE f dur_us [pwr] */
        if (n < 3 || n > 4) return fail("args");
        if (!parse_int(tok[1], -TONE_F_MAX, TONE_F_MAX, &v)) return fail("freq");
        c.f_a = c.f_b = (int)v;
        if (!parse_int(tok[2], TONE_DUR_MIN_US, TONE_DUR_MAX_US, &v)) return fail("dur");
        c.dur_us = (uint32_t)v;
        if (n == 4) {
            if (!parse_int(tok[3], 0, PWR_MAX, &v)) return fail("pwr");
            c.pwr = (int)v;
        }
        c.kind = CMD_TONE;
        return c;
    }
    if (!strcmp(tok[0], "ALT")) { /* ALT fa fb half_us dur_us [pwr] */
        if (n < 5 || n > 6) return fail("args");
        if (!parse_int(tok[1], -TONE_F_MAX, TONE_F_MAX, &v)) return fail("freq");
        c.f_a = (int)v;
        if (!parse_int(tok[2], -TONE_F_MAX, TONE_F_MAX, &v)) return fail("freq");
        c.f_b = (int)v;
        if (!parse_int(tok[3], ALT_HALF_MIN_US, TONE_DUR_MAX_US, &v)) return fail("half");
        c.half_us = (uint32_t)v;
        if (!parse_int(tok[4], TONE_DUR_MIN_US, TONE_DUR_MAX_US, &v)) return fail("dur");
        c.dur_us = (uint32_t)v;
        if (c.half_us > c.dur_us) return fail("half>dur");
        if (c.dur_us / c.half_us > ALT_MAX_TRANS) return fail("transitions");
        if (n == 6) {
            if (!parse_int(tok[5], 0, PWR_MAX, &v)) return fail("pwr");
            c.pwr = (int)v;
        }
        c.kind = CMD_ALT;
        return c;
    }
    return fail("cmd");
}
