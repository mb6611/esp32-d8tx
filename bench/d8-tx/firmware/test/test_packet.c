#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../main/packet.h"
#include "../main/cmd_parse.h"

static cmd_t parse(const char *s) {
    char buf[96]; assert(strlen(s) < sizeof buf); strcpy(buf, s); return cmd_parse(buf);
}
int main(void) {
    /* U3 bench/d8-tx/host/d8_vectors.py build(0), captured-E8 id and 2250 channels. */
    const char *hex = "1142b2000001cacacaca8888cacacaca8888";
    char line[96]; snprintf(line, sizeof line, "PKT %s", hex);
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
    {
        cmd_t k = parse("RETUNE 2441000"); assert(k.kind == CMD_RETUNE && k.khz == 2441000);
        assert(parse("RETUNE 2403999").kind == CMD_ERR && parse("RETUNE 2478001").kind == CMD_ERR);
        assert(parse("RETUNE").kind == CMD_ERR && parse("RETUNE 24x").kind == CMD_ERR);
        k = parse("HOP 940 100"); assert(k.kind == CMD_HOP && k.n_slots == 940 && k.pwr == 100);
        k = parse("HOP 5"); assert(k.kind == CMD_HOP && k.pwr == 127);
        assert(parse("HOP 941").kind == CMD_ERR && parse("HOP 0").kind == CMD_ERR && parse("HOP 5 128").kind == CMD_ERR);
        assert(parse("HOP").kind == CMD_ERR && parse("HOP 5 1 2").kind == CMD_ERR);
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
        d8_build_body(D8_TXID0, D8_TXID1, 77, raw, a);
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
    return 0;
}
