#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../main/packet.h"
#include "../main/cmd_parse.h"

#include "bf_bind_port.h"
/* Firmware BIND schedule: idx 0,5,..,45 cycling from start_idx; returns frames fed until the RX finished. */
static unsigned bf_bind(bf_rx_t *r, const d8_ident_t *id, unsigned start_idx) {
    uint8_t tab[D8_HOP_CHANNELS], body[D8_BODY_BYTES];
    d8_hop_table(id->start, id->step, tab);
    bf_init(r);
    unsigned idx = start_idx, k;
    for (k = 0; k < 200 && r->state != 3; k++) {
        d8_build_bind(id->id0, id->id1, idx, tab, body);
        bf_feed(r, body);
        idx = idx >= D8_BIND_IDX_MAX ? 0 : idx + D8_BIND_IDX_STEP;
    }
    return k;
}
static void check_bind(const d8_ident_t *id, unsigned start_idx) {
    bf_rx_t r;
    unsigned k = bf_bind(&r, id, start_idx);
    uint8_t tab[D8_HOP_CHANNELS]; d8_hop_table(id->start, id->step, tab);
    assert(r.state == 3 && r.list_len == 47 && r.txid[0] == id->id0 && r.txid[1] == id->id1 && r.rxnum == 0);
    assert(!memcmp(r.hop, tab, D8_HOP_CHANNELS));
    assert(r.hop[47] == 0 && r.hop[48] == 0 && r.hop[49] == 0);
    assert(k <= 20); /* <= two idx cycles (~180 ms at 8994 us) */
}
static uint32_t lcg_state = 12345;
static uint32_t lcg(void) { lcg_state = lcg_state * 1103515245u + 12345u; return lcg_state ^ (lcg_state >> 16) * 0x9e3779b9u; }

static cmd_t parse(const char *s) {
    char buf[96]; assert(strlen(s) < sizeof buf); strcpy(buf, s); return cmd_parse(buf);
}
int main(void) {
    /* U3 tools/d8-tx-host/d8_vectors.py build(0), captured-E8 id and 2250 channels. */
    const char *hex = "1142b2000001cacacaca8888cacacaca8888";
    char line[96]; snprintf(line, sizeof line, "PKT %s", hex);
#if !D8_BENCH
    /* release build: bench commands are refused with "bench-only" even when well formed. */
    snprintf(line, sizeof line, "PKT %s 5", hex); assert(!strcmp(parse(line).err, "bench-only"));
    assert(!strcmp(parse("HOP 5 100").err, "bench-only") && !strcmp(parse("RETUNE 2441000").err, "bench-only"));
    assert(parse("HOP 0 64").kind == CMD_HOP && parse("LINK 64").kind == CMD_LINK);
#else
    assert(parse(line).kind == CMD_PKT && parse(line).pwr == PWR_MAX); /* omitted pwr = PWR_MAX */
    snprintf(line, sizeof line, "PKT %s 127", hex);
    cmd_t c = parse(line); assert(c.kind == CMD_PKT && c.packet_len == 18 && c.pwr == 127);
    uint8_t air[D8_AIR_BYTES]; assert(d8_air_bytes(c.packet, c.packet_len, air));
    assert(!memcmp(air, "\xaa\xaa\xaa\xaa\xd3\x91", 6));
    assert(!memcmp(air + 6, c.packet, 18));
    assert(air[0] == 0xaa && (air[4] & 0x80) && !(air[4] & 0x20)); /* MSB-first d3 = 11010011 */
    uint16_t crc = d8_crc(c.packet, 18);
    assert(air[24] == (crc >> 8) && air[25] == (crc & 255));
    assert(!memcmp(air, "\xaa\xaa\xaa\xaa\xd3\x91\x11\x42\xb2\x00\x00\x01\xca\xca\xca\xca\x88\x88\xca\xca\xca\xca\x88\x88\xaf\xa7", D8_AIR_BYTES));
    snprintf(line, sizeof line, "PKT %s%02x%02x 0", hex, air[24], air[25]);
    c = parse(line); assert(c.kind == CMD_PKT && c.packet_len == 20 && c.pwr == 0);
    uint8_t full[D8_AIR_BYTES]; assert(d8_air_bytes(c.packet, c.packet_len, full));
    assert(!memcmp(full, air, sizeof air));
    /* A full host vector is transmitted verbatim even with an intentionally bad CRC. */
    line[strlen(line)-3] = 'f';
    c = parse(line); assert(c.kind == CMD_PKT);
    assert(d8_air_bytes(c.packet, c.packet_len, full));
    assert(memcmp(full, air, sizeof air));
    assert(parse("PKT 11").kind == CMD_ERR);
    assert(parse("PKT 1142b2000001cacacaca8888cacacaca8888f").kind == CMD_ERR);
    assert(parse("PKT 1142b2000001cacacaca8888cacacaca8888afa700").kind == CMD_ERR);
    assert(parse("PKT 0042b2000001cacacaca8888cacacaca8888").kind == CMD_ERR);
    assert(parse("PKT 1142b2000001cacacaca8888cacacaca888g").kind == CMD_ERR);
    snprintf(line, sizeof line, "PKT %s 128", hex); assert(parse(line).kind == CMD_ERR);
    snprintf(line, sizeof line, "PKT %s 127", hex); assert(parse(line).kind == CMD_PKT);
#endif
    /* Hop table = hopfollow.D8_TABLE; body/CRC = host d8_vectors.build. */
    static const uint8_t e8[47] = {0, 57, 112, 167, 222, 21, 76, 131, 186, 241, 40, 95, 150, 205, 4, 59, 114, 169, 224, 23,
        78, 133, 188, 243, 42, 97, 152, 207, 6, 61, 116, 171, 226, 25, 80, 135, 190, 245, 44, 99,
        154, 209, 8, 63, 118, 173, 228};
    uint8_t tab[D8_HOP_CHANNELS]; d8_hop_table(2, 55, tab); assert(!memcmp(tab, e8, sizeof e8));
    assert(d8_channel_f10(0) == 240400000u && d8_channel_f10(245) / 100 < 2478000u);
    assert(d8_us_to_raw(1500) == 2250 && d8_us_to_raw(1000) == 1500 && d8_us_to_raw(2200) == 3300);
    uint16_t raw[8] = {2250, 2250, 2250, 2250, 2250, 2250, 2250, 2250};
    uint8_t body[D8_BODY_BYTES]; d8_build_body(0x42, 0xb2, 0, raw, body);
    assert(!memcmp(body, "\x11\x42\xb2\x00\x00\x01\xca\xca\xca\xca\x88\x88\xca\xca\xca\xca\x88\x88", 18));
    uint16_t r2[8] = {1500, 2250, 3000, 4095, 1, 0x123, 0xabc, 0x800};
    d8_build_body(0x42, 0xb2, 0x35, r2, body);
    static const uint8_t v2[20] = {0x11,0x42,0xb2,0x00,0x35,0x01,0xdc,0xca,0xb8,0xff,0x85,0xfb,0x01,0x23,0xbc,0x00,0x10,0x8a,0x4a,0xf6};
    assert(!memcmp(body, v2, 18) && d8_crc(body, 18) == 0x4af6);
#if D8_BENCH
    {
        cmd_t k = parse("RETUNE 2441000"); assert(k.kind == CMD_RETUNE && k.khz == 2441000);
        assert(parse("RETUNE 2403999").kind == CMD_ERR && parse("RETUNE 2478001").kind == CMD_ERR);
        assert(parse("RETUNE").kind == CMD_ERR && parse("RETUNE 24x").kind == CMD_ERR);
        k = parse("HOP 940 100"); assert(k.kind == CMD_HOP && k.n_slots == 940 && k.pwr == 100);
        assert(parse("HOP 5").kind == CMD_HOP && parse("HOP 5").pwr == PWR_MAX);
        assert(parse("HOP 941").kind == CMD_ERR && parse("HOP 0").kind == CMD_ERR && parse("HOP 5 128").kind == CMD_ERR);
        assert(parse("HOP").kind == CMD_ERR && parse("HOP 5 1 2").kind == CMD_ERR);
    }
#endif
    {
        cmd_t k;
        k = parse("STICKS 1500 1500 1000 2000 1500 1500 1500 1500");
        assert(k.kind == CMD_STICKS && k.sticks[2] == 1000 && k.sticks[3] == 2000);
        assert(parse("STICKS 1500 1500 1000 2000 1500 1500 1500").kind == CMD_ERR);
        assert(parse("STICKS 1500 1500 1000 2000 1500 1500 1500 2201").kind == CMD_ERR);
        assert(parse("STICKS 1500 1500 1000 2000 1500 1500 1500 799").kind == CMD_ERR);
    }
    puts("packet tests ok");
    { /* telemetry request marker: byte3 = 2, byte4 = tid & 0x1f, rest unchanged */
        uint16_t raw[D8_STICKS] = {2250, 2250, 2250, 2250, 2250, 2250, 2250, 2250};
        uint8_t a[D8_BODY_BYTES], b[D8_BODY_BYTES];
        d8_build_body(0x42, 0xb2, 77, raw, a);
        memcpy(b, a, sizeof b);
        d8_mark_telemetry(b, 33);
        assert(b[3] == 2 && b[4] == 1 && b[3] % 4 == 2);
        for (unsigned i = 0; i < D8_BODY_BYTES; i++) if (i != 3 && i != 4) assert(a[i] == b[i]);
    }
    { /* reply detector: full-window tone -> 11, silence -> 0, 2.5 ms burst -> < D8_REPLY_MIN, short capture clipped */
        static int16_t iq[2 * 4500];
        unsigned fit;
        memset(iq, 0, sizeof iq);
        assert(d8_reply_blocks(iq, 4500, 32, &fit) == 0);
        for (unsigned i = 0; i < 4500; i++) { iq[2 * i] = (int16_t)((i & 1) ? 1500 : -1500); iq[2 * i + 1] = 300; }
        assert(d8_reply_blocks(iq, 4500, 32, &fit) == D8_REPLY_BLOCKS && fit == D8_REPLY_BLOCKS);
        assert(d8_reply_blocks(iq, 2000, 32, &fit) == 4); /* 4.0 ms capture: only the 2.0-4.0 ms blocks fit */
        memset(iq, 0, sizeof iq);
        for (unsigned i = 1000; i < 1000 + 1250; i++) iq[2 * i] = 2000; /* 2.5 ms burst at 2 ms */
        assert(d8_reply_blocks(iq, 4500, 32, &fit) == 5);
        for (unsigned i = 0; i < 4500; i++) iq[2 * i] = (int16_t)(i & 1 ? 30 : -30); /* noise-level floor */
        assert(d8_reply_blocks(iq, 4500, 32, &fit) == 0);
        static int16_t iq16[2 * 6000];
        for (unsigned i = 0; i < 6000; i++) { iq16[2 * i] = 750; iq16[2 * i + 1] = 0; } /* dec 16: half the amplitude */
        assert(d8_reply_blocks(iq16, 6000, 16, &fit) == 8 && fit == 8 && d8_reply_seen(8, fit)); /* 6 ms max at dec 16 */
        assert(d8_reply_seen(11, 11) && d8_reply_seen(9, 11) && !d8_reply_seen(8, 11) && !d8_reply_seen(3, 3) && !d8_reply_seen(5, 8));
    }
    puts("reply detector tests ok");
    { /* bind packet: Multiprotocol FrSkyD comment capture (real FrSky TX) "11 03 01 d7 2d 00 00 1e 3c 5b 78 00 00 00 00 00 00 01" */
        uint8_t hop[D8_HOP_CHANNELS] = {0x00, 0x1e, 0x3c, 0x5b, 0x78}, b[D8_BODY_BYTES];
        d8_build_bind(0xd7, 0x2d, 0, hop, b);
        assert(!memcmp(b, "\x11\x03\x01\xd7\x2d\x00\x00\x1e\x3c\x5b\x78\x00\x00\x00\x00\x00\x00\x01", 18));
        /* hand-checked E8 identity (42b2, start 2, step 55): hop 0,57,112,167,222 | 45: 173, 46: 228, then 0s */
        uint8_t tab[D8_HOP_CHANNELS]; d8_hop_table(2, 55, tab);
        d8_build_bind(0x42, 0xb2, 0, tab, b);
        assert(!memcmp(b, "\x11\x03\x01\x42\xb2\x00\x00\x39\x70\xa7\xde\x00\x00\x00\x00\x00\x00\x01", 18));
        d8_build_bind(0x42, 0xb2, 45, tab, b);
        assert(!memcmp(b, "\x11\x03\x01\x42\xb2\x2d\xad\xe4\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01", 18));
        d8_build_bind(0x42, 0xb2, 40, tab, b);
        assert(b[5] == 40 && b[6] == tab[40] && b[10] == tab[44]);
        uint8_t air[D8_AIR_BYTES]; assert(d8_air_bytes(b, 18, air) && air[7] == 0x03);
        /* identity rules */
        d8_ident_t e8 = {0x42, 0xb2, 2, 55}, bad;
        assert(d8_ident_valid(&e8) && !d8_ident_good(&e8)); /* E8 table reaches 245 > D8_GEN_CH_MAX: clone-only */
        bad = e8; bad.step = 0; assert(!d8_ident_valid(&bad));
        bad = e8; bad.step = 128; assert(!d8_ident_valid(&bad));                  /* repeats */
        bad = e8; bad.start = 255; bad.step = 1; assert(!d8_ident_valid(&bad));   /* entry 1 = 0 */
        bad = e8; bad.start = 0; bad.step = 1; assert(!d8_ident_valid(&bad));     /* entry 1 = 1 (bind byte 17) */
        bad = e8; bad.start = 0; bad.step = 6; assert(!d8_ident_valid(&bad));     /* entry 42 = 252 > D8_HOP_CH_MAX */
        d8_ident_t fb = {0x5c, 0x31, 51, 73}; assert(d8_ident_good(&fb));         /* d8_ident_generate fallback */
        /* narrow tables that the old rule accepted (all 47 hops in a ~14 MHz slice) are no longer generated */
        d8_ident_t nar = {0x5c, 0x31, 94, 1}; assert(d8_ident_valid(&nar) && !d8_ident_good(&nar));
        nar.start = 165; nar.step = 254; assert(d8_ident_valid(&nar) && !d8_ident_good(&nar));
        nar.start = 47; nar.step = 3; assert(d8_ident_valid(&nar) && !d8_ident_good(&nar));
        nar = fb; nar.step = 86; nar.start = 7; assert(d8_ident_valid(&nar) && !d8_ident_good(&nar)); /* old fallback: gap 56 */
        unsigned ngood = 0;
        for (unsigned st = 0; st < 256; st++)
            for (unsigned sp = 0; sp < 256; sp++) {
                d8_ident_t t = {0x12, 0x34, (uint8_t)st, (uint8_t)sp};
                if (d8_ident_good(&t)) ngood++;
            }
        printf("good start/step pairs: %u\n", ngood);
        assert(ngood >= 100);
        unsigned nvalid = 0;
        for (unsigned st = 0; st < 256; st++)
            for (unsigned sp = 0; sp < 256; sp++) {
                d8_ident_t t = {0x12, 0x34, (uint8_t)st, (uint8_t)sp};
                if (!d8_ident_valid(&t)) continue;
                nvalid++;
                uint8_t h[D8_HOP_CHANNELS]; d8_hop_table(st, sp, h);
                for (unsigned i = 1; i < D8_HOP_CHANNELS; i++) assert(h[i] >= 2 && h[i] <= D8_HOP_CH_MAX && d8_channel_f10(h[i]) / 100 <= RETUNE_KHZ_MAX);
            }
        assert(nvalid > 1000);
        /* Betaflight acceptance: E8 identity and 200 generated ones, starting at every idx of the cycle */
        for (unsigned s0 = 0; s0 <= D8_BIND_IDX_MAX; s0 += D8_BIND_IDX_STEP) check_bind(&e8, s0);
        for (unsigned i = 0; i < 200; i++) {
            d8_ident_t g; d8_ident_generate(lcg, &g);
            assert(d8_ident_good(&g) && d8_ident_valid(&g));
            /* spread check, independent of d8_ident_good: consecutive hops >= 30 channels apart (cyclic, incl. entry 0),
             * entries span the band (lowest <= 34, highest >= 202) and no 33 consecutive channels are unused */
            uint8_t h[D8_HOP_CHANNELS]; d8_hop_table(g.start, g.step, h);
            unsigned lo = 255, hi = 0;
            for (unsigned k = 0; k < D8_HOP_CHANNELS; k++) {
                int d = (int)h[(k + 1) % D8_HOP_CHANNELS] - (int)h[k];
                assert(d >= 30 || d <= -30);
                if (k) { if (h[k] < lo) lo = h[k]; if (h[k] > hi) hi = h[k]; }
            }
            assert(lo <= 34 && hi >= 202);
            for (unsigned c = 2; c + 32 <= D8_GEN_CH_MAX; c++) {
                int any = 0;
                for (unsigned k = 1; k < D8_HOP_CHANNELS; k++) if (h[k] >= c && h[k] <= c + 32) any = 1;
                assert(any);
            }
            check_bind(&g, (i % 10) * 5);
        }
        /* a table whose entry 46 were 0 would end the list early in Betaflight: such identities are invalid */
        uint8_t t0[D8_HOP_CHANNELS]; d8_hop_table(2, 55, t0); t0[46] = 0;
        bf_rx_t r; bf_init(&r);
        for (unsigned idx = 0; idx <= 45; idx += 5) { uint8_t bb[D8_BODY_BYTES]; d8_build_bind(1, 2, idx, t0, bb); bf_feed(&r, bb); }
        assert(r.state == 3 && r.list_len == 46);
    }
    puts("bind tests ok");
    return 0;
}
