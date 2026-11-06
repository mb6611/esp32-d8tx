/* Pure command-line parser for the d8tone bench app (no hardware access; host-testable). */
#ifndef CMD_PARSE_H
#define CMD_PARSE_H
#include <stdint.h>
#include "packet.h"

#define TONE_F_MAX      511        /* |f| in ROM tone-step units (signed 12-bit field when b8 bit29 set) */
#define TONE_DUR_MAX_US 200000u
#define TONE_DUR_MIN_US 50u
#define ALT_HALF_MIN_US 50u
#define ALT_MAX_TRANS   255u       /* transitions recorded per window */
#define PWR_MAX         127
#define RETUNE_KHZ_MIN  2404000    /* D8 channel span only */
#define RETUNE_KHZ_MAX  2478000
#define RETUNE_TONE_MAX_US 150000u /* TONE after RETUNE (off the 2412 baseline) is capped */
#define HOP_SLOTS_MAX   (D8_HOP_CHANNELS * 20u)

typedef enum { CMD_NONE, CMD_PING, CMD_STAT, CMD_UNKEY, CMD_TONE, CMD_ALT, CMD_PKT, CMD_RETUNE, CMD_HOP, CMD_STICKS, CMD_ERR } cmd_kind_t;

typedef struct {
    cmd_kind_t kind;
    int f_a, f_b;          /* tone step units; TONE uses f_a */
    uint32_t half_us, dur_us;
    uint8_t packet[D8_PACKET_BYTES];
    unsigned packet_len; /* length+payload, optionally supplied CRC */
    int khz;               /* RETUNE */
    unsigned n_slots;      /* HOP */
    int sticks[D8_STICKS]; /* STICKS, microseconds */
    int pwr;               /* PBUS (5,1) value 0..127 */
    const char *err;       /* set for CMD_ERR */
} cmd_t;

/* Parses one line (modified in place). Never returns a keying command unless every field is valid. */
cmd_t cmd_parse(char *line);

#endif
