/* Short decimated I/Q capture for the telemetry-listen experiment (d8tone TLM / TCAP).
 *
 * Single-core port of the ring + bank ping-pong + sentinel scheme of the RX firmware's
 * main/targets/esp32/iq_stream.c (app-CPU part, c1_stream/finish_session/deliver): the capture
 * writer runs at 16 MS/s as an 8192-word ring, the CPU hands it bank 0 / bank 1 of the
 * 0x3ffe8000 window every TCAP_SESSION pairs and boxcar-sums the bank it owns into
 * dec-pair blocks (dec 16/32/64 -> 1 MS/s / 500 kS/s / 250 kS/s). The caller must hold
 * interrupts off for the whole run (busy-waits on the write pointer).
 *
 * The bank-rotation + sentinel scheme follows ESPARGOS esp-sdr main/common/ring_capture.c
 * (https://github.com/ESPARGOS/esp-sdr), which follows h0m3us3r/eSpDR capture.c; this is an
 * independent single-core implementation, not a copy of that code. */
#ifndef TLM_CAP_H
#define TLM_CAP_H
#include <stdint.h>

#define TCAP_RATE_HZ    16000000u
#define TCAP_MAX_OUT    6000u  /* output samples (int16 I,Q): 24 KiB */
#define TCAP_US_MIN     500u
#define TCAP_US_MAX     12000u

typedef struct {
    uint32_t pairs;      /* input pairs delivered to the boxcar */
    uint32_t lost;       /* input pairs missing (late switch, bad marks) */
    uint32_t bad;        /* sessions dropped: inconsistent marks */
    uint32_t units;      /* bank sessions finished */
    uint32_t late_max;   /* worst switch lateness, pairs */
    uint32_t work_max;   /* worst per-session CPU cycles (budget ~ 8064*15 = 120960) */
    uint32_t gain_first, gain_last; /* RX gain index (sample word >> 20) at the first/last session */
    uint32_t start_cyc;  /* CCOUNT right after the run bit was written (pair 0 ~ here) */
    uint32_t end_cyc;
    int timeout;         /* 1: the run hit its cycle cap */
} tcap_res_t;

/* Idle (interrupts on): CPU-owned window filled with marks, output zeroed. n_out <= TCAP_MAX_OUT. */
void tcap_prepare(unsigned n_out);
/* Capture n_out * dec pairs starting now; out = TCAP buffer (interleaved int16 I, Q). dec 16/32/64. */
void tcap_run(unsigned n_out, unsigned dec, tcap_res_t *r);
int16_t *tcap_buffer(void);

#endif
