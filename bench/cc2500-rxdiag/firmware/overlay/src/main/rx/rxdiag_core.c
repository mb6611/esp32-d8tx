// rxdiag core. See plans/cc2500-radio-diagnostic/interface-v1.md (frozen) and vectors-v1.txt.
// Every SPI transaction goes through the three guarded helpers below, which enforce interface-v1 section 6.
#include "rxdiag_core.h"

#define RX_LINE_MAX 640u
#define MAX_SEL 96u    // S/E/X
#define MAX_IH  480u   // I/H

#define BIT0 1u
#define BIT1 2u
#define BIT2 4u
#define BIT3 8u

#define MARC_RX 13u
#define RX_ENTER_TIMEOUT_US 2000u
#define SETTLE_US 1000u
#define STALL_US 1000000u
#define CHECK_EVERY 64u
#define PREROLL_SAMPLES 256u
#define PREROLL_MAX_ATTEMPTS 4096u

// CC2500 register map (addresses only; no hardware addresses of the MCU)
enum {
    R_IOCFG0 = 0x02, R_PKTCTRL1 = 0x07, R_PKTCTRL0 = 0x08, R_CHANNR = 0x0A, R_FSCTRL1 = 0x0B, R_FSCTRL0 = 0x0C,
    R_FREQ2 = 0x0D, R_FREQ1 = 0x0E, R_FREQ0 = 0x0F, R_MDMCFG4 = 0x10, R_MDMCFG3 = 0x11, R_MDMCFG2 = 0x12,
    R_MDMCFG1 = 0x13, R_MDMCFG0 = 0x14, R_MCSM1 = 0x17, R_MCSM0 = 0x18, R_AGCCTRL2 = 0x1B, R_AGCCTRL1 = 0x1C,
    R_AGCCTRL0 = 0x1D, R_FREND1 = 0x21, R_FREND0 = 0x22, R_FSCAL3 = 0x23, R_FSCAL2 = 0x24, R_FSCAL1 = 0x25,
    R_FSCAL0 = 0x26, R_FOCCFG = 0x19, R_FSTEST = 0x29, R_TEST2 = 0x2C, R_TEST1 = 0x2D, R_TEST0 = 0x2E,
    S_PARTNUM = 0x30, S_VERSION = 0x31, S_FREQEST = 0x32, S_LQI = 0x33, S_RSSI = 0x34, S_PKTSTATUS = 0x38, S_MARCSTATE = 0x35,
    STROBE_SRES = 0x30, STROBE_SCAL = 0x33, STROBE_SRX = 0x34, STROBE_SIDLE = 0x36, STROBE_SNOP = 0x3D,
    R_PATABLE = 0x3E
};

#define MDMCFG3_VAL 0x3B
#define DRATE_E 13

// ---------------------------------------------------------------- pure functions

bool rxdiagFreqWord(uint32_t freqKhz, uint32_t *word, uint32_t *setHz, bool *spur)
{
    if (freqKhz < 2400000u || freqKhz > 2483500u) {
        return false;
    }
    const uint64_t w = ((uint64_t)freqKhz * 1000u * 65536u + 13000000u) / 26000000u;
    const uint64_t hz = (w * 26000000u) / 65536u;
    bool sp = false;
    for (int32_t k = 185; k <= 191; k++) {
        int32_t d = (int32_t)freqKhz - k * 13000;
        if (d < 0) {
            d = -d;
        }
        if (d <= 500) {
            sp = true;
        }
    }
    if (word) {
        *word = (uint32_t)w;
    }
    if (setHz) {
        *setHz = (uint32_t)hz;
    }
    if (spur) {
        *spur = sp;
    }
    return true;
}

static const uint16_t bwLabels[16] = { 812, 650, 541, 464, 406, 325, 270, 232, 203, 162, 135, 116, 102, 81, 68, 58 };

bool rxdiagBwLookup(uint32_t bwLabelKhz, uint8_t *mdmcfg4, uint32_t *bwHz)
{
    for (uint32_t i = 0; i < 16; i++) {
        if (bwLabels[i] == bwLabelKhz) {
            const uint32_t e = i / 4, m = i % 4;
            if (mdmcfg4) {
                *mdmcfg4 = (uint8_t)((e << 6) | (m << 4) | 0x0D);
            }
            if (bwHz) {
                *bwHz = (uint32_t)(26000000u / (8u * (4u + m) * (1u << e)));
            }
            return true;
        }
    }
    return false;
}

bool rxdiagWindowValid(uint32_t windowMs)
{
    return windowMs >= 1u && windowMs <= 1000u;
}

bool rxdiagStatusHeader(uint8_t addr, uint8_t *header)
{
    if (addr < 0x30 || addr > 0x3D) {
        return false;
    }
    if (header) {
        *header = (uint8_t)(0xC0u | addr);
    }
    return true;
}

uint64_t rxdiagMicros64(uint64_t prev64, uint32_t now32)
{
    uint64_t cand = (prev64 & ~(uint64_t)0xFFFFFFFFu) | now32;
    if (cand < prev64) {
        cand += (uint64_t)1 << 32;
    }
    return cand;
}

// ---------------------------------------------------------------- string builder

typedef struct { char *p; size_t cap, len; bool ovf; } sb_t;

static void sbInit(sb_t *s, char *buf, size_t cap) { s->p = buf; s->cap = cap; s->len = 0; s->ovf = false; if (cap) buf[0] = 0; }

static void sbc(sb_t *s, char c)
{
    if (s->len + 1 < s->cap) {
        s->p[s->len++] = c;
        s->p[s->len] = 0;
    } else {
        s->ovf = true;
    }
}

static void sbs(sb_t *s, const char *t)
{
    if (!t) {
        t = "none";
    }
    while (*t) {
        sbc(s, *t++);
    }
}

static void sbu(sb_t *s, uint64_t v)
{
    char tmp[21];
    int n = 0;
    do {
        tmp[n++] = (char)('0' + (int)(v % 10u));
        v /= 10u;
    } while (v);
    while (n) {
        sbc(s, tmp[--n]);
    }
}

static void sbi(sb_t *s, int64_t v)
{
    if (v < 0) {
        sbc(s, '-');
        sbu(s, (uint64_t)0 - (uint64_t)v);
    } else {
        sbu(s, (uint64_t)v);
    }
}

static void sbx(sb_t *s, uint32_t v, int digits)
{
    sbs(s, "0x");
    for (int i = digits - 1; i >= 0; i--) {
        sbc(s, "0123456789ABCDEF"[(v >> (4 * i)) & 0xF]);
    }
}

// ---------------------------------------------------------------- window aggregator

typedef struct { uint32_t n, changes; int32_t sum; int8_t min, max, last; } win_t;

static void winInit(win_t *w) { w->n = 0; w->changes = 0; w->sum = 0; w->min = 0; w->max = 0; w->last = 0; }

static void winAdd(win_t *w, int8_t v)
{
    if (w->n == 0) {
        w->min = w->max = v;
    } else {
        if (v != w->last) {
            w->changes++;
        }
        if (v < w->min) {
            w->min = v;
        }
        if (v > w->max) {
            w->max = v;
        }
    }
    w->n++;
    w->sum += v;
    w->last = v;
}

static void fmtS(sb_t *s, uint32_t seq, uint64_t tUs, const win_t *w, uint8_t marc, uint8_t flags)
{
    sbs(s, "S,"); sbu(s, seq);
    sbc(s, ','); sbu(s, tUs);
    sbc(s, ','); sbu(s, w->n);
    sbc(s, ','); sbu(s, w->changes);
    sbc(s, ','); sbi(s, w->min);
    sbc(s, ','); sbi(s, w->max);
    sbc(s, ','); sbi(s, w->last);
    sbc(s, ','); sbi(s, w->sum);
    sbc(s, ','); sbu(s, marc);
    sbc(s, ','); sbu(s, flags);
}

size_t rxdiagFormatS(char *out, size_t cap, uint32_t seq, uint64_t tUs, const int8_t *samples, uint32_t count, uint8_t marc, uint8_t flags)
{
    win_t w;
    winInit(&w);
    for (uint32_t i = 0; i < count; i++) {
        winAdd(&w, samples[i]);
    }
    sb_t s;
    sbInit(&s, out, cap);
    fmtS(&s, seq, tUs, &w, marc, flags);
    return s.ovf ? 0 : s.len;
}

// ---------------------------------------------------------------- run state

typedef struct {
    const rxdiagHal_t *h;
    const rxdiagBoard_t *b;
    uint64_t m64;
    uint32_t seq;
    bool dropped;
    bool failing;
    uint64_t failStart;
    uint32_t sinceCheck;
    uint8_t sampleFlags; // scratch for pre-roll
    bool armed;          // events: edge capture enabled (disarmed by finish)
    bool gdoOut;         // events: IOCFG0 drives GDO0 (set back to high-Z by finish)
} st_t;

static uint64_t nowUs(st_t *st)
{
    st->m64 = rxdiagMicros64(st->m64, st->h->micros(st->h->ctx));
    return st->m64;
}

// ---- guarded SPI helpers (interface-v1 section 6). A refused request produces no traffic.

static bool spiStrobe(st_t *st, uint8_t s)
{
    if (s != STROBE_SRES && s != STROBE_SCAL && s != STROBE_SRX && s != STROBE_SIDLE && s != STROBE_SNOP) {
        return false;
    }
    st->h->spiStrobe(st->h->ctx, s);
    return true;
}

static bool spiWriteReg(st_t *st, uint8_t addr, uint8_t data)
{
    if (!((addr <= 0x2E) || (addr == R_PATABLE && data == 0x00))) {
        return false;
    }
    st->h->spiWrite(st->h->ctx, addr, data);
    return true;
}

static uint8_t spiReadCfg(st_t *st, uint8_t addr)
{
    if (addr > 0x2E) {
        return 0;
    }
    return st->h->spiRead(st->h->ctx, (uint8_t)(0x80u | addr));
}

static uint8_t spiReadStatus(st_t *st, uint8_t addr)
{
    uint8_t hdr;
    if (!rxdiagStatusHeader(addr, &hdr)) {
        return 0;
    }
    return st->h->spiRead(st->h->ctx, hdr);
}

// ---- record output

static bool emit(st_t *st, sb_t *s, size_t maxLen)
{
    if (s->ovf || s->len > maxLen) {
        return false; // never send a record that violates the length contract
    }
    sbc(s, '\r');
    sbc(s, '\n');
    if (s->ovf) {
        return false;
    }
    const bool ok = st->h->txTry(st->h->ctx, s->p, (uint32_t)s->len);
    if (ok) {
        st->failing = false;
    } else {
        if (!st->failing) {
            st->failing = true;
            st->failStart = nowUs(st);
        }
        st->dropped = true;
    }
    return ok;
}

static void emitE(st_t *st, const char *code, const char *detail)
{
    char buf[RX_LINE_MAX];
    sb_t s;
    sbInit(&s, buf, sizeof buf);
    sbs(&s, "E,"); sbu(&s, nowUs(st));
    sbc(&s, ','); sbs(&s, code);
    sbc(&s, ','); sbs(&s, detail ? detail : "-");
    emit(st, &s, MAX_SEL);
}

static void emitX(st_t *st, const char *reason)
{
    char buf[RX_LINE_MAX];
    sb_t s;
    sbInit(&s, buf, sizeof buf);
    sbs(&s, "X,"); sbu(&s, st->seq);
    sbc(&s, ','); sbu(&s, nowUs(st));
    sbc(&s, ','); sbs(&s, reason);
    emit(st, &s, MAX_SEL);
}

// Exit invariant: SIDLE last, LNA off, then the best-effort X record.
static rxdiagResult_e finish(st_t *st, rxdiagResult_e res, const char *reason)
{
    if (st->armed) {
        st->h->edgeArm(st->h->ctx, false);
        st->armed = false;
    }
    if (st->gdoOut) {
        spiWriteReg(st, R_IOCFG0, 0x2E); // GDO0 back to high impedance
        st->gdoOut = false;
    }
    spiStrobe(st, STROBE_SIDLE);
    st->h->frontEnd(st->h->ctx, false);
    if (reason) {
        emitX(st, reason);
    }
    return res;
}

// ---------------------------------------------------------------- argument parsing

// Decimal, digits only. Saturates to UINT32_MAX on overflow. Returns false for a non-numeric token.
static bool parseU(const char *t, size_t n, uint32_t *out)
{
    if (n == 0) {
        return false;
    }
    uint64_t v = 0;
    for (size_t i = 0; i < n; i++) {
        if (t[i] < '0' || t[i] > '9') {
            return false;
        }
        v = v * 10u + (uint64_t)(t[i] - '0');
        if (v > 0xFFFFFFFFu) {
            v = 0xFFFFFFFFu;
        }
    }
    *out = (uint32_t)v;
    return true;
}

#define MAX_TOK 7

static int tokenize(const char *a, const char *tok[MAX_TOK], size_t len[MAX_TOK])
{
    int n = 0;
    while (*a) {
        while (*a == ' ') {
            a++;
        }
        if (!*a) {
            break;
        }
        if (n >= MAX_TOK) {
            return -1;
        }
        tok[n] = a;
        while (*a && *a != ' ') {
            a++;
        }
        len[n] = (size_t)(a - tok[n]);
        n++;
    }
    return n;
}

static bool tokIs(const char *t, size_t n, const char *lit)
{
    size_t i = 0;
    for (; lit[i]; i++) {
        if (i >= n || t[i] != lit[i]) {
            return false;
        }
    }
    return i == n;
}

// ---------------------------------------------------------------- radio helpers

typedef struct { bool resetOk, rbOk; uint8_t part, ver; } live_t;

// SRES, wait, FREQ1 reset value check, FREQ0 write/readback, restore, PARTNUM/VERSION.
static void liveness(st_t *st, live_t *l)
{
    spiStrobe(st, STROBE_SRES);
    st->h->delayUs(st->h->ctx, 1000);
    l->resetOk = spiReadCfg(st, R_FREQ1) == 0xC4;
    spiWriteReg(st, R_FREQ0, 0x5A);
    l->rbOk = spiReadCfg(st, R_FREQ0) == 0x5A;
    spiWriteReg(st, R_FREQ0, 0xEC);
    l->part = spiReadStatus(st, S_PARTNUM);
    l->ver = spiReadStatus(st, S_VERSION);
}

static bool waitRx(st_t *st, uint8_t *marcOut)
{
    const uint64_t t0 = nowUs(st);
    for (;;) {
        const uint8_t m = spiReadStatus(st, S_MARCSTATE) & 0x1F;
        if (marcOut) {
            *marcOut = m;
        }
        if (m == MARC_RX) {
            return true;
        }
        if (nowUs(st) - t0 >= RX_ENTER_TIMEOUT_US) {
            return false;
        }
    }
}

static void emitMarcDetail(st_t *st, const char *code, uint8_t m)
{
    char d[24];
    sb_t s;
    sbInit(&s, d, sizeof d);
    sbs(&s, "marc="); sbu(&s, m);
    emitE(st, code, d);
}

// Reads MARCSTATE; on mismatch emits ESTATE and tries to re-enter RX. Returns -1 on success
// (flags updated) or an rxdiagResult_e on failure (finish already done).
static int marcCheck(st_t *st, uint8_t *flags, uint8_t *marcOut)
{
    uint8_t m = spiReadStatus(st, S_MARCSTATE) & 0x1F;
    if (m != MARC_RX) {
        emitMarcDetail(st, "ESTATE", m);
        *flags |= (uint8_t)(BIT0 | BIT3);
        spiStrobe(st, STROBE_SIDLE);
        spiStrobe(st, STROBE_SRX);
        if (!waitRx(st, &m)) {
            return (int)finish(st, RXDIAG_EXIT_RADIO, "radio");
        }
    }
    if (marcOut) {
        *marcOut = m;
    }
    return -1;
}

// Host byte, USB gone, USB stall. Returns -1 to continue or an rxdiagResult_e (finish done).
static int linkCheck(st_t *st)
{
    if (st->h->rxWaiting(st->h->ctx) > 0) {
        st->h->rxDrain(st->h->ctx);
        return (int)finish(st, RXDIAG_EXIT_HOST, "host");
    }
    if (!st->h->usbConnected(st->h->ctx)) {
        return (int)finish(st, RXDIAG_EXIT_USB, "usb");
    }
    if (st->failing && nowUs(st) - st->failStart > STALL_US) {
        return (int)finish(st, RXDIAG_EXIT_USBSTALL, "usbstall");
    }
    return -1;
}

// One sample attempt (two RSSI reads). Returns true when accepted.
static bool sampleOnce(st_t *st, int8_t *v, uint8_t *flags)
{
    const uint8_t a = spiReadStatus(st, S_RSSI);
    const uint8_t b = spiReadStatus(st, S_RSSI);
    if (a != b) {
        *flags |= BIT1;
        return false;
    }
    *v = (int8_t)a;
    return true;
}

// Periodic check every CHECK_EVERY attempts.
static int periodic(st_t *st, uint8_t *flags)
{
    if (++st->sinceCheck < CHECK_EVERY) {
        return -1;
    }
    st->sinceCheck = 0;
    int r = linkCheck(st);
    if (r >= 0) {
        return r;
    }
    return marcCheck(st, flags, NULL);
}

// ---------------------------------------------------------------- info

static void emitI(st_t *st, const live_t *l)
{
    char buf[RX_LINE_MAX];
    sb_t s;
    const rxdiagBoard_t *b = st->b;
    sbInit(&s, buf, sizeof buf);
    sbs(&s, "I,proto=1,fw="); sbs(&s, b->fw);
    sbs(&s, ",bf="); sbs(&s, b->bf);
    sbs(&s, ",build=MATEKF411RXDIAG,board=M41R,usb=MATEKF411RX-RXDIAG");
    sbs(&s, ",reset_ok="); sbu(&s, l->resetOk ? 1 : 0);
    sbs(&s, ",rb_ok="); sbu(&s, l->rbOk ? 1 : 0);
    sbs(&s, ",part="); sbx(&s, l->part, 2);
    sbs(&s, ",ver="); sbx(&s, l->ver, 2);
    sbs(&s, ",cs="); sbs(&s, b->cs);
    sbs(&s, ",exti="); sbs(&s, b->exti);
    sbs(&s, ",txen="); sbs(&s, b->txen);
    sbs(&s, ",lna="); sbs(&s, b->lna);
    sbs(&s, ",ant="); sbs(&s, b->ant);
    sbs(&s, ",spi="); sbu(&s, b->spiBus);
    sbs(&s, ",spidiv="); sbu(&s, b->spiDiv);
    sbs(&s, ",spi_hz="); sbu(&s, b->spiHz);
    sbs(&s, ",motor_proto="); sbs(&s, b->motorProto);
    sbs(&s, ",motor_dev="); sbs(&s, b->motorDevNull ? "null" : "active");
    sbs(&s, ",vbat_cv="); sbi(&s, b->vbatCv);
    emit(st, &s, MAX_IH);
}

static rxdiagResult_e doInfo(st_t *st)
{
    live_t l;
    st->h->frontEnd(st->h->ctx, false);
    liveness(st, &l);
    spiStrobe(st, STROBE_SIDLE);
    st->h->frontEnd(st->h->ctx, false);
    emitI(st, &l);
    return RXDIAG_DONE;
}

// ---------------------------------------------------------------- stream

typedef struct { uint8_t addr, val; } regval_t;

static const regval_t baseRegs[] = {
    { R_IOCFG0, 0x2E }, { R_FSCTRL1, 0x0A }, { R_FSCTRL0, 0x00 }, { R_CHANNR, 0x00 },
};
static const regval_t tailRegs[] = {
    { R_MDMCFG3, MDMCFG3_VAL }, { R_MDMCFG2, 0x10 }, { R_MDMCFG1, 0x23 }, { R_MDMCFG0, 0x7A },
    { R_PKTCTRL1, 0x00 }, { R_PKTCTRL0, 0x32 }, { R_MCSM1, 0x0C }, { R_MCSM0, 0x18 },
    { R_AGCCTRL2, 0x03 }, { R_AGCCTRL1, 0x40 }, { R_AGCCTRL0, 0x91 },
    { R_FREND1, 0x56 }, { R_FREND0, 0x10 },
    { R_FSCAL3, 0xA9 }, { R_FSCAL2, 0x0A }, { R_FSCAL1, 0x00 }, { R_FSCAL0, 0x11 },
    { R_FSTEST, 0x59 }, { R_TEST2, 0x88 }, { R_TEST1, 0x31 }, { R_TEST0, 0x0B },
};

static rxdiagResult_e doStream(st_t *st, uint32_t freqKhz, uint32_t windowMs, uint32_t bwLabel)
{
    uint32_t word = 0, setHz = 0, bwHz = 0;
    uint8_t mdm4 = 0;
    bool spur = false;
    rxdiagFreqWord(freqKhz, &word, &setHz, &spur);
    rxdiagBwLookup(bwLabel, &mdm4, &bwHz);
    const uint32_t windowUs = windowMs * 1000u;

    // Motor gate: zero SPI traffic.
    if (!st->b->motorDevNull || !(st->b->motorProto && st->b->motorProto[0] == 'D' && st->b->motorProto[1] == 'I' &&
                                  st->b->motorProto[2] == 'S' && st->b->motorProto[3] == 'A' && st->b->motorProto[4] == 'B' &&
                                  st->b->motorProto[5] == 'L' && st->b->motorProto[6] == 'E' && st->b->motorProto[7] == 'D' &&
                                  st->b->motorProto[8] == 0)) {
        char d[64];
        sb_t s;
        sbInit(&s, d, sizeof d);
        sbs(&s, "proto="); sbs(&s, st->b->motorProto);
        sbs(&s, ";dev="); sbs(&s, st->b->motorDevNull ? "null" : "active");
        emitE(st, "EMOTOR", d);
        return RXDIAG_ERR_REFUSED;
    }

    // Residue (CR/LF) from the command line must not read as a stop byte.
    st->h->rxDrain(st->h->ctx);

    live_t l;
    st->h->frontEnd(st->h->ctx, false);
    liveness(st, &l);
    if (!l.resetOk || !l.rbOk) {
        spiStrobe(st, STROBE_SIDLE);
        st->h->frontEnd(st->h->ctx, false);
        char d[32];
        sb_t s;
        sbInit(&s, d, sizeof d);
        sbs(&s, "reset_ok="); sbu(&s, l.resetOk ? 1 : 0);
        sbs(&s, ";rb_ok="); sbu(&s, l.rbOk ? 1 : 0);
        emitE(st, "ENOCHIP", d);
        return RXDIAG_EXIT_RADIO;
    }

    // Configuration (writes only, header 0x00-0x2E, then PATABLE=0).
    for (size_t i = 0; i < sizeof baseRegs / sizeof baseRegs[0]; i++) {
        spiWriteReg(st, baseRegs[i].addr, baseRegs[i].val);
    }
    spiWriteReg(st, R_FREQ2, (uint8_t)(word >> 16));
    spiWriteReg(st, R_FREQ1, (uint8_t)(word >> 8));
    spiWriteReg(st, R_FREQ0, (uint8_t)word);
    spiWriteReg(st, R_MDMCFG4, mdm4);
    for (size_t i = 0; i < sizeof tailRegs / sizeof tailRegs[0]; i++) {
        spiWriteReg(st, tailRegs[i].addr, tailRegs[i].val);
    }
    spiWriteReg(st, R_PATABLE, 0x00);

    // Liveness passed: the LNA may go on.
    st->h->frontEnd(st->h->ctx, true);
    spiStrobe(st, STROBE_SIDLE);
    const uint64_t srxAt = nowUs(st);
    spiStrobe(st, STROBE_SRX);
    uint8_t marc = 0;
    if (!waitRx(st, &marc)) {
        emitMarcDetail(st, "ECAL", marc);
        return finish(st, RXDIAG_EXIT_RADIO, "radio");
    }
    {
        const uint64_t el = nowUs(st) - srxAt;
        if (el < SETTLE_US) {
            st->h->delayUs(st->h->ctx, (uint32_t)(SETTLE_US - el));
        }
    }

    // Pre-roll (not reported): measures the mean time per accepted sample.
    uint32_t sampleUs = 0;
    {
        const uint64_t p0 = nowUs(st);
        uint32_t acc = 0;
        for (uint32_t att = 0; att < PREROLL_MAX_ATTEMPTS && acc < PREROLL_SAMPLES; att++) {
            int8_t v;
            if (sampleOnce(st, &v, &st->sampleFlags)) {
                acc++;
            }
            const int r = periodic(st, &st->sampleFlags);
            if (r >= 0) {
                return (rxdiagResult_e)r;
            }
        }
        if (acc) {
            const uint64_t el = nowUs(st) - p0;
            sampleUs = (uint32_t)((el * 2u + acc) / (2u * acc));
        }
    }

    uint64_t winStart = nowUs(st);
    {
        char buf[RX_LINE_MAX];
        sb_t s;
        sbInit(&s, buf, sizeof buf);
        sbs(&s, "H,proto=1,fw="); sbs(&s, st->b->fw);
        sbs(&s, ",bf="); sbs(&s, st->b->bf);
        sbs(&s, ",build=MATEKF411RXDIAG,freq_req_khz="); sbu(&s, freqKhz);
        sbs(&s, ",freq_set_hz="); sbu(&s, setHz);
        sbs(&s, ",freq_word="); sbx(&s, word, 6);
        sbs(&s, ",xosc_hz=26000000,bw_hz="); sbu(&s, bwHz);
        sbs(&s, ",drate_baud="); sbu(&s, ((uint64_t)(256u + (MDMCFG3_VAL)) * ((uint64_t)1 << DRATE_E) * 26000000u) >> 28);
        sbs(&s, ",filter_len=16,window_us="); sbu(&s, windowUs);
        sbs(&s, ",unit=rssi_raw_s8,dbm_est=raw/2-72,offset_note=typical_uncalibrated");
        sbs(&s, ",part="); sbx(&s, l.part, 2);
        sbs(&s, ",ver="); sbx(&s, l.ver, 2);
        sbs(&s, ",spur="); sbu(&s, spur ? 1 : 0);
        sbs(&s, ",ant=1,lna=1,txen=0,spi_hz="); sbu(&s, st->b->spiHz);
        sbs(&s, ",t0_us="); sbu(&s, winStart);
        sbs(&s, ",settle_us=1000,sample_us="); sbu(&s, sampleUs);
        emit(st, &s, MAX_IH);
    }

    bool first = true;
    uint32_t enosamp = 0;
    for (;;) {
        win_t w;
        winInit(&w);
        uint8_t flags = first ? BIT3 : 0;
        first = false;

        do {
            int8_t v;
            if (sampleOnce(st, &v, &flags)) {
                winAdd(&w, v);
            }
            const int r = periodic(st, &flags);
            if (r >= 0) {
                return (rxdiagResult_e)r;
            }
        } while (nowUs(st) - winStart < windowUs);

        // End of window: liveness of the link and of the radio state.
        int r = linkCheck(st);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        uint8_t endMarc = 0;
        r = marcCheck(st, &flags, &endMarc);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        const uint64_t tEnd = nowUs(st);

        if (w.n == 0) {
            char d[24];
            sb_t ds;
            sbInit(&ds, d, sizeof d);
            sbs(&ds, "seq="); sbu(&ds, st->seq);
            emitE(st, "ENOSAMP", d);
            st->seq++;
            if (++enosamp >= 2) {
                return finish(st, RXDIAG_EXIT_RADIO, "radio");
            }
        } else {
            enosamp = 0;
            char buf[RX_LINE_MAX];
            sb_t s;
            sbInit(&s, buf, sizeof buf);
            if (st->dropped) {
                flags |= BIT2;
                st->dropped = false;
            }
            fmtS(&s, st->seq, tEnd, &w, endMarc, flags);
            emit(st, &s, MAX_SEL);
            st->seq++;
        }

        r = linkCheck(st);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        winStart = nowUs(st);
    }
}

// ---------------------------------------------------------------- events (proto 2)
//
// Short-burst instrument. GDO0 is set to carrier sense (IOCFG0=0x0E): the CC2500 drives it high while
// its RSSI is above the AGC carrier-sense threshold (AGCCTRL2.MAGN_TARGET + AGCCTRL1.CARRIER_SENSE_ABS_THR).
// The glue captures both pin edges in an interrupt with a microsecond timestamp, so burst detection has
// no polling gap; the main loop keeps sampling RSSI (two equal reads) for peak level and threshold calibration.
// Records: H (header), B (one per completed burst), C (one per window, cumulative counters), E, X.
// RSSI energy above a threshold only; nothing here demodulates or validates packets.

#define C_MAX 160u
#define B_MAX 96u

static bool motorGateOk(st_t *st)
{
    const char *p = st->b->motorProto;
    static const char dis[] = "DISABLED";
    bool ok = st->b->motorDevNull && p != NULL;
    for (size_t i = 0; ok && i < sizeof dis; i++) {
        ok = p[i] == dis[i];
    }
    if (!ok) {
        char d[64];
        sb_t s;
        sbInit(&s, d, sizeof d);
        sbs(&s, "proto="); sbs(&s, p);
        sbs(&s, ";dev="); sbs(&s, st->b->motorDevNull ? "null" : "active");
        emitE(st, "EMOTOR", d);
    }
    return ok;
}

// ISR timestamp (32-bit, in the past) -> 64-bit timeline of st->m64.
static uint64_t edgeTo64(st_t *st, uint32_t et)
{
    const uint64_t now = nowUs(st);
    int32_t d = (int32_t)((uint32_t)now - et);
    if (d < 0) {
        d = 0; // ISR fired after nowUs(): treat as now
    }
    return now - (uint32_t)d;
}

typedef struct {
    uint32_t att, acc, rej, nHigh, nLow, gapMax;
    int8_t min, max, maxLow, minHigh;
} evwin_t;

static void evwinInit(evwin_t *w)
{
    w->att = w->acc = w->rej = w->nHigh = w->nLow = w->gapMax = 0;
    w->min = 127; w->max = -128; w->maxLow = -128; w->minHigh = 127;
}

static rxdiagResult_e doEvents(st_t *st, uint32_t freqKhz, uint32_t windowMs, uint32_t bwLabel,
                               uint8_t agc2, uint8_t agc1, bool antHigh)
{
    const rxdiagHal_t *h = st->h;
    if (!h->gdoRead || !h->edgeArm || !h->edgePop || !h->edgeCounts || !h->antSet || h->gdoRead(h->ctx) < 0) {
        emitE(st, "EGDO", "nopin");
        return RXDIAG_ERR_REFUSED;
    }
    if (!motorGateOk(st)) {
        return RXDIAG_ERR_REFUSED;
    }
    uint32_t word = 0, setHz = 0, bwHz = 0;
    uint8_t mdm4 = 0;
    bool spur = false;
    rxdiagFreqWord(freqKhz, &word, &setHz, &spur);
    rxdiagBwLookup(bwLabel, &mdm4, &bwHz);
    const uint32_t windowUs = windowMs * 1000u;

    h->rxDrain(h->ctx);
    h->antSet(h->ctx, antHigh);

    live_t l;
    h->frontEnd(h->ctx, false);
    liveness(st, &l);
    if (!l.resetOk || !l.rbOk) {
        spiStrobe(st, STROBE_SIDLE);
        h->frontEnd(h->ctx, false);
        emitE(st, "ENOCHIP", l.resetOk ? "rb_ok=0" : "reset_ok=0");
        return RXDIAG_EXIT_RADIO;
    }

    // Configuration: same register set as stream, with the AGC (threshold/gain) bytes from the arguments.
    regval_t cfg[sizeof baseRegs / sizeof baseRegs[0] + 4 + sizeof tailRegs / sizeof tailRegs[0]];
    size_t nc = 0;
    for (size_t i = 0; i < sizeof baseRegs / sizeof baseRegs[0]; i++) {
        cfg[nc++] = baseRegs[i];
    }
    cfg[nc].addr = R_FREQ2; cfg[nc++].val = (uint8_t)(word >> 16);
    cfg[nc].addr = R_FREQ1; cfg[nc++].val = (uint8_t)(word >> 8);
    cfg[nc].addr = R_FREQ0; cfg[nc++].val = (uint8_t)word;
    cfg[nc].addr = R_MDMCFG4; cfg[nc++].val = mdm4;
    for (size_t i = 0; i < sizeof tailRegs / sizeof tailRegs[0]; i++) {
        cfg[nc] = tailRegs[i];
        if (cfg[nc].addr == R_AGCCTRL2) {
            cfg[nc].val = agc2;
        } else if (cfg[nc].addr == R_AGCCTRL1) {
            cfg[nc].val = agc1;
        }
        nc++;
    }
    for (size_t i = 0; i < nc; i++) {
        spiWriteReg(st, cfg[i].addr, cfg[i].val);
    }
    spiWriteReg(st, R_PATABLE, 0x00);

    // Readback: every configuration byte must read back as written (frequency word included).
    uint32_t mism = 0;
    uint8_t firstBad = 0xFF;
    for (size_t i = 0; i < nc; i++) {
        if (spiReadCfg(st, cfg[i].addr) != cfg[i].val) {
            if (!mism) {
                firstBad = cfg[i].addr;
            }
            mism++;
        }
    }
    const uint32_t freqRb = ((uint32_t)spiReadCfg(st, R_FREQ2) << 16) | ((uint32_t)spiReadCfg(st, R_FREQ1) << 8) | spiReadCfg(st, R_FREQ0);

    // GDO0 wire test while IDLE: constant low, constant high (inverted), constant low.
    st->gdoOut = true;
    spiWriteReg(st, R_IOCFG0, 0x2F);
    h->delayUs(h->ctx, 20);
    const int g0 = h->gdoRead(h->ctx);
    spiWriteReg(st, R_IOCFG0, 0x6F);
    h->delayUs(h->ctx, 20);
    const int g1 = h->gdoRead(h->ctx);
    spiWriteReg(st, R_IOCFG0, 0x2F);
    h->delayUs(h->ctx, 20);
    const int g2 = h->gdoRead(h->ctx);
    const bool gdoOk = g0 == 0 && g1 == 1 && g2 == 0;
    if (mism || freqRb != word) {
        char d[32];
        sb_t s;
        sbInit(&s, d, sizeof d);
        sbs(&s, "mism="); sbu(&s, mism);
        sbs(&s, ";reg="); sbx(&s, firstBad, 2);
        emitE(st, "ECFG", d);
        return finish(st, RXDIAG_EXIT_RADIO, "radio");
    }
    if (!gdoOk) {
        char d[32];
        sb_t s;
        sbInit(&s, d, sizeof d);
        sbs(&s, "lo="); sbi(&s, g0);
        sbs(&s, ";hi="); sbi(&s, g1);
        sbs(&s, ";lo2="); sbi(&s, g2);
        emitE(st, "EGDO", d);
        return finish(st, RXDIAG_EXIT_RADIO, "radio");
    }
    spiWriteReg(st, R_IOCFG0, 0x0E); // carrier sense

    h->frontEnd(h->ctx, true);
    spiStrobe(st, STROBE_SIDLE);
    const uint64_t srxAt = nowUs(st);
    spiStrobe(st, STROBE_SRX);
    uint8_t marc = 0;
    if (!waitRx(st, &marc)) {
        emitMarcDetail(st, "ECAL", marc);
        return finish(st, RXDIAG_EXIT_RADIO, "radio");
    }
    const uint32_t calUs = (uint32_t)(nowUs(st) - srxAt);
    if (calUs < SETTLE_US) {
        h->delayUs(h->ctx, SETTLE_US - calUs);
    }
    const uint8_t fscal3 = spiReadCfg(st, R_FSCAL3), fscal2 = spiReadCfg(st, R_FSCAL2), fscal1 = spiReadCfg(st, R_FSCAL1);

    h->edgeArm(h->ctx, true);
    st->armed = true;
    const int level0 = h->gdoRead(h->ctx);
    const uint64_t t0 = nowUs(st);
    {
        char buf[RX_LINE_MAX];
        sb_t s;
        sbInit(&s, buf, sizeof buf);
        sbs(&s, "H,proto=2,mode=events,fw="); sbs(&s, st->b->fw);
        sbs(&s, ",bf="); sbs(&s, st->b->bf);
        sbs(&s, ",build=MATEKF411RXDIAG,freq_req_khz="); sbu(&s, freqKhz);
        sbs(&s, ",freq_set_hz="); sbu(&s, setHz);
        sbs(&s, ",freq_word="); sbx(&s, word, 6);
        sbs(&s, ",freq_rb="); sbx(&s, freqRb, 6);
        sbs(&s, ",cfg_rb_ok=1,xosc_hz=26000000,bw_hz="); sbu(&s, bwHz);
        sbs(&s, ",window_us="); sbu(&s, windowUs);
        sbs(&s, ",agcctrl2="); sbx(&s, agc2, 2);
        sbs(&s, ",agcctrl1="); sbx(&s, agc1, 2);
        sbs(&s, ",agcctrl0=0x91,iocfg0=0x0E,gdo_ok=1");
        sbs(&s, ",fscal3="); sbx(&s, fscal3, 2);
        sbs(&s, ",fscal2="); sbx(&s, fscal2, 2);
        sbs(&s, ",fscal1="); sbx(&s, fscal1, 2);
        sbs(&s, ",cal_us="); sbu(&s, calUs);
        sbs(&s, ",unit=rssi_raw_s8,dbm_est=raw/2-72");
        sbs(&s, ",part="); sbx(&s, l.part, 2);
        sbs(&s, ",ver="); sbx(&s, l.ver, 2);
        sbs(&s, ",spur="); sbu(&s, spur ? 1 : 0);
        sbs(&s, ",ant="); sbu(&s, antHigh ? 1 : 0);
        sbs(&s, ",lna=1,txen=0,spi_hz="); sbu(&s, st->b->spiHz);
        sbs(&s, ",t0_us="); sbu(&s, t0);
        sbs(&s, ",level0="); sbi(&s, level0);
        emit(st, &s, MAX_IH);
    }

    bool open = level0 == 1;
    uint64_t riseT = t0;
    int8_t peak = -128;
    uint32_t bn = 0;
    uint8_t bflags = open ? BIT0 : 0;  // BIT0 rise before t0, BIT1 repeated rise, BIT2 radio re-entry
    uint32_t bseq = 0, bfail = 0, orphan = 0;
    uint32_t cseq = 0;
    evwin_t w;
    evwinInit(&w);
    uint8_t wflags = BIT3;
    uint64_t winStart = t0, lastS = t0;

    for (;;) {
        const uint64_t ts = nowUs(st);
        if (ts - lastS > w.gapMax) {
            w.gapMax = (uint32_t)(ts - lastS);
        }
        lastS = ts;
        w.att++;
        int8_t v;
        uint8_t sf = 0;
        const bool ok = sampleOnce(st, &v, &sf);
        const int g = h->gdoRead(h->ctx);
        if (ok) {
            w.acc++;
            if (v < w.min) { w.min = v; }
            if (v > w.max) { w.max = v; }
            if (g == 1) {
                w.nHigh++;
                if (v < w.minHigh) { w.minHigh = v; }
            } else {
                w.nLow++;
                if (v > w.maxLow) { w.maxLow = v; }
            }
            if (open) {
                bn++;
                if (v > peak) { peak = v; }
            }
        } else {
            w.rej++;
        }

        uint32_t et;
        uint8_t lv;
        while (h->edgePop(h->ctx, &et, &lv)) {
            const uint64_t e64 = edgeTo64(st, et);
            if (lv) {
                if (open) {
                    bflags |= BIT1;
                } else {
                    open = true;
                    riseT = e64;
                    peak = -128;
                    bn = 0;
                    bflags = 0;
                }
            } else if (!open) {
                orphan++;
            } else {
                char buf[C_MAX + 4];
                sb_t s;
                sbInit(&s, buf, sizeof buf);
                sbs(&s, "B,"); sbu(&s, bseq);
                sbc(&s, ','); sbu(&s, riseT);
                sbc(&s, ','); sbu(&s, e64 >= riseT ? e64 - riseT : 0);
                sbc(&s, ','); sbi(&s, peak);
                sbc(&s, ','); sbu(&s, bn);
                sbc(&s, ','); sbu(&s, bflags);
                if (!emit(st, &s, B_MAX)) {
                    bfail++;
                }
                bseq++;
                open = false;
            }
        }

        const uint8_t before = wflags;
        const int r = periodic(st, &wflags);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        if ((wflags & BIT0) && !(before & BIT0) && open) {
            bflags |= BIT2;
        }

        if (nowUs(st) - winStart >= windowUs) {
            int rr = linkCheck(st);
            if (rr >= 0) {
                return (rxdiagResult_e)rr;
            }
            uint8_t endMarc = 0;
            rr = marcCheck(st, &wflags, &endMarc);
            if (rr >= 0) {
                return (rxdiagResult_e)rr;
            }
            uint32_t edges = 0, lost = 0;
            h->edgeCounts(h->ctx, &edges, &lost);
            const uint64_t tEnd = nowUs(st);
            if (st->dropped) {
                wflags |= BIT2;
                st->dropped = false;
            }
            char buf[C_MAX + 4];
            sb_t s;
            sbInit(&s, buf, sizeof buf);
            sbs(&s, "C,"); sbu(&s, cseq);
            sbc(&s, ','); sbu(&s, tEnd);
            sbc(&s, ','); sbu(&s, tEnd - winStart);
            sbc(&s, ','); sbu(&s, edges);
            sbc(&s, ','); sbu(&s, lost);
            sbc(&s, ','); sbu(&s, bseq);
            sbc(&s, ','); sbu(&s, bfail);
            sbc(&s, ','); sbu(&s, orphan);
            sbc(&s, ','); sbu(&s, w.att);
            sbc(&s, ','); sbu(&s, w.acc);
            sbc(&s, ','); sbu(&s, w.rej);
            sbc(&s, ','); sbi(&s, w.min);
            sbc(&s, ','); sbi(&s, w.max);
            sbc(&s, ','); sbi(&s, w.maxLow);
            sbc(&s, ','); sbi(&s, w.minHigh);
            sbc(&s, ','); sbu(&s, w.nHigh);
            sbc(&s, ','); sbu(&s, w.gapMax);
            sbc(&s, ','); sbu(&s, open ? 1 : 0);
            sbc(&s, ','); sbu(&s, endMarc);
            sbc(&s, ','); sbu(&s, wflags);
            emit(st, &s, C_MAX);
            cseq++;
            evwinInit(&w);
            wflags = 0;
            winStart = tEnd;
            lastS = nowUs(st); // emit time is accounted in this window's span, not as a sample gap
            w.gapMax = (uint32_t)(lastS - tEnd);
        }
    }
}

// ---------------------------------------------------------------- freq (proto 3)
//
// Receive-only frequency-offset readout. Per window one F record from FREQEST (status 0x32, signed, 26 MHz/2^14
// = 1587.1 Hz per LSB), gated by the PKTSTATUS carrier-sense bit (0x40) so a window without carrier reports
// ncs=0, flags bit4 and zeros in the estimate fields (never a stale estimate). Status reads are accepted only
// when two consecutive reads agree. Duration is bounded (default 5000 ms, max 60000 ms). Nothing is transmitted.
#define FREQ_DUR_DEFAULT_MS 5000u
#define FREQ_DUR_MAX_MS 60000u
#define FLAG_NOCARRIER 16u
#define PKT_CS 0x40u

bool rxdiagDurationValid(uint32_t durationMs)
{
    return durationMs >= 1u && durationMs <= FREQ_DUR_MAX_MS;
}

int32_t rxdiagFreqEstHz(int32_t raw)
{
    return (int32_t)(((int64_t)raw * 26000000) / 16384);
}

static bool readStable(st_t *st, uint8_t addr, uint8_t *v)
{
    const uint8_t a = spiReadStatus(st, addr);
    const uint8_t b = spiReadStatus(st, addr);
    *v = a;
    return a == b;
}

static rxdiagResult_e doFreq(st_t *st, uint32_t freqKhz, uint32_t windowMs, uint32_t bwLabel,
                             uint8_t agc2, uint8_t agc1, uint32_t durationMs)
{
    const rxdiagHal_t *h = st->h;
    if (!motorGateOk(st)) {
        return RXDIAG_ERR_REFUSED;
    }
    uint32_t word = 0, setHz = 0, bwHz = 0;
    uint8_t mdm4 = 0;
    bool spur = false;
    rxdiagFreqWord(freqKhz, &word, &setHz, &spur);
    rxdiagBwLookup(bwLabel, &mdm4, &bwHz);
    const uint32_t windowUs = windowMs * 1000u;
    const uint64_t durUs = (uint64_t)durationMs * 1000u;

    h->rxDrain(h->ctx);
    live_t l;
    h->frontEnd(h->ctx, false);
    liveness(st, &l);
    if (!l.resetOk || !l.rbOk) {
        spiStrobe(st, STROBE_SIDLE);
        h->frontEnd(h->ctx, false);
        emitE(st, "ENOCHIP", l.resetOk ? "rb_ok=0" : "reset_ok=0");
        return RXDIAG_EXIT_RADIO;
    }

    regval_t cfg[sizeof baseRegs / sizeof baseRegs[0] + 5 + sizeof tailRegs / sizeof tailRegs[0]];
    size_t nc = 0;
    for (size_t i = 0; i < sizeof baseRegs / sizeof baseRegs[0]; i++) {
        cfg[nc++] = baseRegs[i];
    }
    cfg[nc].addr = R_FREQ2; cfg[nc++].val = (uint8_t)(word >> 16);
    cfg[nc].addr = R_FREQ1; cfg[nc++].val = (uint8_t)(word >> 8);
    cfg[nc].addr = R_FREQ0; cfg[nc++].val = (uint8_t)word;
    cfg[nc].addr = R_MDMCFG4; cfg[nc++].val = mdm4;
    cfg[nc].addr = R_FOCCFG; cfg[nc++].val = 0x1D;   // chip default, written explicitly so it is known
    for (size_t i = 0; i < sizeof tailRegs / sizeof tailRegs[0]; i++) {
        cfg[nc] = tailRegs[i];
        if (cfg[nc].addr == R_AGCCTRL2) {
            cfg[nc].val = agc2;
        } else if (cfg[nc].addr == R_AGCCTRL1) {
            cfg[nc].val = agc1;
        }
        nc++;
    }
    for (size_t i = 0; i < nc; i++) {
        spiWriteReg(st, cfg[i].addr, cfg[i].val);
    }
    spiWriteReg(st, R_PATABLE, 0x00);
    uint32_t mism = 0;
    uint8_t firstBad = 0xFF;
    for (size_t i = 0; i < nc; i++) {
        if (spiReadCfg(st, cfg[i].addr) != cfg[i].val) {
            if (!mism) {
                firstBad = cfg[i].addr;
            }
            mism++;
        }
    }
    if (mism) {
        char d[32];
        sb_t s;
        sbInit(&s, d, sizeof d);
        sbs(&s, "mism="); sbu(&s, mism);
        sbs(&s, ";reg="); sbx(&s, firstBad, 2);
        emitE(st, "ECFG", d);
        return finish(st, RXDIAG_EXIT_RADIO, "radio");
    }

    h->frontEnd(h->ctx, true);
    spiStrobe(st, STROBE_SIDLE);
    const uint64_t srxAt = nowUs(st);
    spiStrobe(st, STROBE_SRX);
    uint8_t marc = 0;
    if (!waitRx(st, &marc)) {
        emitMarcDetail(st, "ECAL", marc);
        return finish(st, RXDIAG_EXIT_RADIO, "radio");
    }
    const uint32_t calUs = (uint32_t)(nowUs(st) - srxAt);   // IDLE->RX including auto-calibration
    {
        const uint64_t el = nowUs(st) - srxAt;
        if (el < SETTLE_US) {
            h->delayUs(h->ctx, (uint32_t)(SETTLE_US - el));
        }
    }
    const uint8_t fs3 = spiReadCfg(st, R_FSCAL3), fs2 = spiReadCfg(st, R_FSCAL2);
    const uint8_t fs1 = spiReadCfg(st, R_FSCAL1), fs0 = spiReadCfg(st, R_FSCAL0);
    const uint32_t freqRb = ((uint32_t)spiReadCfg(st, R_FREQ2) << 16) | ((uint32_t)spiReadCfg(st, R_FREQ1) << 8) | spiReadCfg(st, R_FREQ0);

    const uint64_t t0 = nowUs(st);
    uint64_t winStart = t0;
    {
        char buf[RX_LINE_MAX];
        sb_t s;
        sbInit(&s, buf, sizeof buf);
        sbs(&s, "H,proto=3,mode=freq,fw="); sbs(&s, st->b->fw);
        sbs(&s, ",bf="); sbs(&s, st->b->bf);
        sbs(&s, ",freq_req_khz="); sbu(&s, freqKhz);
        sbs(&s, ",freq_set_hz="); sbu(&s, setHz);
        sbs(&s, ",freq_word="); sbx(&s, word, 6);
        sbs(&s, ",freq_rb="); sbx(&s, freqRb, 6);
        sbs(&s, ",bw_hz="); sbu(&s, bwHz);
        sbs(&s, ",agc2="); sbu(&s, agc2);
        sbs(&s, ",agc1="); sbu(&s, agc1);
        sbs(&s, ",foccfg=1D,fsctrl0=0,fsctrl1=0A");
        sbs(&s, ",fscal3="); sbx(&s, fs3, 2);
        sbs(&s, ",fscal2="); sbx(&s, fs2, 2);
        sbs(&s, ",fscal1="); sbx(&s, fs1, 2);
        sbs(&s, ",fscal0="); sbx(&s, fs0, 2);
        sbs(&s, ",cal_us="); sbu(&s, calUs);
        sbs(&s, ",hz_per_lsb=1587,part="); sbx(&s, l.part, 2);
        sbs(&s, ",ver="); sbx(&s, l.ver, 2);
        sbs(&s, ",spur="); sbu(&s, spur ? 1 : 0);
        sbs(&s, ",ant=1,lna=1,txen=0,spi_hz="); sbu(&s, st->b->spiHz);
        sbs(&s, ",window_us="); sbu(&s, windowUs);
        sbs(&s, ",duration_ms="); sbu(&s, durationMs);
        sbs(&s, ",t0_us="); sbu(&s, t0);
        emit(st, &s, MAX_IH);
    }

    uint32_t enosamp = 0;
    bool first = true;
    for (;;) {
        uint32_t n = 0, rej = 0, ncs = 0;
        int32_t feLast = 0, feMin = 0, feMax = 0;
        int64_t feSum = 0;
        int8_t rssiMax = -128;
        uint8_t pktLast = 0, lqiLast = 0;
        uint8_t flags = first ? BIT3 : 0;
        first = false;
        do {
            uint8_t pk, fe, rs;
            if (readStable(st, S_PKTSTATUS, &pk) && readStable(st, S_FREQEST, &fe) && readStable(st, S_RSSI, &rs)) {
                n++;
                pktLast = pk;
                if ((int8_t)rs > rssiMax) {
                    rssiMax = (int8_t)rs;
                }
                if (pk & PKT_CS) {
                    const int32_t v = (int8_t)fe;
                    if (!ncs || v < feMin) {
                        feMin = v;
                    }
                    if (!ncs || v > feMax) {
                        feMax = v;
                    }
                    feLast = v;
                    feSum += v;
                    ncs++;
                }
            } else {
                rej++;
                flags |= BIT1;
            }
            const int r = periodic(st, &flags);
            if (r >= 0) {
                return (rxdiagResult_e)r;
            }
        } while (nowUs(st) - winStart < windowUs);

        int r = linkCheck(st);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        uint8_t endMarc = 0;
        r = marcCheck(st, &flags, &endMarc);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        lqiLast = spiReadStatus(st, S_LQI);
        const uint64_t tEnd = nowUs(st);

        if (n == 0) {
            char d[24];
            sb_t ds;
            sbInit(&ds, d, sizeof d);
            sbs(&ds, "seq="); sbu(&ds, st->seq);
            emitE(st, "ENOSAMP", d);
            st->seq++;
            if (++enosamp >= 2) {
                return finish(st, RXDIAG_EXIT_RADIO, "radio");
            }
        } else {
            enosamp = 0;
            if (!ncs) {
                flags |= FLAG_NOCARRIER;
            }
            if (st->dropped) {
                flags |= BIT2;
                st->dropped = false;
            }
            const int32_t meanRaw = ncs ? (int32_t)(feSum / (int64_t)ncs) : 0;
            const int32_t meanHz = ncs ? (int32_t)((feSum * 26000000) / ((int64_t)16384 * (int64_t)ncs)) : 0;
            char buf[RX_LINE_MAX];
            sb_t s;
            sbInit(&s, buf, sizeof buf);
            sbs(&s, "F,"); sbu(&s, st->seq);
            sbc(&s, ','); sbu(&s, tEnd);
            sbc(&s, ','); sbu(&s, n);
            sbc(&s, ','); sbu(&s, rej);
            sbc(&s, ','); sbu(&s, ncs);
            sbc(&s, ','); sbi(&s, feLast);
            sbc(&s, ','); sbi(&s, feMin);
            sbc(&s, ','); sbi(&s, feMax);
            sbc(&s, ','); sbi(&s, meanRaw);
            sbc(&s, ','); sbi(&s, meanHz);
            sbc(&s, ','); sbi(&s, rssiMax);
            sbc(&s, ','); sbu(&s, pktLast);
            sbc(&s, ','); sbu(&s, lqiLast);
            sbc(&s, ','); sbu(&s, endMarc);
            sbc(&s, ','); sbu(&s, flags);
            emit(st, &s, MAX_IH);
            st->seq++;
        }
        r = linkCheck(st);
        if (r >= 0) {
            return (rxdiagResult_e)r;
        }
        winStart = nowUs(st);
        if (winStart - t0 >= durUs) {
            return finish(st, RXDIAG_DONE, "done");
        }
    }
}

static bool parseByte(const char *t, size_t n, uint8_t *out)
{
    uint32_t v;
    if (!parseU(t, n, &v) || v > 255u) {
        return false;
    }
    *out = (uint8_t)v;
    return true;
}

// ---------------------------------------------------------------- entry

rxdiagResult_e rxdiagRun(const rxdiagHal_t *hal, const rxdiagBoard_t *board, const char *args)
{
    st_t st;
    st.h = hal;
    st.b = board;
    st.m64 = 0;
    st.seq = 0;
    st.dropped = false;
    st.failing = false;
    st.failStart = 0;
    st.sinceCheck = 0;
    st.sampleFlags = 0;
    st.armed = false;
    st.gdoOut = false;

    const char *tok[MAX_TOK];
    size_t len[MAX_TOK];
    const int n = args ? tokenize(args, tok, len) : -1;

    if (n == 1 && tokIs(tok[0], len[0], "info")) {
        return doInfo(&st);
    }
    if (n >= 2 && n <= 4 && tokIs(tok[0], len[0], "stream")) {
        uint32_t v[3] = { 0, 10, 812 };
        bool ok = true;
        for (int i = 1; i < n; i++) {
            ok = ok && parseU(tok[i], len[i], &v[i - 1]);
        }
        if (ok) {
            if (!rxdiagFreqWord(v[0], NULL, NULL, NULL)) {
                emitE(&st, "EFREQ", "-");
                return RXDIAG_ERR_ARG;
            }
            if (rxdiagWindowValid(v[1]) && rxdiagBwLookup(v[2], NULL, NULL)) {
                return doStream(&st, v[0], v[1], v[2]);
            }
        }
    }
    if (n >= 2 && n <= 7 && tokIs(tok[0], len[0], "events")) {
        // events <freq_khz> [window_ms=100] [bw=812] [agcctrl2=3] [agcctrl1=64] [ant=1]
        uint32_t freq = 0, win = 100, bw = 812;
        uint8_t agc2 = 0x03, agc1 = 0x40, ant = 1;
        bool ok = parseU(tok[1], len[1], &freq);
        ok = ok && (n < 3 || parseU(tok[2], len[2], &win));
        ok = ok && (n < 4 || parseU(tok[3], len[3], &bw));
        ok = ok && (n < 5 || parseByte(tok[4], len[4], &agc2));
        ok = ok && (n < 6 || parseByte(tok[5], len[5], &agc1));
        ok = ok && (n < 7 || (parseByte(tok[6], len[6], &ant) && ant <= 1));
        if (ok) {
            if (!rxdiagFreqWord(freq, NULL, NULL, NULL)) {
                emitE(&st, "EFREQ", "-");
                return RXDIAG_ERR_ARG;
            }
            if (rxdiagWindowValid(win) && rxdiagBwLookup(bw, NULL, NULL)) {
                return doEvents(&st, freq, win, bw, agc2, agc1, ant == 1);
            }
        }
    }
    if (n >= 2 && n <= 7 && tokIs(tok[0], len[0], "freq")) {
        // freq <freq_khz> [window_ms=100] [bw=812] [agcctrl2=251] [agcctrl1=64] [duration_ms=5000]
        uint32_t freq = 0, win = 100, bw = 812, dur = FREQ_DUR_DEFAULT_MS;
        uint8_t agc2 = 0xFB, agc1 = 0x40;
        bool ok = parseU(tok[1], len[1], &freq);
        ok = ok && (n < 3 || parseU(tok[2], len[2], &win));
        ok = ok && (n < 4 || parseU(tok[3], len[3], &bw));
        ok = ok && (n < 5 || parseByte(tok[4], len[4], &agc2));
        ok = ok && (n < 6 || parseByte(tok[5], len[5], &agc1));
        ok = ok && (n < 7 || parseU(tok[6], len[6], &dur));
        if (ok) {
            if (!rxdiagFreqWord(freq, NULL, NULL, NULL)) {
                emitE(&st, "EFREQ", "-");
                return RXDIAG_ERR_ARG;
            }
            if (rxdiagWindowValid(win) && rxdiagBwLookup(bw, NULL, NULL) && rxdiagDurationValid(dur)) {
                return doFreq(&st, freq, win, bw, agc2, agc1, dur);
            }
        }
    }
    emitE(&st, "EARG", "-");
    return RXDIAG_ERR_ARG;
}
