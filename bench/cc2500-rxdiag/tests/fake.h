// Fake CC2500 + tracing HAL for rxdiag core tests and rxdiag_sim.
#ifndef FAKE_H
#define FAKE_H
#include <stdbool.h>
#include <stdint.h>
#include "rxdiag_core.h"

typedef struct fake_s fake_t;
typedef void (*fakeLineHook_t)(fake_t *f, const char *line);

enum { RSSI_CONST = 0, RSSI_RAMP = 1, RSSI_STEP = 2 };

#define FAKE_MAXLINES 20000
#define FAKE_HEAD 64

struct fake_s {
    // ---- clock
    bool real;            // true: monotonic clock and busy-wait frame time (sim)
    uint64_t now;         // virtual clock, microseconds
    uint32_t frameUs;     // time consumed per SPI frame / micros() call
    uint64_t realStart;
    // ---- chip
    uint8_t reg[0x40];
    uint8_t state;        // MARCSTATE value
    uint64_t rxAtUs;      // time at which CAL completes
    uint32_t calDelayUs;
    bool resetBad, rbBad, neverRx;
    uint64_t estateAt;    // 0 = none; at that time state drops to 0x11 (once)
    bool estateDone, estateStuck;
    uint64_t disagreeFrom, disagreeTo;
    int rssiMode;
    int8_t rssiConst;
    int8_t stepOff, stepOn;
    uint64_t stepOnAt, stepOffAt; // RSSI_STEP: ON in [stepOnAt, stepOffAt)
    uint32_t rssiToggle;
    // ---- scripted HAL events (tests)
    uint64_t rxAt;        // rx byte becomes available at this time (0 = none)
    uint32_t rxCount;
    uint64_t usbDownAt;   // 0 = never
    uint64_t txFailFrom, txFailUntil; // txTry fails while from<=now<until
    // ---- trace
    uint64_t frames;
    uint32_t violations;
    char vmsg[128];
    uint8_t headHdr[FAKE_HEAD], headData[FAKE_HEAD], headKind[FAKE_HEAD]; // kind: 'R','W','S'
    uint8_t lastHdr, lastKind;
    bool lna, lnaEverOn, lnaCalled;
    uint32_t lnaOnCount;
    bool sawFreq1Ok, sawRbOk;
    bool drained, drainCalled;
    uint32_t rssiReads, rssiSincePoll, maxRssiBetweenPolls;
    uint32_t rxPolls;
    bool firstRssiSeen;
    uint32_t rssiAfterRx;     // rssi reads since rxAt became visible
    bool rxVisibleSeen;
    uint8_t status[0x40];
    // ---- events: GDO0 pin + both-edge capture model
    bool gdoUnwired;              // pin never follows GDO0 (reads 0)
    bool noGdoHal;                // HAL has no gdo functions
    int nb;                       // scripted bursts [bOn, bOff): RSSI = burstRssi, CS high while in RX
    uint64_t bOn[64], bOff[64];
    int8_t burstRssi;
    bool armed;
    uint64_t armedAt;
    uint32_t edgeNext;            // next edge index (2 per burst) to deliver
    uint32_t edgeSeen, edgeLost, lostInject;
    bool ant, antSetCalled;
    // ---- freq mode: carrier [fqOn, fqOff) in RX sets PKTSTATUS.CS and FREQEST=feVal (feStale otherwise)
    uint64_t fqOn, fqOff;
    int8_t feVal, feStale;
    bool feDisagree;              // FREQEST consecutive reads always differ
    uint32_t feToggle, feReads, pktReads;
    // ---- records
    char **lines;
    int nlines;
    fakeLineHook_t hook;
    void *hookUser;
    // optional overrides for sim
    uint32_t (*simRxWaiting)(void *);
    void (*simRxDrain)(void *);
    bool (*simUsb)(void *);
    bool (*simTx)(void *, const char *, uint32_t);
    void *simCtx;
};

void fakeInit(fake_t *f);
void fakeFree(fake_t *f);
void fakeHal(fake_t *f, rxdiagHal_t *hal);
uint64_t fakeNow(fake_t *f);
void fakeAdvance(fake_t *f, uint32_t us);
int8_t fakeRssiAt(fake_t *f, uint64_t t);
void fakeViolation(fake_t *f, const char *msg);
bool fakeInBurst(fake_t *f, uint64_t t);
#endif
