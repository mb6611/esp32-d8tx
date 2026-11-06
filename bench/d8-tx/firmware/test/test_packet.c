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
    puts("packet tests ok");
}
