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
    cmd_t c;
#if D8_BENCH
    c = P("TONE 0 1000 127");
    assert(c.kind == CMD_TONE && c.f_a == 0 && c.dur_us == 1000 && c.pwr == 127);
    c = P("TONE -511 200000 5");
    assert(c.kind == CMD_TONE && c.f_a == -511 && c.dur_us == 200000 && c.pwr == 5);
    ERR("TONE 512 1000 5", "freq"); ERR("TONE -512 1000 5", "freq"); ERR("TONE x 1000 5", "freq");
    ERR("TONE 0x10 1000 5", "freq"); ERR("TONE 1.5 1000 5", "freq");
    ERR("TONE 0 0 5", "dur"); ERR("TONE 0 49 5", "dur"); ERR("TONE 0 200001 5", "dur"); ERR("TONE 0 -5 5", "dur");
    ERR("TONE 0 1000 128", "pwr"); ERR("TONE 0 1000 -1", "pwr"); ERR("TONE 0", "args");
    ERR("TONE 0 1000 1 2", "args");
    c = P("ALT -8 8 100 1000 9");
    assert(c.kind == CMD_ALT && c.f_a == -8 && c.f_b == 8 && c.half_us == 100 && c.dur_us == 1000 && c.pwr == 9);
    ERR("ALT 0 8 49 1000 9", "half"); ERR("ALT 0 8 2000 1000 9", "half>dur");
    ERR("ALT 0 8 50 20000 9", "transitions");  /* 400 > 255 */
    assert(P("ALT 0 8 50 12750 9").kind == CMD_ALT); /* 255 ok */
    ERR("ALT 0 8 50 12800 9", "transitions");
    ERR("ALT 0 600 100 1000 9", "freq"); ERR("ALT 0 8 100", "args");
    c = P("TONE 0 1000"); assert(c.kind == CMD_TONE && c.pwr == PWR_MAX); /* omitted pwr = PWR_MAX */
    c = P("ALT 0 8 100 1000"); assert(c.kind == CMD_ALT && c.pwr == PWR_MAX);
    c = P("PKT 1142b2000001cacacaca8888cacacaca8888"); assert(c.kind == CMD_PKT && c.pwr == PWR_MAX);
    ERR("HOP 5 10 300", "args");
#else
    /* release build: bench commands refused before any argument check, with or without pwr */
    ERR("TONE 0 1000 5", "bench-only"); ERR("TONE 0 1000", "bench-only"); ERR("ALT 0 8 100 1000 5", "bench-only");
    ERR("RETUNE 2441000", "bench-only"); ERR("PKT 1142b2000001cacacaca8888cacacaca8888 5", "bench-only");
    ERR("HOP 5 5", "bench-only"); ERR("HOP 5", "bench-only"); ERR("TCAP 2412000 2000 50 64 5", "bench-only");
    assert(P("TONE 0 1000 5").legacy && !P("TCAP 2412000 2000 50 64 5").legacy);
    assert(!strcmp(err_code("bench-only"), "bench-only")); /* v1 reply: ERR bench-only bench build required */
    assert(P("TCAP 2440000").kind == CMD_TCAP && P("TCAP 2440000 2000 50 64 -1").kind == CMD_TCAP && P("HOP 0 20").kind == CMD_HOP);
#endif
    ERR("KEY", "cmd"); ERR("tone 0 1000", "cmd");
    ERR("A B C D E F G H I J K L M", "args");
    c = P("FOFS -63000"); assert(c.kind == CMD_FOFS && c.hz == -63000);
    assert(P("FOFS 200000").hz == 200000 && P("FOFS 0").kind == CMD_FOFS);
    ERR("FOFS 200001", "hz"); ERR("FOFS -200001", "hz"); ERR("FOFS x", "hz"); ERR("FOFS", "args");
#if D8_BENCH
    c = P("HOP 5"); assert(c.kind == CMD_HOP && c.n_slots == 5 && c.pwr == PWR_MAX);
    c = P("HOP 5 127"); assert(c.kind == CMD_HOP && c.n_slots == 5 && c.pwr == 127);
#endif
    ERR("HOP 0", "args"); ERR("HOP 0 5 0", "timeout");
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
    ERR("TLM 47 10000 40 32 2", "same"); ERR("TLM 47 6001 40 16", "cap_us"); ERR("TLM 1 2 3 4 5 6 7 8 9 10 11 12 13", "args");
    c = P("TLM 48 9000 40 32 0 1 1"); assert(c.kind == CMD_TLM && c.stream == 1 && c.ack == 1 && c.cap_us == 9000);
    c = P("TLM 48"); assert(c.stream == 0 && c.ack == 0 && c.skip_us == 0 && c.bits == 8);
    c = P("TLM 8 8600 40 64 0 1 1 0 1 1000 4"); assert(c.kind == CMD_TLM && c.skip_us == 1000 && c.bits == 4 && c.dec == 64);
    ERR("TLM 8 8600 40 64 0 1 1 0 1 1000 5", "bits"); ERR("TLM 8 8600 40 64 0 1 1 0 1 8200", "skip");
    ERR("TLM 8 8600 40 64 0 0 0 0 0 1000", "skip"); ERR("TLM 8 8600 40 64 0 0 0 0 0 0 4", "skip");
    c = P("TLM 48 9000 40 32 0 1 1 1 2"); assert(c.kind == CMD_TLM && c.mark == 1 && c.retry == 2);
    c = P("TLM 48 9000 40 32 0 1 1"); assert(c.mark == 0 && c.retry == 0);
    ERR("TLM 48 9000 40 32 0 1 1 2", "mark"); ERR("TLM 48 9000 40 32 0 1 1 0 4", "retry"); ERR("TLM 48 9000 40 32 0 0 1 0 1", "retry");
    c = P("TLMX 8 50"); assert(c.kind == CMD_TLMX && c.tail_bits == 8 && c.settle_us == 50 && c.tail_all == 0);
    c = P("TLMX 0 0 1"); assert(c.kind == CMD_TLMX && c.tail_all == 1 && c.probe == 0);
    c = P("TLMX 0 0 0 1"); assert(c.kind == CMD_TLMX && c.tail_all == 0 && c.probe == 1);
    ERR("TLMX 0 0 0 2", "probe");
    ERR("TLMX 33 0", "tail"); ERR("TLMX 0 301", "settle"); ERR("TLMX 0 0 2", "all"); ERR("TLMX 1", "args");
    ERR("TLM 48 9000 40 32 0 2", "stream"); ERR("TLM 48 9000 40 32 0 1 2", "ack");
    c = P("TID 31"); assert(c.kind == CMD_TID && c.tid == 31);
    c = P("TID 0"); assert(c.kind == CMD_TID && c.tid == 0);
    ERR("TID 32", "tid"); ERR("TID -1", "tid"); ERR("TID", "args"); ERR("TID 1 2", "args");
    assert(!P("TLM 3").legacy && !strcmp(err_code("every"), "range"));
    c = P("TCAP 2440000"); assert(c.kind == CMD_TCAP && c.khz == 2440000 && c.pwr == -1 && c.cap_us == 10000 && c.dec == 32);
#if D8_BENCH
    c = P("TCAP 2412000 2000 50 64 127"); assert(c.kind == CMD_TCAP && c.cap_us == 2000 && c.gain == 50 && c.dec == 64 && c.pwr == 127);
    ERR("TCAP 2412000 2000 50 64 128", "pwr");
#endif
    ERR("TCAP 2403999", "khz"); ERR("TCAP", "args");
    assert(PWR_MAX >= 0 && PWR_MAX <= 127);
    ERR("LINK 128", "pwr"); ERR("HOP 0 128", "pwr"); ERR("BIND 128", "pwr");
    assert(P("LINK 127").kind == CMD_LINK || PWR_MAX < 127); /* cap applies to LINK/HOP 0/BIND alike */
    /* ID / BIND (OTA bind) */
    c = P("ID"); assert(c.kind == CMD_ID && c.id_op == ID_GET);
    c = P("ID new"); assert(c.kind == CMD_ID && c.id_op == ID_NEW);
    c = P("ID 42b2 2 55"); assert(c.kind == CMD_ID && c.id_op == ID_SET && c.ident.id0 == 0x42 && c.ident.id1 == 0xb2 && c.ident.start == 2 && c.ident.step == 55);
    c = P("ID 42B2 2 55"); assert(c.kind == CMD_ID && c.ident.id1 == 0xb2);
    c = P("ID 0000 7 86"); assert(c.kind == CMD_ID && c.id_op == ID_SET);
    ERR("ID NEW", "args"); ERR("ID x", "args"); ERR("ID 42b2 2", "args"); ERR("ID 42b2 2 55 1", "args");
    ERR("ID 42b 2 55", "txid"); ERR("ID 42b2a 2 55", "txid"); ERR("ID 42g2 2 55", "txid");
    ERR("ID 42b2 256 55", "start"); ERR("ID 42b2 -1 55", "start"); ERR("ID 42b2 2 0", "step"); ERR("ID 42b2 2 256", "step");
    ERR("ID 42b2 2 128", "hop_table"); ERR("ID 42b2 0 1", "hop_table");
    assert(!strcmp(err_code("txid"), "range") && !strcmp(err_code("hop_table"), "range") && !P("ID x").legacy);
    c = P("BIND"); assert(c.kind == CMD_BIND && c.pwr == PWR_MAX);
    c = P("BIND 20"); assert(c.kind == CMD_BIND && c.pwr == 20);
    ERR("BIND 128", "pwr"); ERR("BIND x", "pwr"); ERR("BIND 1 2", "args");
    puts(D8_BENCH ? "cmd_parse tests ok (bench)" : "cmd_parse tests ok (release)");
    return 0;
}
