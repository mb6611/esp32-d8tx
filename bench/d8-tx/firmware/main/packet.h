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

/* Hopping helpers (pure; mirrors host/esp32sdr/d8.py build_packet and hopfollow.D8_TABLE). */
#define D8_HOP_CHANNELS 47u
#define D8_STICKS 8u
#define D8_TXID0 0x42
#define D8_TXID1 0xb2
#define D8_STICK_US_MIN 800
#define D8_STICK_US_MAX 2200
/* Table: entry 0 = 0, entry i>=1 = (start + step*i) & 0xff (start 2, step 55 = E8 table). */
void d8_hop_table(unsigned start, unsigned step, uint8_t out[D8_HOP_CHANNELS]);
/* Carrier of CC2500 channel n in units of 10 Hz: 2404 MHz + n * 299.93 kHz. */
uint32_t d8_channel_f10(unsigned n);
/* us -> raw 12-bit channel value (Betaflight scales raw by 2/3 to us), rounded, clamped 0..4095. */
uint16_t d8_us_to_raw(int us);
/* Length byte + 17 payload bytes (no CRC): id, [3]=0, counter at [4], [5]=1 (same as host d8_vectors.build), 8 channels
 * (low bytes at 6,7,8,9,12,13,14,15; high nibbles at 10,11,16,17). */
void d8_build_body(uint8_t id0, uint8_t id1, uint8_t counter, const uint16_t raw[D8_STICKS],
                   uint8_t out[D8_BODY_BYTES]);
/* Telemetry request (Betaflight cc2500_frsky_d.c: reply when byte[3] % 4 == 2; byte[4] is the telemetry id
 * it echoes in frame[7] and checks against its expected hub ack id, (last + 1) & 0x1f). */
#define D8_TLM_REQ 0x02u
void d8_mark_telemetry(uint8_t body[D8_BODY_BYTES], uint8_t tid);
#endif
