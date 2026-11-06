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

static cmd_t fail(const char *why) {
    cmd_t c = {.kind = CMD_ERR, .err = why};
    return c;
}

cmd_t cmd_parse(char *line) {
    cmd_t c = {.kind = CMD_NONE, .pwr = PWR_MAX};
    char *save, *tok[10];
    int n = 0;
    for (char *t = strtok_r(line, " \t", &save); t; t = strtok_r(NULL, " \t", &save)) {
        if (n == 10) return fail("args");
        tok[n++] = t;
    }
    if (!n) return c;
    long v;
    if (!strcmp(tok[0], "PING") || !strcmp(tok[0], "STAT") || !strcmp(tok[0], "U")) {
        if (n != 1) return fail("args");
        c.kind = tok[0][0] == 'P' ? CMD_PING : tok[0][0] == 'S' ? CMD_STAT : CMD_UNKEY;
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
    if (!strcmp(tok[0], "HOP")) { /* HOP n_slots [pwr] */
        if (n < 2 || n > 3) return fail("args");
        if (!parse_int(tok[1], 1, HOP_SLOTS_MAX, &v)) return fail("slots");
        c.n_slots = (unsigned)v;
        if (n == 3) {
            if (!parse_int(tok[2], 0, PWR_MAX, &v)) return fail("pwr");
            c.pwr = (int)v;
        }
        c.kind = CMD_HOP;
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
