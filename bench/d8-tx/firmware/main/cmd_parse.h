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
#define FOFS_HZ_MAX     200000     /* LO frequency offset, +/- Hz */
#define HOP_TIMEOUT_DEF_MS 300
#define HOP_TIMEOUT_MAX_MS 1000
#define S_US_MIN        1000   /* live S clamp */
#define S_US_MAX        2000
#define S_CH7_US_MAX    1300   /* ch7 (index 6, ARM) forced low unless ARMOK was sent before this HOP */
#define HOP_SLOTS_MAX   (D8_HOP_CHANNELS * 20u)

typedef enum { CMD_NONE, CMD_PING, CMD_STAT, CMD_UNKEY, CMD_TONE, CMD_ALT, CMD_PKT, CMD_RETUNE, CMD_HOP, CMD_STICKS, CMD_S, CMD_FOFS, CMD_ARMOK, CMD_INFO, CMD_LINK, CMD_ERR } cmd_kind_t;

typedef struct {
    cmd_kind_t kind;
    int f_a, f_b;          /* tone step units; TONE uses f_a */
    uint32_t half_us, dur_us;
    uint8_t packet[D8_PACKET_BYTES];
    unsigned packet_len; /* length+payload, optionally supplied CRC */
    int hz;                /* FOFS */
    int khz;               /* RETUNE */
    unsigned n_slots;      /* HOP; 0 = continuous */
    unsigned timeout_ms;   /* HOP 0: max gap between S updates */
    int sticks[D8_STICKS]; /* STICKS/S, microseconds */
    int pwr;               /* PBUS (5,1) value 0..127 */
    const char *err;       /* set for CMD_ERR: short reason text */
    int legacy;            /* CMD_ERR from a legacy bench command: print the old bare "ERR <why>" */
} cmd_t;

/* Parses one line (modified in place). Never returns a keying command unless every field is valid. */
cmd_t cmd_parse(char *line);

/* Protocol v1 error code (args|range|busy|keyed|unknown|long) for a parser reason text. */
const char *err_code(const char *why);

#endif
