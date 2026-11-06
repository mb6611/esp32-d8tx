#ifndef D8_PACKET_H
#define D8_PACKET_H
#include <stddef.h>
#include <stdint.h>
/* D8 CC2500: four preamble bytes, two sync bytes, length + 17 payload + CRC. */
#define D8_BODY_BYTES 18u
#define D8_PACKET_BYTES 20u
#define D8_AIR_BYTES 26u
#define D8_AIR_BITS (D8_AIR_BYTES * 8u)
#define D8_BIT_CYCLES 7731u /* 240 MHz / 31,044.006 baud = 7730.96; fixed 7731 cycles/bit (~8 cycles drift over 208 bits) */
uint16_t d8_crc(const uint8_t *bytes, size_t n);
/* n=18 appends CRC, n=20 preserves supplied CRC verbatim. Reject bad length byte. */
int d8_air_bytes(const uint8_t *packet, size_t n, uint8_t out[D8_AIR_BYTES]);
#endif
