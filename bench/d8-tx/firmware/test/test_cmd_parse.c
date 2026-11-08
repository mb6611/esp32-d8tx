#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../main/cmd_parse.h"

static cmd_t P(const char *s) { char b[96]; strcpy(b, s); return cmd_parse(b); }
#define ERR(s, why) do { cmd_t c = P(s); assert(c.kind == CMD_ERR); assert(!strcmp(c.err, why)); } while (0)

int main(void) {
    assert(P("").kind == CMD_NONE);
    assert(P("PING").kind == CMD_PING && P("STAT").kind == CMD_STAT && P("U").kind == CMD_UNKEY);
    ERR("U 1", "args");
    cmd_t c = P("TONE 0 1000");
    assert(c.kind == CMD_TONE && c.f_a == 0 && c.dur_us == 1000 && c.pwr == 127);
    c = P("TONE -511 200000 5");
    assert(c.kind == CMD_TONE && c.f_a == -511 && c.dur_us == 200000 && c.pwr == 5);
    ERR("TONE 512 1000", "freq"); ERR("TONE -512 1000", "freq"); ERR("TONE x 1000", "freq");
    ERR("TONE 0x10 1000", "freq"); ERR("TONE 1.5 1000", "freq");
    ERR("TONE 0 0", "dur"); ERR("TONE 0 49", "dur"); ERR("TONE 0 200001", "dur"); ERR("TONE 0 -5", "dur");
    ERR("TONE 0 1000 128", "pwr"); ERR("TONE 0 1000 -1", "pwr"); ERR("TONE 0", "args");
    ERR("TONE 0 1000 1 2", "args");
    c = P("ALT -8 8 100 1000");
    assert(c.kind == CMD_ALT && c.f_a == -8 && c.f_b == 8 && c.half_us == 100 && c.dur_us == 1000);
    ERR("ALT 0 8 49 1000", "half"); ERR("ALT 0 8 2000 1000", "half>dur");
    ERR("ALT 0 8 50 20000", "transitions");  /* 400 > 255 */
    assert(P("ALT 0 8 50 12750").kind == CMD_ALT); /* 255 ok */
    ERR("ALT 0 8 50 12800", "transitions");
    ERR("ALT 0 600 100 1000", "freq"); ERR("ALT 0 8 100", "args");
    ERR("KEY", "cmd"); ERR("tone 0 1000", "cmd");
    ERR("A B C D E F G H I J K", "args");
    c = P("FOFS -63000"); assert(c.kind == CMD_FOFS && c.hz == -63000);
    assert(P("FOFS 200000").hz == 200000 && P("FOFS 0").kind == CMD_FOFS);
    ERR("FOFS 200001", "hz"); ERR("FOFS -200001", "hz"); ERR("FOFS x", "hz"); ERR("FOFS", "args");
    c = P("HOP 5"); assert(c.kind == CMD_HOP && c.n_slots == 5 && c.pwr == 127);
    ERR("HOP 5 10 300", "args"); ERR("HOP 0", "args"); ERR("HOP 0 5 0", "timeout");
    c = P("HOP 0 20"); assert(c.kind == CMD_HOP && c.n_slots == 0 && c.pwr == 20 && c.timeout_ms == 300);
    c = P("HOP 0 20 1000"); assert(c.timeout_ms == 1000);
    ERR("HOP 0 20 1001", "timeout"); ERR("HOP 0 128", "pwr");
    assert(P("STOP").kind == CMD_UNKEY);
    c = P("S 1500 900 2500 1000 2000 1500 2000 -5");
    assert(c.kind == CMD_S && c.sticks[0] == 1500 && c.sticks[1] == 1000 && c.sticks[2] == 2000);
    assert(c.sticks[3] == 1000 && c.sticks[4] == 2000 && c.sticks[5] == 1500 && c.sticks[6] == 2000 && c.sticks[7] == 1000); /* ch7 gate is in d8tone.c (ARMOK) */
    assert(P("ARMOK").kind == CMD_ARMOK); ERR("ARMOK 1", "args");
    assert(P("S 1500 1500 1500 1500 1500 1500 1200 1500").sticks[6] == 1200);
    ERR("S 1500", "args"); ERR("S 1 2 3 4 5 6 7 x", "stick");
    assert(P("STAT").kind == CMD_STAT);
    /* protocol v1 */
    assert(P("INFO").kind == CMD_INFO); ERR("INFO 1", "args");
    c = P("LINK 127"); assert(c.kind == CMD_LINK && c.pwr == 127 && c.n_slots == 0 && c.timeout_ms == 300);
    c = P("LINK 0 1000"); assert(c.kind == CMD_LINK && c.pwr == 0 && c.timeout_ms == 1000);
    assert(P("LINK 5 1").timeout_ms == 1);
    ERR("LINK", "args"); ERR("LINK 1 2 3", "args"); ERR("LINK 128", "pwr"); ERR("LINK -1", "pwr");
    ERR("LINK 5 0", "timeout"); ERR("LINK 5 1001", "timeout"); ERR("LINK x", "pwr");
    assert(!P("LINK 128").legacy && !P("FOFS x").legacy && !P("BOGUS").legacy);
    assert(P("TONE x 1").legacy && P("HOP 0").legacy && P("PKT zz").legacy && P("RETUNE 1").legacy);
    /* error codes: args range busy keyed unknown long */
    assert(!strcmp(err_code("args"), "args") && !strcmp(err_code("cmd"), "unknown"));
    assert(!strcmp(err_code("hz"), "range") && !strcmp(err_code("stick"), "range") && !strcmp(err_code("pwr"), "range"));
    assert(!strcmp(err_code("timeout"), "range") && !strcmp(err_code("busy"), "busy"));
    assert(!strcmp(err_code("keyed"), "keyed") && !strcmp(err_code("long"), "long") && !strcmp(err_code("hex"), "args"));
    assert(P("STOP").kind == CMD_UNKEY);
    ERR("STOP 1", "args"); ERR("PING 1", "args"); ERR("STAT x", "args"); ERR("ARMOK 1", "args");
    ERR("NOPE", "cmd");
    /* TLM / TCAP (telemetry listen, off by default) */
    c = P("TLM 0"); assert(c.kind == CMD_TLM && c.tlm_every == 0 && c.cap_us == 10000 && c.gain == 40 && c.dec == 32 && c.same == 0);
    c = P("TLM 47 12000 -1 64 1"); assert(c.kind == CMD_TLM && c.tlm_every == 47 && c.cap_us == 12000 && c.gain == -1 && c.dec == 64 && c.same == 1);
    c = P("TLM 4 6000 0 16"); assert(c.kind == CMD_TLM && c.dec == 16 && c.gain == 0);
    ERR("TLM", "args"); ERR("TLM 3", "every"); ERR("TLM 941", "every"); ERR("TLM 47 499", "cap_us"); ERR("TLM 47 12001", "cap_us");
    ERR("TLM 47 10000 128", "gain"); ERR("TLM 47 10000 -2", "gain"); ERR("TLM 47 10000 40 48", "dec");
    ERR("TLM 47 10000 40 32 2", "same"); ERR("TLM 47 6001 40 16", "cap_us"); ERR("TLM 1 2 3 4 5 6", "args");
    assert(!P("TLM 3").legacy && !strcmp(err_code("every"), "range"));
    c = P("TCAP 2440000"); assert(c.kind == CMD_TCAP && c.khz == 2440000 && c.pwr == -1 && c.cap_us == 10000 && c.dec == 32);
    c = P("TCAP 2412000 2000 50 64 127"); assert(c.kind == CMD_TCAP && c.cap_us == 2000 && c.gain == 50 && c.dec == 64 && c.pwr == 127);
    ERR("TCAP 2403999", "khz"); ERR("TCAP 2412000 2000 50 64 128", "pwr"); ERR("TCAP", "args");
    puts("cmd_parse tests ok");
    return 0;
}
