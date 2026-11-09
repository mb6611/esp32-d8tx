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
#define D8_STICK_US_MIN 800
#define D8_STICK_US_MAX 2200
/* Table: entry 0 = 0, entry i>=1 = (start + step*i) & 0xff (start 2, step 55 = E8 table). */
void d8_hop_table(unsigned start, unsigned step, uint8_t out[D8_HOP_CHANNELS]);

/* Per-ESP identity (protocol/PROTOCOL.md "Bind"): txid + hop table d8_hop_table(start, step). */
typedef struct { uint8_t id0, id1, start, step; } d8_ident_t;
#define D8_HOP_CH_MAX 246u      /* highest usable channel: 2477.78 MHz, inside RETUNE_KHZ_MAX */
#define D8_GEN_CH_MAX 234u      /* generated identities stay in the reference TX range (< 0xeb) */
/* Accepted by "ID XXXX S T" (any txid, so existing bindings can be cloned): step != 0, entries 1..46 distinct and
 * each in 2..D8_HOP_CH_MAX (0 = bind channel and list end, 1 = bind byte 17, see d8_build_bind). E8's 42b2 2 55 passes. */
int d8_ident_valid(const d8_ident_t *id);
/* Stricter rule for generated identities: valid, entries <= D8_GEN_CH_MAX, none 0x5a / 0xdc (Multiprotocol
 * Frsky_init_hop filter), txid0 not 0x00 / 0x03 (bind address) / 0xff. */
int d8_ident_good(const d8_ident_t *id);
/* Draws from rnd until d8_ident_good (bounded; falls back to a fixed good identity). */
void d8_ident_generate(uint32_t (*rnd)(void), d8_ident_t *out);

/* Bind packet (Multiprotocol FrSkyD_build_bind_packet; Betaflight getBind1/getBind2): 11 03 01 id0 id1 idx
 * hop[idx..idx+4] 00 00 00 00 00 00 01. Entries at index >= 47 are 0 (list end). idx = 0,5,..,45. */
#define D8_BIND_IDX_STEP 5u
#define D8_BIND_IDX_MAX 45u
#define D8_BIND_BYTE17 0x01u
void d8_build_bind(uint8_t id0, uint8_t id1, unsigned idx, const uint8_t hop[D8_HOP_CHANNELS], uint8_t out[D8_BODY_BYTES]);
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
/* On-chip "did the drone reply?" check on a telemetry capture (interleaved int16 I,Q boxcar sums of dec pairs at
 * 16 MS/s, capture starting ~0.2-0.4 ms after unkey). The reply runs ~1.3-8.1 ms into the capture with a constant
 * envelope, so count the 0.5 ms blocks in 2.0-7.5 ms whose mean I^2+Q^2 exceeds D8_REPLY_POW (scaled by (dec/32)^2).
 * Returns that count; *fit = blocks inside the capture (11 at 7.5+ ms). d8_reply_seen: at most 2 quiet blocks of >= 4.
 * Offline over 586 captures of 2026-11-07 (dec 32, 11 blocks): every reply 11, every no-reply <= 8
 * (interference bursts are <= 2.6 ms). */
#define D8_REPLY_BLOCKS 11u
#define D8_REPLY_POW 200000u
unsigned d8_reply_blocks(const int16_t *iq, unsigned n_out, unsigned dec, unsigned *fit);
static inline int d8_reply_seen(unsigned nb, unsigned fit) { return fit >= 4u && nb + 2u >= fit; }
#endif
