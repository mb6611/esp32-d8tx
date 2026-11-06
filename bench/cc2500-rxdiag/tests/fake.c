#define _POSIX_C_SOURCE 200809L
#include "fake.h"
#include <stdlib.h>
#include <string.h>
#include <time.h>

static uint64_t monoUs(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}

uint64_t fakeNow(fake_t *f)
{
    return f->real ? monoUs() - f->realStart : f->now;
}

void fakeAdvance(fake_t *f, uint32_t us)
{
    if (!f->real) {
        f->now += us;
        return;
    }
    const uint64_t end = monoUs() + us;
    if (us >= 300) {
        struct timespec ts = { 0, (long)(us - 200) * 1000L };
        nanosleep(&ts, NULL);
    }
    while (monoUs() < end) {
    }
}

void fakeInit(fake_t *f)
{
    memset(f, 0, sizeof *f);
    f->frameUs = 3;
    f->state = 0x01;
    f->calDelayUs = 800;
    f->rssiConst = -90;
    f->lines = calloc(FAKE_MAXLINES, sizeof(char *));
    f->status[0x30] = 0x80;
    f->status[0x31] = 0x03;
}

void fakeFree(fake_t *f)
{
    for (int i = 0; i < f->nlines; i++) {
        free(f->lines[i]);
    }
    free(f->lines);
    f->lines = NULL;
}

void fakeViolation(fake_t *f, const char *msg)
{
    if (f->violations == 0) {
        strncpy(f->vmsg, msg, sizeof f->vmsg - 1);
    }
    f->violations++;
}

bool fakeInBurst(fake_t *f, uint64_t t)
{
    for (int i = 0; i < f->nb; i++) {
        if (t >= f->bOn[i] && t < f->bOff[i]) {
            return true;
        }
    }
    return false;
}

int8_t fakeRssiAt(fake_t *f, uint64_t t)
{
    if (f->nb) {
        return fakeInBurst(f, t) ? f->burstRssi : f->rssiConst;
    }
    switch (f->rssiMode) {
    case RSSI_RAMP:
        return (int8_t)(-120 + (int)((t / 1000u) % 200u));
    case RSSI_STEP: {
        const bool on = t >= f->stepOnAt && t < f->stepOffAt;
        const int8_t base = on ? f->stepOn : f->stepOff;
        uint32_t x = (uint32_t)(t / 10u) * 2654435761u;
        x ^= x >> 15;
        return (int8_t)(base + (int)(x % 5u) - 2);
    }
    default:
        return f->rssiConst;
    }
}

static void trace(fake_t *f, uint8_t kind, uint8_t hdr, uint8_t data)
{
    if (f->frames < FAKE_HEAD) {
        f->headHdr[f->frames] = hdr;
        f->headData[f->frames] = data;
        f->headKind[f->frames] = kind;
    }
    f->frames++;
    f->lastHdr = hdr;
    f->lastKind = kind;
}

static void tick(fake_t *f)
{
    fakeAdvance(f, f->frameUs);
}

static void chipUpdate(fake_t *f)
{
    const uint64_t t = fakeNow(f);
    if (f->estateAt && !f->estateDone && t >= f->estateAt && f->state == 0x0D) {
        f->state = 0x11;
        f->estateDone = true;
    }
    if (f->state == 0x13 && t >= f->rxAtUs && !f->neverRx) {
        f->state = 0x0D;
    }
}

static void doStrobe(fake_t *f, uint8_t s)
{
    chipUpdate(f);
    switch (s) {
    case 0x30:
        memset(f->reg, 0, sizeof f->reg);
        f->reg[0x0E] = f->resetBad ? 0x00 : 0xC4;
        f->reg[0x0F] = 0xEC;
        f->state = 0x01;
        f->sawFreq1Ok = f->sawRbOk = false;
        break;
    case 0x36:
        f->state = 0x01;
        break;
    case 0x34:
        if (f->state == 0x01 && !(f->estateDone && f->estateStuck)) {
            f->state = 0x13;
            f->rxAtUs = fakeNow(f) + f->calDelayUs;
        } else if (f->state == 0x01) {
            f->state = 0x01;
        }
        break;
    default:
        break;
    }
}

static bool strobeOk(uint8_t s)
{
    return s == 0x30 || s == 0x33 || s == 0x34 || s == 0x36 || s == 0x3D;
}

static void pStrobe(void *c, uint8_t s)
{
    fake_t *f = c;
    if (!strobeOk(s)) {
        fakeViolation(f, "bad strobe");
    }
    trace(f, 'S', s, 0);
    doStrobe(f, s);
    tick(f);
}

static void pWrite(void *c, uint8_t hdr, uint8_t data)
{
    fake_t *f = c;
    if (!(hdr <= 0x2E || (hdr == 0x3E && data == 0x00))) {
        fakeViolation(f, "bad write header");
    }
    trace(f, 'W', hdr, data);
    if (hdr == 0x0F && f->rbBad) {
        // write ignored
    } else if (hdr <= 0x2E) {
        f->reg[hdr] = data;
    }
    tick(f);
}

static uint8_t pRead(void *c, uint8_t hdr)
{
    fake_t *f = c;
    const bool cfg = hdr >= 0x80 && hdr <= 0xAE;
    const bool stat = hdr >= 0xF0 && hdr <= 0xFD;
    uint8_t v = 0;
    if (!cfg && !stat) {
        fakeViolation(f, "bad read header");
    }
    trace(f, 'R', hdr, 0xFF);
    chipUpdate(f);
    if (cfg) {
        v = f->reg[hdr & 0x3F];
        if (hdr == 0x8E && v == 0xC4) {
            f->sawFreq1Ok = true;
        }
        if (hdr == 0x8F && v == 0x5A) {
            f->sawRbOk = true;
        }
    } else if (stat) {
        const uint8_t a = hdr & 0x3F;
        if (a == 0x35) {
            v = f->state;
        } else if (a == 0x34) {
            const uint64_t t = fakeNow(f);
            if (!f->firstRssiSeen) {
                f->firstRssiSeen = true;
                if (!f->drainCalled) {
                    fakeViolation(f, "first sample before rxDrain");
                }
            }
            f->rssiReads++;
            f->rssiSincePoll++;
            if (f->rssiSincePoll > f->maxRssiBetweenPolls) {
                f->maxRssiBetweenPolls = f->rssiSincePoll;
            }
            if (f->rxVisibleSeen) {
                f->rssiAfterRx++;
            }
            v = (uint8_t)fakeRssiAt(f, t);
            if (t >= f->disagreeFrom && t < f->disagreeTo) {
                /* time-independent alternation so consecutive reads always disagree */
                v = (f->rssiToggle++ & 1u) ? 0x10u : 0x20u;
            }
        } else if (a == 0x32 || a == 0x38) {
            const uint64_t t = fakeNow(f);
            const bool carrier = f->state == 0x0D && t >= f->fqOn && t < f->fqOff;
            if (a == 0x32) {
                f->feReads++;
                v = (uint8_t)(carrier ? f->feVal : f->feStale);
                if (f->feDisagree) {
                    v = (f->feToggle++ & 1u) ? 0x05u : 0x06u;
                }
            } else {
                f->pktReads++;
                v = carrier ? 0x40u : 0x00u;
            }
        } else {
            v = f->status[a];
        }
    }
    tick(f);
    return v;
}

static uint32_t pMicros(void *c)
{
    fake_t *f = c;
    if (!f->real) {
        f->now += 1;
    }
    return (uint32_t)fakeNow(f);
}

static void pDelay(void *c, uint32_t us)
{
    fakeAdvance(c, us);
}

static void pFront(void *c, bool on)
{
    fake_t *f = c;
    f->lnaCalled = true;
    if (on) {
        if (!(f->sawFreq1Ok && f->sawRbOk)) {
            fakeViolation(f, "LNA on before liveness");
        }
        f->lnaEverOn = true;
        f->lnaOnCount++;
    }
    f->lna = on;
}

static uint32_t pRxWaiting(void *c)
{
    fake_t *f = c;
    if (f->simRxWaiting) {
        return f->simRxWaiting(f->simCtx);
    }
    f->rxPolls++;
    f->rssiSincePoll = 0;
    if (f->rxAt && fakeNow(f) >= f->rxAt) {
        f->rxVisibleSeen = true;
        return f->rxCount ? f->rxCount : 1;
    }
    return 0;
}

static void pRxDrain(void *c)
{
    fake_t *f = c;
    f->drainCalled = true;
    if (f->simRxDrain) {
        f->simRxDrain(f->simCtx);
        return;
    }
    f->rxAt = 0;
    f->rxVisibleSeen = false;
}

static bool pUsb(void *c)
{
    fake_t *f = c;
    if (f->simUsb) {
        return f->simUsb(f->simCtx);
    }
    f->rssiSincePoll = 0;
    return !(f->usbDownAt && fakeNow(f) >= f->usbDownAt);
}

static bool pTx(void *c, const char *buf, uint32_t len)
{
    fake_t *f = c;
    if (f->simTx) {
        return f->simTx(f->simCtx, buf, len);
    }
    const uint64_t t = fakeNow(f);
    if (f->txFailFrom && t >= f->txFailFrom && t < f->txFailUntil) {
        return false;
    }
    if (f->nlines < FAKE_MAXLINES) {
        char *s = malloc(len + 1);
        memcpy(s, buf, len);
        s[len] = 0;
        f->lines[f->nlines++] = s;
        if (f->hook) {
            f->hook(f, s);
        }
    }
    return true;
}

static int pGdoRead(void *c)
{
    fake_t *f = c;
    chipUpdate(f);
    if (f->gdoUnwired) {
        return 0;
    }
    const uint8_t cfg = f->reg[0x02];
    int v = 0;
    if ((cfg & 0x3F) == 0x2F) {
        v = 0;
    } else if ((cfg & 0x3F) == 0x0E) {
        v = f->state == 0x0D && fakeInBurst(f, fakeNow(f));
    } else if ((cfg & 0x3F) == 0x2E) {
        return 0; // high impedance, pull-down
    } else if (f->armed) {
        fakeViolation(f, "unexpected IOCFG0 while capturing GDO0");
    }
    return (cfg & 0x40) ? !v : v;
}

static bool pEdgeArm(void *c, bool on)
{
    fake_t *f = c;
    f->armed = on;
    if (on) {
        if ((f->reg[0x02] & 0x3F) != 0x0E) {
            fakeViolation(f, "armed without carrier sense on GDO0");
        }
        f->armedAt = fakeNow(f);
        f->edgeSeen = f->edgeLost = 0;
        f->edgeNext = 0;
        // edges before arming are not captured
        while (f->edgeNext < 2u * (uint32_t)f->nb) {
            const uint32_t b = f->edgeNext / 2u;
            const uint64_t t = (f->edgeNext & 1u) ? f->bOff[b] : f->bOn[b];
            if (t > f->armedAt) break;
            f->edgeNext++;
        }
    }
    return true;
}

static bool pEdgePop(void *c, uint32_t *tUs, uint8_t *level)
{
    fake_t *f = c;
    if (!f->armed || f->edgeNext >= 2u * (uint32_t)f->nb) {
        return false;
    }
    const uint32_t b = f->edgeNext / 2u;
    const bool rise = (f->edgeNext & 1u) == 0;
    const uint64_t t = rise ? f->bOn[b] : f->bOff[b];
    if (t > fakeNow(f)) {
        return false;
    }
    f->edgeNext++;
    f->edgeSeen++;
    if (f->lostInject) {
        f->lostInject--;
        f->edgeLost++;
        return pEdgePop(c, tUs, level);
    }
    *tUs = (uint32_t)t;
    *level = rise ? 1 : 0;
    return true;
}

static void pEdgeCounts(void *c, uint32_t *e, uint32_t *l)
{
    fake_t *f = c;
    *e = f->edgeSeen;
    *l = f->edgeLost;
}

static void pAntSet(void *c, bool high)
{
    fake_t *f = c;
    f->ant = high;
    f->antSetCalled = true;
}

void fakeHal(fake_t *f, rxdiagHal_t *h)
{
    h->gdoRead = f->noGdoHal ? NULL : pGdoRead;
    h->edgeArm = f->noGdoHal ? NULL : pEdgeArm;
    h->edgePop = f->noGdoHal ? NULL : pEdgePop;
    h->edgeCounts = f->noGdoHal ? NULL : pEdgeCounts;
    h->antSet = f->noGdoHal ? NULL : pAntSet;
    h->ctx = f;
    h->spiRead = pRead;
    h->spiWrite = pWrite;
    h->spiStrobe = pStrobe;
    h->micros = pMicros;
    h->delayUs = pDelay;
    h->frontEnd = pFront;
    h->rxWaiting = pRxWaiting;
    h->rxDrain = pRxDrain;
    h->usbConnected = pUsb;
    h->txTry = pTx;
    f->realStart = f->real ? monoUs() : 0;
    // chip power-on state: reset registers
    f->reg[0x0E] = f->resetBad ? 0x00 : 0xC4;
    f->reg[0x0F] = 0xEC;
}
