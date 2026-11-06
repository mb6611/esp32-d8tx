// rxdiag core: CC2500 receive-only RSSI diagnostic. Implements interface-v1.md.
// C99, no Betaflight headers, no printf family, no allocation, no hardware addresses.
#ifndef RXDIAG_CORE_H
#define RXDIAG_CORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RXDIAG_PROTO 1

typedef struct rxdiagHal_s {
    void *ctx;
    uint8_t  (*spiRead)(void *ctx, uint8_t header);               // one CS frame: header, 0xFF; returns 2nd byte
    void     (*spiWrite)(void *ctx, uint8_t header, uint8_t data); // one CS frame: header, data
    void     (*spiStrobe)(void *ctx, uint8_t strobe);             // one CS frame: header only
    uint32_t (*micros)(void *ctx);
    void     (*delayUs)(void *ctx, uint32_t us);
    void     (*frontEnd)(void *ctx, bool lnaOn);                  // glue keeps TX_EN low always; ANT fixed high
    uint32_t (*rxWaiting)(void *ctx);
    void     (*rxDrain)(void *ctx);
    bool     (*usbConnected)(void *ctx);
    bool     (*txTry)(void *ctx, const char *buf, uint32_t len);  // all-or-nothing, non-blocking
    // ---- events mode (GDO0 -> MCU input pin). Any of these may be NULL: events then refuses (EGDO).
    int      (*gdoRead)(void *ctx);                               // current pin level 0/1, -1 = no pin
    bool     (*edgeArm)(void *ctx, bool on);                      // on: clear ring+counters, enable both-edge capture
    bool     (*edgePop)(void *ctx, uint32_t *tUs, uint8_t *level); // oldest captured edge (ISR timestamp, level after edge)
    void     (*edgeCounts)(void *ctx, uint32_t *edges, uint32_t *lost); // cumulative since arm: edges seen by ISR, ring overflows
    void     (*antSet)(void *ctx, bool high);                     // diversity select used by frontEnd (default high)
} rxdiagHal_t;

typedef struct rxdiagBoard_s {
    const char *fw, *bf, *cs, *exti, *txen, *lna, *ant, *motorProto;   // "none" where absent
    uint8_t spiBus; uint16_t spiDiv; uint32_t spiHz; bool motorDevNull; int32_t vbatCv;
} rxdiagBoard_t;

typedef enum { RXDIAG_DONE = 0, RXDIAG_ERR_ARG, RXDIAG_ERR_REFUSED, RXDIAG_EXIT_HOST,
               RXDIAG_EXIT_USB, RXDIAG_EXIT_USBSTALL, RXDIAG_EXIT_RADIO } rxdiagResult_e;

// args: text after "rxdiag " (e.g. "info", "stream 2440000 10 812" or
// "events <freq_khz> [window_ms] [bw] [agcctrl2] [agcctrl1] [ant]", see stage4/results/U5-burst/README.md).
#define RXDIAG_EV_PROTO 2
#define RXDIAG_FREQ_PROTO 3   // "freq <freq_khz> [window_ms] [bw] [agcctrl2] [agcctrl1] [duration_ms]"
rxdiagResult_e rxdiagRun(const rxdiagHal_t *hal, const rxdiagBoard_t *board, const char *args);
bool     rxdiagFreqWord(uint32_t freqKhz, uint32_t *word, uint32_t *setHz, bool *spur);
bool     rxdiagBwLookup(uint32_t bwLabelKhz, uint8_t *mdmcfg4, uint32_t *bwHz);
bool     rxdiagWindowValid(uint32_t windowMs);
bool     rxdiagDurationValid(uint32_t durationMs);
int32_t  rxdiagFreqEstHz(int32_t raw);   // FREQEST LSB = 26 MHz / 2^14
bool     rxdiagStatusHeader(uint8_t addr, uint8_t *header);
uint64_t rxdiagMicros64(uint64_t prev64, uint32_t now32);
// Test entry; the stream path uses the same aggregator. Returns line length excluding CRLF (no CRLF written),
// or 0 if it does not fit (cap includes the terminating NUL).
size_t   rxdiagFormatS(char *out, size_t cap, uint32_t seq, uint64_t tUs, const int8_t *samples, uint32_t count, uint8_t marc, uint8_t flags);

#endif
