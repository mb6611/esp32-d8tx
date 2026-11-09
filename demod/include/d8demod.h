/* FrSky D8 telemetry-reply demodulator (port of python/d8tx/demod.py + telemetry.decode_capture).
 * Pure C99: no malloc, no OS calls, no globals. Libm used: atan2f, sinf, cosf, floorf. */
#ifndef D8DEMOD_H
#define D8DEMOD_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define D8_PKT_BYTES 20 /* length byte + 17 payload + 2 CRC (bytes 0..17 are the 0x11 frame) */

typedef struct {
    uint8_t txid[2]; /* accepted bind id; default 66,178 */
    int has_hint;    /* try hint_hz first in the shift search */
    float hint_hz;
} d8_opts;

typedef struct d8_work d8_work; /* opaque; caller-owned, 8-byte aligned, d8_work_size(n_pairs) bytes */

typedef struct {
    uint8_t pkt[D8_PKT_BYTES];
    int32_t crc_ok;
    float cfo_hz;   /* burst carrier offset incl. shift_hz */
    float shift_hz; /* search shift that decoded */
    float t_ms;     /* preamble start */
} d8_result;

void d8_opts_default(d8_opts *o);
size_t d8_work_size(size_t n_pairs);

/* iq: int8 interleaved I,Q (Q negated inside). Returns 1 = packet found (out filled), 0 = none, <0 = bad args. */
int d8_decode(const int8_t *iq, size_t n_pairs, float fs, const d8_opts *o, d8_work *w, d8_result *out);

#ifdef __cplusplus
}
#endif
#endif
