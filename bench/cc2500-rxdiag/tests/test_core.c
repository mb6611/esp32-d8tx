// rxdiag core tests: vectors-v1.txt (read at runtime), fake-CC2500 scenarios, SPI trace invariants.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fake.h"
#include "rxdiag_core.h"

static int fails = 0, checks = 0;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static rxdiagBoard_t board = { "A1B2C3D4", "ABCDEF1", "A15", "C14", "A8", "A13", "A14", "DISABLED", 1, 2, 5250000, true, 0 };

typedef struct { fake_t f; rxdiagHal_t hal; rxdiagResult_e res; } run_t;

static void runInit(run_t *r) { fakeInit(&r->f); }
static void runGo(run_t *r, const rxdiagBoard_t *b, const char *args)
{
    fakeHal(&r->f, &r->hal);
    r->res = rxdiagRun(&r->hal, b, args);
}

// ---- helpers
static int findLine(fake_t *f, const char *prefix, int from)
{
    for (int i = from; i < f->nlines; i++) {
        if (strncmp(f->lines[i], prefix, strlen(prefix)) == 0) {
            return i;
        }
    }
    return -1;
}
static int countLines(fake_t *f, const char *prefix)
{
    int n = 0;
    for (int i = 0; i < f->nlines; i++) {
        n += strncmp(f->lines[i], prefix, strlen(prefix)) == 0;
    }
    return n;
}
static bool field(const char *line, const char *key, char *out, size_t cap)
{
    char k[64];
    snprintf(k, sizeof k, ",%s=", key);
    const char *p = strstr(line, k);
    if (!p) return false;
    p += strlen(k);
    size_t n = strcspn(p, ",\r");
    if (n >= cap) n = cap - 1;
    memcpy(out, p, n);
    out[n] = 0;
    return true;
}
static bool sfield(const char *line, int idx, long long *out) // S line field idx (0 = "S")
{
    const char *p = line;
    for (int i = 0; i < idx; i++) {
        p = strchr(p, ',');
        if (!p) return false;
        p++;
    }
    *out = strtoll(p, NULL, 10);
    return true;
}
static bool sfieldU(const char *line, int idx, unsigned long long *out)
{
    const char *p = line;
    for (int i = 0; i < idx; i++) {
        p = strchr(p, ',');
        if (!p) return false;
        p++;
    }
    *out = strtoull(p, NULL, 10);
    return true;
}
static bool endsSidleLnaOff(fake_t *f)
{
    return f->frames > 0 && f->lastKind == 'S' && f->lastHdr == 0x36 && !f->lna;
}

// Common invariants for every scenario.
static void invariants(run_t *r, const char *name)
{
    fake_t *f = &r->f;
    CHECK(f->violations == 0, "%s: SPI violation: %s", name, f->vmsg);
    if (f->frames > 0) {
        CHECK(endsSidleLnaOff(f), "%s: last frame 0x%02X kind %c lna=%d", name, f->lastHdr, f->lastKind, f->lna);
    } else {
        CHECK(!f->lna && !f->lnaEverOn, "%s: zero-frame path touched LNA", name);
    }
    CHECK(f->maxRssiBetweenPolls <= 130, "%s: %u RSSI reads between polls", name, f->maxRssiBetweenPolls);
    // header bytes in recorded head
    for (uint64_t i = 0; i < f->frames && i < FAKE_HEAD; i++) {
        uint8_t h = f->headHdr[i];
        CHECK(h != 0x31 && h != 0x35 && h != 0x3A && h != 0x3B && h != 0x3F && !(h >= 0xB0 && h <= 0xBD) && h != 0x7F && h != 0xBF && h != 0xFF && h != 0x32 && h != 0x37,
              "%s: forbidden header 0x%02X", name, h);
    }
    // record shapes
    unsigned long long expectSeq = 0, lastT = 0;
    bool haveT = false;
    for (int i = 0; i < f->nlines; i++) {
        const char *l = f->lines[i];
        size_t n = strlen(l);
        CHECK(n >= 3 && l[n - 2] == '\r' && l[n - 1] == '\n', "%s: line %d not CRLF", name, i);
        size_t body = n - 2;
        char t = l[0];
        CHECK(strchr("IHSEX", t) && l[1] == ',', "%s: bad record type: %s", name, l);
        CHECK(body <= ((t == 'I' || t == 'H') ? 480u : 96u), "%s: line too long (%zu)", name, body);
        CHECK(strchr(l, ' ') == NULL, "%s: space in record", name);
        if (t == 'S') {
            unsigned long long seq, tu;
            sfieldU(l, 1, &seq);
            sfieldU(l, 2, &tu);
            CHECK(seq >= expectSeq, "%s: seq %llu < %llu", name, seq, expectSeq);
            expectSeq = seq + 1;
            CHECK(!haveT || tu > lastT, "%s: t not increasing", name);
            lastT = tu; haveT = true;
        } else if (t == 'E' && strstr(l, ",ENOSAMP,")) {
            char d[32];
            field(l, "seq", d, sizeof d);
            CHECK(strtoull(d, NULL, 10) >= expectSeq, "%s: ENOSAMP seq", name);
            expectSeq = strtoull(d, NULL, 10) + 1;
        } else if (t == 'X') {
            unsigned long long seq;
            sfieldU(l, 1, &seq);
            CHECK(seq == expectSeq, "%s: X seq %llu expected %llu", name, seq, expectSeq);
        }
    }
}

// Count seq contiguity exactly: S lines + ENOSAMP lines with no gaps (valid when nothing was dropped).
static void contiguous(fake_t *f, const char *name)
{
    unsigned long long expect = 0;
    for (int i = 0; i < f->nlines; i++) {
        const char *l = f->lines[i];
        unsigned long long seq = 0;
        if (l[0] == 'S') sfieldU(l, 1, &seq);
        else if (l[0] == 'E' && strstr(l, ",ENOSAMP,")) { char d[32]; field(l, "seq", d, sizeof d); seq = strtoull(d, NULL, 10); }
        else continue;
        CHECK(seq == expect, "%s: seq gap: got %llu expected %llu", name, seq, expect);
        expect = seq + 1;
    }
}

// ---- hooks
typedef struct { const char *type; int k; int seen; void (*act)(fake_t *); } hk_t;
static hk_t hk;
static int stopAfterS; // if >0: host byte scheduled when this many S lines have been seen
static int sSeen;
static void actStop(fake_t *f);
static void hookFn(fake_t *f, const char *line)
{
    if (line[0] == hk.type[0] && ++hk.seen == hk.k) {
        hk.act(f);
    }
    if (line[0] == 'S' && stopAfterS && ++sSeen == stopAfterS) {
        actStop(f);
    }
}
static void setHook(run_t *r, const char *type, int k, void (*act)(fake_t *))
{
    hk.type = type; hk.k = k; hk.seen = 0; hk.act = act;
    stopAfterS = 0; sSeen = 0;
    r->f.hook = hookFn;
}
static void actStop(fake_t *f) { f->rxAt = fakeNow(f) + 5000; f->rxCount = 1; }
static void actStopNow(fake_t *f) { f->rxAt = fakeNow(f); f->rxCount = 3; }
static void actUsbDown(fake_t *f) { f->usbDownAt = fakeNow(f); }
static void actFail999(fake_t *f) { f->txFailFrom = fakeNow(f); f->txFailUntil = fakeNow(f) + 990000; f->rxAt = 0; }
static void actFailForever(fake_t *f) { f->txFailFrom = fakeNow(f); f->txFailUntil = ~(uint64_t)0; }
static void actDisagree1(fake_t *f) { f->disagreeFrom = fakeNow(f); f->disagreeTo = fakeNow(f) + 11000; }
static void actDisagree2(fake_t *f) { f->disagreeFrom = fakeNow(f); f->disagreeTo = fakeNow(f) + 26000; }
static void actEstate(fake_t *f) { f->estateAt = fakeNow(f) + 3000; }

// ---- vectors
static void testVectors(const char *path)
{
    FILE *fp = fopen(path, "r");
    CHECK(fp != NULL, "cannot open vectors %s", path);
    if (!fp) return;
    char line[1024];
    int rows = 0;
    while (fgets(line, sizeof line, fp)) {
        char *nl = strpbrk(line, "\r\n");
        if (nl) *nl = 0;
        if (line[0] == '#' || line[0] == 0) continue;
        char kind[32];
        if (sscanf(line, "%31s", kind) != 1) continue;
        rows++;
        if (!strcmp(kind, "freq")) {
            unsigned long khz; char ok[16]; unsigned long word, hz; int spur;
            int n = sscanf(line, "freq %lu %15s %lx %lu %d", &khz, ok, &word, &hz, &spur);
            uint32_t w = 0, h = 0; bool sp = false;
            bool r = rxdiagFreqWord((uint32_t)khz, &w, &h, &sp);
            if (!strcmp(ok, "ok")) {
                CHECK(n == 5 && r && w == word && h == hz && sp == (spur != 0), "freq %lu: got %d 0x%X %u %d", khz, r, w, h, sp);
                // end-to-end through H
                run_t R; runInit(&R);
                setHook(&R, "H", 1, actStopNow);
                char a[64]; snprintf(a, sizeof a, "stream %lu", khz);
                runGo(&R, &board, a);
                int hi = findLine(&R.f, "H,", 0);
                char v[32];
                CHECK(hi >= 0 && R.res == RXDIAG_EXIT_HOST, "freq %lu: no H / result %d", khz, R.res);
                if (hi >= 0) {
                    char exp[32];
                    CHECK(field(R.f.lines[hi], "freq_word", v, sizeof v) && strtoul(v, NULL, 16) == word, "freq_word %s", v);
                    snprintf(exp, sizeof exp, "%lu", hz);
                    CHECK(field(R.f.lines[hi], "freq_set_hz", v, sizeof v) && !strcmp(v, exp), "freq_set_hz %s", v);
                    CHECK(field(R.f.lines[hi], "spur", v, sizeof v) && atoi(v) == spur, "spur %s", v);
                    CHECK(R.f.reg[0x0D] == (word >> 16) && R.f.reg[0x0E] == ((word >> 8) & 0xFF) && R.f.reg[0x0F] == (word & 0xFF), "FREQ regs");
                }
                invariants(&R, "freq-stream");
                fakeFree(&R.f);
            } else {
                CHECK(!r, "freq %lu should be EFREQ", khz);
                run_t R; runInit(&R);
                char a[64]; snprintf(a, sizeof a, "stream %lu", khz);
                runGo(&R, &board, a);
                CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0 && countLines(&R.f, "E,") == 1 && findLine(&R.f, "E,", 0) >= 0 &&
                      strstr(R.f.lines[0], ",EFREQ,") != NULL, "EFREQ run %lu", khz);
                invariants(&R, "efreq");
                fakeFree(&R.f);
            }
        } else if (!strcmp(kind, "bw")) {
            unsigned long label; char ok[16]; unsigned long m4, hz;
            int n = sscanf(line, "bw %lu %15s %lx %lu", &label, ok, &m4, &hz);
            uint8_t m = 0; uint32_t bh = 0;
            bool r = rxdiagBwLookup((uint32_t)label, &m, &bh);
            if (!strcmp(ok, "ok")) {
                CHECK(n == 4 && r && m == m4 && bh == hz, "bw %lu: %d 0x%02X %u", label, r, m, bh);
                run_t R; runInit(&R);
                setHook(&R, "H", 1, actStopNow);
                char a[64]; snprintf(a, sizeof a, "stream 2440000 10 %lu", label);
                runGo(&R, &board, a);
                int hi = findLine(&R.f, "H,", 0);
                char v[32], exp[32];
                snprintf(exp, sizeof exp, "%lu", hz);
                CHECK(hi >= 0 && field(R.f.lines[hi], "bw_hz", v, sizeof v) && !strcmp(v, exp), "H bw_hz for %lu", label);
                CHECK(R.f.reg[0x10] == m4, "MDMCFG4 reg 0x%02X expected 0x%02lX", R.f.reg[0x10], m4);
                invariants(&R, "bw-stream");
                fakeFree(&R.f);
            } else {
                CHECK(!r, "bw %lu should be refused", label);
                run_t R; runInit(&R);
                char a[64]; snprintf(a, sizeof a, "stream 2440000 10 %lu", label);
                runGo(&R, &board, a);
                CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0 && strstr(R.f.lines[0], ",EARG,") != NULL, "EARG run bw %lu", label);
                invariants(&R, "earg-bw");
                fakeFree(&R.f);
            }
        } else if (!strcmp(kind, "window")) {
            unsigned long wms; char ok[16];
            sscanf(line, "window %lu %15s", &wms, ok);
            CHECK(rxdiagWindowValid((uint32_t)wms) == !strcmp(ok, "ok"), "window %lu", wms);
            run_t R; runInit(&R);
            char a[64]; snprintf(a, sizeof a, "stream 2440000 %lu", wms);
            if (!strcmp(ok, "ok")) setHook(&R, "H", 1, actStopNow);
            runGo(&R, &board, a);
            if (!strcmp(ok, "ok")) {
                int hi = findLine(&R.f, "H,", 0); char v[32], exp[32];
                snprintf(exp, sizeof exp, "%lu", wms * 1000);
                CHECK(hi >= 0 && field(R.f.lines[hi], "window_us", v, sizeof v) && !strcmp(v, exp), "window_us for %lu", wms);
            } else {
                CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0, "window %lu refused", wms);
            }
            invariants(&R, "window-vec");
            fakeFree(&R.f);
        } else if (!strcmp(kind, "status")) {
            unsigned a, h; uint8_t o = 0;
            sscanf(line, "status %x %x", &a, &h);
            CHECK(rxdiagStatusHeader((uint8_t)a, &o) && o == h, "status 0x%02X", a);
        } else if (!strcmp(kind, "status_invalid")) {
            unsigned a; uint8_t o = 0x5A;
            sscanf(line, "status_invalid %x", &a);
            CHECK(!rxdiagStatusHeader((uint8_t)a, &o) && o == 0x5A, "status_invalid 0x%02X", a);
        } else if (!strcmp(kind, "micros64")) {
            unsigned long long prev, exp; unsigned long now;
            sscanf(line, "micros64 %llu %lu %llu", &prev, &now, &exp);
            CHECK(rxdiagMicros64(prev, (uint32_t)now) == exp, "micros64 %llu %lu", prev, now);
        } else if (!strcmp(kind, "drate")) {
            unsigned m3; int e; unsigned long exp;
            sscanf(line, "drate %x %d %lu", &m3, &e, &exp);
            run_t R; runInit(&R);
            setHook(&R, "H", 1, actStopNow);
            runGo(&R, &board, "stream 2440000");
            int hi = findLine(&R.f, "H,", 0); char v[32], ex[32];
            snprintf(ex, sizeof ex, "%lu", exp);
            CHECK(hi >= 0 && field(R.f.lines[hi], "drate_baud", v, sizeof v) && !strcmp(v, ex), "drate_baud %s", v);
            CHECK(R.f.reg[0x11] == m3, "MDMCFG3 0x%02X", R.f.reg[0x11]);
            fakeFree(&R.f);
        } else if (!strcmp(kind, "sline")) {
            char *p = line + 6, *arrow = strstr(line, " => ");
            CHECK(arrow != NULL, "sline format");
            if (!arrow) continue;
            *arrow = 0;
            const char *expect = arrow + 4;
            unsigned long seq; unsigned long long t; unsigned marc, flags; char smp[512];
            sscanf(p, "%lu %llu %u %u %511s", &seq, &t, &marc, &flags, smp);
            int8_t s[256]; uint32_t n = 0;
            for (char *tok = strtok(smp, ","); tok; tok = strtok(NULL, ",")) s[n++] = (int8_t)atoi(tok);
            char out[128];
            size_t len = rxdiagFormatS(out, sizeof out, (uint32_t)seq, t, s, n, (uint8_t)marc, (uint8_t)flags);
            CHECK(len == strlen(expect) && !strcmp(out, expect), "sline: got '%s' expected '%s'", out, expect);
        } else {
            CHECK(0, "unknown vector kind %s", kind);
        }
    }
    CHECK(rows > 60, "vectors rows read: %d", rows);
    fclose(fp);
}

// ---- scenarios
static void testInfo(void)
{
    run_t R; runInit(&R);
    runGo(&R, &board, "info");
    fake_t *f = &R.f;
    CHECK(R.res == RXDIAG_DONE, "info result %d", R.res);
    CHECK(f->nlines == 1 && f->lines[0][0] == 'I', "info lines %d", f->nlines);
    const char *l = f->lines[0];
    char v[64];
    CHECK(field(l, "reset_ok", v, sizeof v) && !strcmp(v, "1"), "reset_ok");
    CHECK(field(l, "rb_ok", v, sizeof v) && !strcmp(v, "1"), "rb_ok");
    CHECK(field(l, "part", v, sizeof v) && !strcmp(v, "0x80"), "part %s", v);
    CHECK(field(l, "ver", v, sizeof v) && !strcmp(v, "0x03"), "ver %s", v);
    CHECK(field(l, "motor_dev", v, sizeof v) && !strcmp(v, "null"), "motor_dev");
    CHECK(field(l, "motor_proto", v, sizeof v) && !strcmp(v, "DISABLED"), "motor_proto");
    CHECK(field(l, "spi_hz", v, sizeof v) && !strcmp(v, "5250000"), "spi_hz");
    CHECK(field(l, "txen", v, sizeof v) && !strcmp(v, "A8"), "txen");
    CHECK(strstr(l, "I,proto=1,fw=A1B2C3D4,bf=ABCDEF1,build=MATEKF411RXDIAG,board=M41R,usb=MATEKF411RX-RXDIAG,reset_ok=") == l, "I prefix: %s", l);
    CHECK(strstr(l, ",vbat_cv=0\r\n") != NULL, "vbat tail");
    static const uint8_t hdr[] = { 0x30, 0x8E, 0x0F, 0x8F, 0x0F, 0xF0, 0xF1, 0x36 };
    CHECK(f->frames == 8, "info frames %llu", (unsigned long long)f->frames);
    for (int i = 0; i < 8 && i < (int)f->frames; i++) CHECK(f->headHdr[i] == hdr[i], "info frame %d = 0x%02X", i, f->headHdr[i]);
    CHECK(f->headData[2] == 0x5A && f->headData[4] == 0xEC, "FREQ0 write/restore data");
    CHECK(f->reg[0x0F] == 0xEC, "FREQ0 restored");
    CHECK(!f->lnaEverOn, "info LNA");
    invariants(&R, "info");
    fakeFree(&R.f);

    // bad reset / readback: info still prints I with 0 flags
    runInit(&R); R.f.resetBad = true; runGo(&R, &board, "info");
    CHECK(R.res == RXDIAG_DONE && strstr(R.f.lines[0], ",reset_ok=0,") != NULL, "info resetBad");
    invariants(&R, "info-resetbad"); fakeFree(&R.f);
    runInit(&R); R.f.rbBad = true; runGo(&R, &board, "info");
    CHECK(R.res == RXDIAG_DONE && strstr(R.f.lines[0], ",rb_ok=0,") != NULL && strstr(R.f.lines[0], ",reset_ok=1,") != NULL, "info rbBad");
    invariants(&R, "info-rbbad"); fakeFree(&R.f);
}

static void testNoChip(void)
{
    for (int which = 0; which < 2; which++) {
        run_t R; runInit(&R);
        if (which == 0) R.f.resetBad = true; else R.f.rbBad = true;
        runGo(&R, &board, "stream 2440000");
        CHECK(R.res == RXDIAG_EXIT_RADIO, "nochip result %d", R.res);
        CHECK(R.f.nlines == 1 && strstr(R.f.lines[0], ",ENOCHIP,") != NULL, "ENOCHIP line");
        CHECK(findLine(&R.f, "H,", 0) < 0 && !R.f.lnaEverOn, "no H / LNA never on");
        CHECK(R.f.frames > 0 && R.f.lastHdr == 0x36, "SIDLE");
        invariants(&R, which ? "nochip-rb" : "nochip-reset");
        fakeFree(&R.f);
    }
}

static void testArgs(void)
{
    static const char *bad[] = { "", "bogus", "info x", "stream", "stream abc", "stream 2440000 0", "stream 2440000 1001", "stream 2440000 10 100",
        "stream 2440000 10 812 7", "stream -1", "stream +2440000", "stream 2440000 1x", "stream 2440000 10 812 1 2", "info stream", "stream 2440000 ,", "stream 2440000 5000000000" };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        run_t R; runInit(&R);
        runGo(&R, &board, bad[i]);
        CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0 && R.f.nlines == 1 && strstr(R.f.lines[0], ",EARG,") != NULL,
              "EARG '%s': res %d frames %llu line %s", bad[i], R.res, (unsigned long long)R.f.frames, R.f.nlines ? R.f.lines[0] : "-");
        invariants(&R, "earg");
        fakeFree(&R.f);
    }
    static const char *bf[] = { "stream 0", "stream 2399999", "stream 2483501", "stream 99999999999999" };
    for (size_t i = 0; i < sizeof bf / sizeof bf[0]; i++) {
        run_t R; runInit(&R);
        runGo(&R, &board, bf[i]);
        CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0 && R.f.nlines == 1 && strstr(R.f.lines[0], ",EFREQ,") != NULL, "EFREQ '%s'", bf[i]);
        invariants(&R, "efreq2");
        fakeFree(&R.f);
    }
    run_t R; runInit(&R);
    runGo(&R, &board, NULL);
    CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0, "NULL args");
    fakeFree(&R.f);
}

static void testMotor(void)
{
    rxdiagBoard_t b = board;
    for (int which = 0; which < 3; which++) {
        b = board;
        if (which == 0) b.motorDevNull = false;
        if (which == 1) b.motorProto = "DSHOT600";
        if (which == 2) { b.motorProto = "DSHOT600"; b.motorDevNull = false; }
        run_t R; runInit(&R);
        runGo(&R, &b, "stream 2440000");
        CHECK(R.res == RXDIAG_ERR_REFUSED && R.f.frames == 0 && R.f.nlines == 1 && strstr(R.f.lines[0], ",EMOTOR,") != NULL, "EMOTOR %d", which);
        invariants(&R, "emotor");
        fakeFree(&R.f);
        // info is not gated, reports active
        runInit(&R);
        runGo(&R, &b, "info");
        CHECK(R.res == RXDIAG_DONE && (strstr(R.f.lines[0], "motor_dev=active") || strstr(R.f.lines[0], "motor_proto=DSHOT600")), "info motor %d", which);
        fakeFree(&R.f);
    }
}

static void testStreamTrace(void)
{
    run_t R; runInit(&R);
    setHook(&R, "S", 2, actStop);
    R.f.rssiMode = RSSI_RAMP;
    runGo(&R, &board, "stream 2440000 10 812");
    fake_t *f = &R.f;
    CHECK(R.res == RXDIAG_EXIT_HOST, "stream result %d", R.res);
    CHECK(f->headHdr[0] == 0x30 && f->headHdr[1] == 0x8E && f->headHdr[5] == 0xF0 && f->headHdr[6] == 0xF1, "stream liveness prefix");
    CHECK(f->headHdr[11] == 0x0D && f->headHdr[12] == 0x0E && f->headHdr[13] == 0x0F && f->headKind[11] == 'W', "FREQ writes");
    CHECK(f->headData[11] == 0x5D && f->headData[12] == 0xD8 && f->headData[13] == 0x9E, "FREQ bytes 0x5DD89E");
    CHECK(f->headHdr[36] == 0x3E && f->headData[36] == 0 && f->headKind[36] == 'W', "PATABLE=0");
    CHECK(f->headHdr[37] == 0x36 && f->headHdr[38] == 0x34 && f->headKind[37] == 'S', "SIDLE,SRX");
    CHECK(f->headHdr[39] == 0xF5, "MARC poll header 0xF5");
    CHECK(f->reg[0x12] == 0x10 && f->reg[0x08] == 0x32 && f->reg[0x17] == 0x0C && f->reg[0x18] == 0x18, "mode regs");
    CHECK(f->lnaOnCount == 1, "LNA on once");
    CHECK(R.f.drainCalled, "drain");
    int hi = findLine(f, "H,", 0);
    CHECK(hi == 0, "H first");
    char v[64];
    CHECK(field(f->lines[0], "sample_us", v, sizeof v) && atoi(v) > 0 && atoi(v) < 100, "sample_us %s", v);
    CHECK(strstr(f->lines[0], "unit=rssi_raw_s8,dbm_est=raw/2-72,offset_note=typical_uncalibrated") != NULL, "H units");
    CHECK(strstr(f->lines[0], ",ant=1,lna=1,txen=0,spi_hz=5250000,t0_us=") != NULL, "H tail");
    unsigned long long t0 = 0; { char t[32]; field(f->lines[0], "t0_us", t, sizeof t); t0 = strtoull(t, NULL, 10); }
    // window oracle: S stats stay within the value range of their own time span (ramp mode)
    unsigned long long prevEnd = t0;
    for (int i = 1; i < f->nlines; i++) {
        if (f->lines[i][0] != 'S') continue;
        long long n, ch, mn, mx, last, sum; unsigned long long te;
        sfieldU(f->lines[i], 2, &te); sfield(f->lines[i], 3, &n); sfield(f->lines[i], 4, &ch);
        sfield(f->lines[i], 5, &mn); sfield(f->lines[i], 6, &mx); sfield(f->lines[i], 7, &last); sfield(f->lines[i], 8, &sum);
        long long lo = -120 + (long long)((prevEnd / 1000) % 200), hiV = -120 + (long long)((te / 1000) % 200);
        CHECK(mn >= lo && mx <= hiV && last == mx && n > 100 && sum >= n * mn && sum <= n * mx, "S window tag: %s", f->lines[i]);
        CHECK(ch > 0 && ch < n, "ramp changes %lld", ch);
        CHECK(te - prevEnd >= 10000 && te - prevEnd < 12000, "window length %llu", te - prevEnd);
        prevEnd = te;
    }
    CHECK(countLines(f, "S,") == 2, "S count %d", countLines(f, "S,"));
    CHECK(strstr(f->lines[f->nlines - 1], ",host\r\n") != NULL && f->lines[f->nlines - 1][0] == 'X', "X host last");
    CHECK(f->rssiAfterRx <= 130, "stop latency %u", f->rssiAfterRx);
    CHECK(f->rxAt == 0, "RX drained at stop");
    contiguous(f, "stream");
    invariants(&R, "stream");
    fakeFree(&R.f);
}

static void testHostStopLatency(void)
{
    run_t R; runInit(&R);
    setHook(&R, "H", 1, actStopNow);
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_HOST && R.f.rxAt == 0, "host stop immediate");
    CHECK(R.f.rssiAfterRx <= 130, "latency %u", R.f.rssiAfterRx);
    CHECK(countLines(&R.f, "S,") == 0 && strstr(R.f.lines[R.f.nlines - 1], "X,0,") == R.f.lines[R.f.nlines - 1], "X seq 0");
    invariants(&R, "host-stop"); fakeFree(&R.f);
}

static void testEcal(void)
{
    run_t R; runInit(&R);
    R.f.neverRx = true;
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_RADIO, "ECAL result");
    int e = findLine(&R.f, "E,", 0);
    CHECK(e == 0 && strstr(R.f.lines[0], ",ECAL,") && strstr(R.f.lines[1], ",radio\r\n") && R.f.lines[1][0] == 'X', "ECAL then X radio");
    CHECK(findLine(&R.f, "H,", 0) < 0, "no H after ECAL");
    invariants(&R, "ecal"); fakeFree(&R.f);
}

static void testEstate(void)
{
    run_t R;
    runInit(&R);
    // recovered: ESTATE at +3ms after S1; stop after the third S
    setHook(&R, "S", 1, actEstate);
    stopAfterS = 6;
    runGo(&R, &board, "stream 2440000");
    int ei = findLine(&R.f, "E,", 0);
    CHECK(R.res == RXDIAG_EXIT_HOST, "estate recovered result %d", R.res);
    CHECK(ei >= 0 && strstr(R.f.lines[ei], ",ESTATE,marc=17\r\n") != NULL, "ESTATE line: %s", ei >= 0 ? R.f.lines[ei] : "-");
    int si = findLine(&R.f, "S,", ei);
    long long fl = 0;
    CHECK(si >= 0 && sfield(R.f.lines[si], 10, &fl) && (fl & 9) == 9, "flags bit0+bit3 after ESTATE: %s", si >= 0 ? R.f.lines[si] : "-");
    CHECK(si >= 0 && sfield(R.f.lines[si], 9, &fl) && fl == 13, "marc 13 after recovery");
    CHECK(R.f.lnaOnCount == 1, "LNA once");
    contiguous(&R.f, "estate");
    invariants(&R, "estate-rec"); fakeFree(&R.f);

    runInit(&R);
    R.f.estateAt = 30000; R.f.estateStuck = true;
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_RADIO, "estate unrecovered result %d", R.res);
    ei = findLine(&R.f, "E,", 0);
    CHECK(ei >= 0 && strstr(R.f.lines[ei], ",ESTATE,") != NULL && R.f.lines[R.f.nlines - 1][0] == 'X' && strstr(R.f.lines[R.f.nlines - 1], ",radio\r\n"), "ESTATE then X radio");
    invariants(&R, "estate-stuck"); fakeFree(&R.f);
}

static void testEnosamp(void)
{
    run_t R; runInit(&R);
    setHook(&R, "S", 1, actDisagree1);
    stopAfterS = 5;
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_HOST, "single ENOSAMP: result %d", R.res);
    CHECK(countLines(&R.f, "E,") == 1 && strstr(R.f.lines[findLine(&R.f, "E,", 0)], ",ENOSAMP,seq=1\r\n"), "one ENOSAMP seq=1");
    CHECK(countLines(&R.f, "S,") >= 3, "samples resume: S count %d", countLines(&R.f, "S,"));
    // bit1 set on partial window
    bool bit1 = false;
    for (int i = 0; i < R.f.nlines; i++) { long long fl; if (R.f.lines[i][0] == 'S' && sfield(R.f.lines[i], 10, &fl) && (fl & 2)) bit1 = true; }
    CHECK(bit1, "bit1 on a discarded-sample window");
    contiguous(&R.f, "enosamp1");
    invariants(&R, "enosamp1"); fakeFree(&R.f);

    runInit(&R);
    setHook(&R, "S", 1, actDisagree2);
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_RADIO, "double ENOSAMP result %d", R.res);
    CHECK(countLines(&R.f, "E,") == 2 && R.f.lines[R.f.nlines - 1][0] == 'X' && strstr(R.f.lines[R.f.nlines - 1], ",radio\r\n"), "two ENOSAMP then X radio");
    contiguous(&R.f, "enosamp2");
    invariants(&R, "enosamp2"); fakeFree(&R.f);
}

static void testUsb(void)
{
    run_t R; runInit(&R);
    setHook(&R, "S", 2, actUsbDown);
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_USB, "usb result %d", R.res);
    CHECK(R.f.lines[R.f.nlines - 1][0] == 'X' && strstr(R.f.lines[R.f.nlines - 1], ",usb\r\n"), "X usb");
    invariants(&R, "usb"); fakeFree(&R.f);
}

static void testTxFailures(void)
{
    // fail for ~990 ms with 1 ms windows, then succeed: bit2, no exit
    run_t R; runInit(&R);
    setHook(&R, "S", 1, actFail999);
    stopAfterS = 5;
    runGo(&R, &board, "stream 2440000 1");
    CHECK(R.res == RXDIAG_EXIT_HOST, "tx 999 result %d (must not stall)", R.res);
    long long fl;
    int firstAfter = -1;
    for (int i = 1; i < R.f.nlines; i++) if (R.f.lines[i][0] == 'S') { if (sfield(R.f.lines[i], 10, &fl) && (fl & 4) && firstAfter < 0) firstAfter = i; }
    CHECK(firstAfter > 0, "bit2 set after tx recovery");
    invariants(&R, "tx999"); fakeFree(&R.f);

    runInit(&R);
    setHook(&R, "S", 1, actFailForever);
    runGo(&R, &board, "stream 2440000 1");
    CHECK(R.res == RXDIAG_EXIT_USBSTALL, "usbstall result %d", R.res);
    CHECK(R.f.lna == false && R.f.lastHdr == 0x36, "usbstall SIDLE/LNA");
    invariants(&R, "usbstall"); fakeFree(&R.f);
}

static void testWindows(void)
{
    for (int w = 0; w < 2; w++) {
        run_t R; runInit(&R);
        R.f.rssiMode = RSSI_CONST;
        R.f.rssiConst = -90;
        setHook(&R, "S", 3, actStopNow);
        runGo(&R, &board, w ? "stream 2440000 1000" : "stream 2440000 1");
        CHECK(R.res == RXDIAG_EXIT_HOST, "window run %d", R.res);
        CHECK(countLines(&R.f, "S,") == 3, "3 S lines (%d)", countLines(&R.f, "S,"));
        for (int i = 0; i < R.f.nlines; i++) {
            if (R.f.lines[i][0] != 'S') continue;
            long long n, ch, mn, mx, last, sum;
            sfield(R.f.lines[i], 3, &n); sfield(R.f.lines[i], 4, &ch); sfield(R.f.lines[i], 5, &mn);
            sfield(R.f.lines[i], 6, &mx); sfield(R.f.lines[i], 7, &last); sfield(R.f.lines[i], 8, &sum);
            CHECK(ch == 0 && mn == -90 && mx == -90 && last == -90 && sum == -90 * n && n > 0, "constant RSSI: %s", R.f.lines[i]);
        }
        contiguous(&R.f, "windows");
        invariants(&R, w ? "window1000" : "window1"); fakeFree(&R.f);
    }
}

static void testClockWrap(void)
{
    run_t R; runInit(&R);
    R.f.now = 0xFFFFFFFFull - 25000;
    R.f.rssiMode = RSSI_CONST;
    setHook(&R, "S", 5, actStopNow);
    runGo(&R, &board, "stream 2440000");
    CHECK(R.res == RXDIAG_EXIT_HOST, "wrap result");
    unsigned long long last = 0; bool wrapped = false;
    for (int i = 0; i < R.f.nlines; i++) {
        unsigned long long t;
        if (R.f.lines[i][0] == 'S') { sfieldU(R.f.lines[i], 2, &t); if (t > 0xFFFFFFFFull) wrapped = true; CHECK(t > last, "t monotonic across wrap"); last = t; }
    }
    CHECK(wrapped, "t_us exceeded 2^32");
    invariants(&R, "wrap"); fakeFree(&R.f);
}

static void testNegative(void)
{
    run_t R; runInit(&R);
    R.f.rssiMode = RSSI_CONST;
    R.f.rssiConst = -128;
    setHook(&R, "S", 1, actStopNow);
    runGo(&R, &board, "stream 2440000");
    int si = findLine(&R.f, "S,", 0); long long mn, mx, last;
    sfield(R.f.lines[si], 5, &mn); sfield(R.f.lines[si], 6, &mx); sfield(R.f.lines[si], 7, &last);
    CHECK(mn == -128 && mx == -128 && last == -128, "min -128 handled");
    invariants(&R, "neg"); fakeFree(&R.f);
}


// ---- events mode (proto 2)
static void evInvariants(run_t *r, const char *name)
{
    fake_t *f = &r->f;
    CHECK(f->violations == 0, "%s: violation: %s", name, f->vmsg);
    if (f->frames > 0) {
        CHECK(endsSidleLnaOff(f), "%s: last frame 0x%02X kind %c lna=%d", name, f->lastHdr, f->lastKind, f->lna);
    }
    CHECK(!f->armed, "%s: edge capture left armed", name);
    CHECK(f->reg[0x02] == 0x2E || f->frames == 0 || !f->lnaEverOn, "%s: IOCFG0 left 0x%02X", name, f->reg[0x02]);
    CHECK(f->maxRssiBetweenPolls <= 130, "%s: %u RSSI reads between polls", name, f->maxRssiBetweenPolls);
    for (int i = 0; i < f->nlines; i++) {
        const char *l = f->lines[i];
        size_t n = strlen(l);
        CHECK(n >= 3 && l[n - 2] == '\r' && l[n - 1] == '\n', "%s: line %d not CRLF", name, i);
        CHECK(strchr("HBCEX", l[0]) && l[1] == ',', "%s: bad record type: %s", name, l);
        CHECK(n - 2 <= (l[0] == 'H' ? 480u : l[0] == 'C' ? 160u : 96u), "%s: line too long", name);
    }
}

static int evC(fake_t *f, int idx, unsigned long long *v) // last C line field idx
{
    for (int i = f->nlines - 1; i >= 0; i--) {
        if (f->lines[i][0] == 'C') {
            sfieldU(f->lines[i], idx, v);
            return i;
        }
    }
    return -1;
}

static void actEvStop(fake_t *f) { f->rxAt = 95000; f->rxCount = 1; }
static void evSetup(run_t *r)
{
    runInit(r);
    r->f.rssiConst = -100;
    r->f.burstRssi = 40;
    // bursts after settle (~1.1 ms + preamble): 40 us, 300 us, 900 us, plus one 3 ms
    const uint64_t on[4] = { 20000, 30000, 45000, 60000 }, len[4] = { 40, 300, 900, 3000 };
    for (int i = 0; i < 4; i++) { r->f.bOn[i] = on[i]; r->f.bOff[i] = on[i] + len[i]; }
    r->f.nb = 4;
    setHook(r, "H", 1, actEvStop);
}

static void testEventsBasic(void)
{
    run_t R; evSetup(&R);
    runGo(&R, &board, "events 2402000 10 812");
    fake_t *f = &R.f;
    evInvariants(&R, "events");
    CHECK(R.res == RXDIAG_EXIT_HOST, "events res %d", R.res);
    int h = findLine(f, "H,proto=2,mode=events", 0);
    CHECK(h >= 0, "events: no H");
    char v[32];
    if (h >= 0) {
        CHECK(field(f->lines[h], "gdo_ok", v, sizeof v) && !strcmp(v, "1"), "gdo_ok");
        char a[32], b[32];
        CHECK(field(f->lines[h], "freq_word", a, sizeof a) && field(f->lines[h], "freq_rb", b, sizeof b) && !strcmp(a, b), "freq_rb");
        CHECK(field(f->lines[h], "iocfg0", v, sizeof v) && !strcmp(v, "0x0E"), "iocfg0");
        CHECK(field(f->lines[h], "level0", v, sizeof v) && !strcmp(v, "0"), "level0");
    }
    CHECK(countLines(f, "B,") == 4, "events: %d B lines", countLines(f, "B,"));
    const long long expDur[4] = { 40, 300, 900, 3000 };
    int bi = 0;
    for (int i = 0; i < f->nlines; i++) {
        if (f->lines[i][0] != 'B') continue;
        long long seq, t, dur, peak, n;
        sfield(f->lines[i], 1, &seq); sfield(f->lines[i], 2, &t); sfield(f->lines[i], 3, &dur);
        sfield(f->lines[i], 4, &peak); sfield(f->lines[i], 5, &n);
        CHECK(seq == bi, "B seq %lld", seq);
        if (bi < 4) {
            CHECK(t == (long long)f->bOn[bi] && dur == expDur[bi], "B %d: t=%lld dur=%lld", bi, t, dur);
            if (bi > 0) CHECK(peak == 40 && n > 0, "B %d peak %lld n %lld", bi, peak, n);
        }
        bi++;
    }
    unsigned long long edges = 0, lost = 0, bseq = 0, bfail = 0, orphan = 0;
    CHECK(evC(f, 4, &edges) >= 0, "no C");
    evC(f, 5, &lost); evC(f, 6, &bseq); evC(f, 7, &bfail); evC(f, 8, &orphan);
    CHECK(edges == 8 && lost == 0 && bseq == 4 && bfail == 0 && orphan == 0, "C counters %llu %llu %llu %llu %llu", edges, lost, bseq, bfail, orphan);
    // C windows tile time: span sum == last t - t0
    int nc = countLines(f, "C,");
    CHECK(nc >= 8, "C lines %d", nc);
    unsigned long long prevT = 0;
    for (int i = 0; i < f->nlines; i++) {
        if (f->lines[i][0] != 'C') continue;
        unsigned long long t, sp;
        sfieldU(f->lines[i], 2, &t); sfieldU(f->lines[i], 3, &sp);
        if (prevT) CHECK(t - prevT == sp, "C span %llu vs dt %llu", sp, t - prevT);
        prevT = t;
    }
    CHECK(f->antSetCalled && f->ant, "ant default high");
}

static void testEventsGdo(void)
{
    run_t R; evSetup(&R);
    R.f.gdoUnwired = true;
    runGo(&R, &board, "events 2402000");
    evInvariants(&R, "gdo-unwired");
    CHECK(R.res == RXDIAG_EXIT_RADIO && findLine(&R.f, "E,", 0) >= 0 && strstr(R.f.lines[findLine(&R.f, "E,", 0)], "EGDO"), "unwired: res %d", R.res);
    CHECK(!R.f.lnaEverOn, "unwired: LNA turned on");
    CHECK(R.f.reg[0x02] == 0x2E, "unwired: IOCFG0 0x%02X", R.f.reg[0x02]);

    run_t Q; evSetup(&Q);
    Q.f.noGdoHal = true;
    runGo(&Q, &board, "events 2402000");
    CHECK(Q.res == RXDIAG_ERR_REFUSED && Q.f.frames == 0, "nohal: res %d frames %llu", Q.res, (unsigned long long)Q.f.frames);
}

static void testEventsArgs(void)
{
    const char *bad[] = { "events", "events 2402000 0", "events 2402000 10 811", "events 2402000 10 812 256",
                          "events 2402000 10 812 3 64 2", "events 2402000 10 812 3 64 1 9", "events x" };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        run_t R; runInit(&R);
        runGo(&R, &board, bad[i]);
        CHECK(R.res == RXDIAG_ERR_ARG && R.f.frames == 0, "args '%s': res %d", bad[i], R.res);
        fakeFree(&R.f);
    }
    run_t R; evSetup(&R);
    runGo(&R, &board, "events 2480000 5 541 7 71 0");
    evInvariants(&R, "events-args");
    int h = findLine(&R.f, "H,", 0);
    char v[16];
    CHECK(h >= 0 && field(R.f.lines[h], "agcctrl2", v, sizeof v) && !strcmp(v, "0x07"), "agc2");
    CHECK(h >= 0 && field(R.f.lines[h], "agcctrl1", v, sizeof v) && !strcmp(v, "0x47"), "agc1");
    CHECK(h >= 0 && field(R.f.lines[h], "ant", v, sizeof v) && !strcmp(v, "0"), "ant");
    CHECK(R.f.antSetCalled && !R.f.ant, "ant low");
    rxdiagBoard_t b2 = board;
    b2.motorProto = "DSHOT600";
    run_t M; evSetup(&M);
    runGo(&M, &b2, "events 2402000");
    CHECK(M.res == RXDIAG_ERR_REFUSED && M.f.frames == 0 && findLine(&M.f, "E,", 0) >= 0, "motor gate");
}

static void actFailShort(fake_t *f) { f->txFailFrom = fakeNow(f); f->txFailUntil = 33000; actEvStop(f); }
static void testEventsDrops(void)
{
    run_t R; evSetup(&R);
    R.f.lostInject = 2; // first burst's two edges lost in the ring
    setHook(&R, "H", 1, actFailShort); // tx fails until t=33 ms: burst 2 B record is lost
    runGo(&R, &board, "events 2402000 10 812");
    fake_t *f = &R.f;
    evInvariants(&R, "drops");
    unsigned long long edges = 0, lost = 0, bseq = 0, bfail = 0;
    evC(f, 4, &edges); evC(f, 5, &lost); evC(f, 6, &bseq); evC(f, 7, &bfail);
    CHECK(edges == 8 && lost == 2 && bseq == 3 && bfail == 1, "drops: %llu %llu %llu %llu", edges, lost, bseq, bfail);
    CHECK(countLines(f, "B,") == 2, "drops: B lines %d", countLines(f, "B,"));
    bool flagged = false;
    for (int i = 0; i < f->nlines; i++) {
        unsigned long long fl;
        if (f->lines[i][0] == 'C' && sfieldU(f->lines[i], 20, &fl) && (fl & 4)) flagged = true;
    }
    CHECK(flagged, "drops: no C with dropped flag");
}


// ---- freq mode (proto 3): FREQEST readout, receive only
static void fqInvariants(run_t *r, const char *name)
{
    fake_t *f = &r->f;
    CHECK(f->violations == 0, "%s: violation: %s", name, f->vmsg);
    if (f->frames > 0) {
        CHECK(endsSidleLnaOff(f), "%s: last frame 0x%02X kind %c lna=%d", name, f->lastHdr, f->lastKind, f->lna);
    }
    CHECK(!f->armed, "%s: edge capture armed", name);
    CHECK(f->reg[0x02] == 0x2E || !f->lnaEverOn, "%s: IOCFG0 0x%02X", name, f->reg[0x02]);
    CHECK(f->reg[0x3E] == 0x00 || f->frames == 0, "%s: PATABLE written nonzero", name);
    for (int i = 0; i < f->nlines; i++) {
        const char *l = f->lines[i];
        size_t n = strlen(l);
        CHECK(n >= 3 && l[n - 2] == '\r' && l[n - 1] == '\n', "%s: line %d not CRLF", name, i);
        CHECK(strchr("HFEX", l[0]) && l[1] == ',', "%s: bad record type: %s", name, l);
        CHECK(n - 2 <= (l[0] == 'F' || l[0] == 'H' ? 480u : 96u), "%s: line too long", name);
    }
}
static void fqSetup(run_t *r)
{
    runInit(r);
    r->f.rssiConst = -100;
    r->f.feStale = 99;      // must never be reported when there is no carrier
}
static long long fqF(fake_t *f, int line, int idx)
{
    long long v = 0;
    sfield(f->lines[line], idx, &v);
    return v;
}

static void testFreqCarrier(void)
{
    run_t R; fqSetup(&R);
    R.f.fqOn = 0; R.f.fqOff = ~(uint64_t)0; R.f.feVal = -7;
    runGo(&R, &board, "freq 2402000 10 812 251 64 50");
    fake_t *f = &R.f;
    fqInvariants(&R, "freq");
    CHECK(R.res == RXDIAG_DONE, "freq res %d", R.res);
    int h = findLine(f, "H,proto=3,mode=freq", 0);
    CHECK(h >= 0, "freq: no H");
    char v[24];
    CHECK(h >= 0 && field(f->lines[h], "freq_word", v, sizeof v) && field(f->lines[h], "freq_rb", v, sizeof v), "freq: H fields");
    CHECK(h >= 0 && field(f->lines[h], "txen", v, sizeof v) && !strcmp(v, "0"), "freq: txen=0");
    CHECK(h >= 0 && field(f->lines[h], "fscal1", v, sizeof v), "freq: fscal1 reported");
    CHECK(h >= 0 && field(f->lines[h], "cal_us", v, sizeof v), "freq: cal_us reported");
    int nF = countLines(f, "F,");
    CHECK(nF >= 4 && nF <= 6, "freq: %d F lines", nF);
    CHECK(findLine(f, "X,", 0) >= 0 && strstr(f->lines[f->nlines - 1], ",done") != NULL, "freq: ends with X done");
    for (int i = 0; i < f->nlines; i++) {
        if (f->lines[i][0] != 'F') continue;
        CHECK(fqF(f, i, 5) == fqF(f, i, 3) && fqF(f, i, 5) > 0, "freq: ncs==n line %d", i);
        CHECK(fqF(f, i, 6) == -7 && fqF(f, i, 7) == -7 && fqF(f, i, 8) == -7 && fqF(f, i, 9) == -7, "freq: raw -7 line %d", i);
        CHECK(fqF(f, i, 10) == -11108, "freq: hz %lld", fqF(f, i, 10));
        CHECK((fqF(f, i, 15) & 16) == 0, "freq: nocarrier flag set with carrier");
        CHECK(fqF(f, i, 14) == 13, "freq: marc %lld", fqF(f, i, 14));
    }
    CHECK(f->feReads > 0 && f->pktReads > 0, "freq: status registers read");
    CHECK(rxdiagFreqEstHz(13) == 20629 && rxdiagFreqEstHz(-128) == -203125 && rxdiagFreqEstHz(0) == 0, "freq: hz conversion");
    fakeFree(&R.f);
}

static void testFreqNoCarrier(void)
{
    run_t R; fqSetup(&R);   // fqOn == fqOff == 0: never a carrier; FREQEST would read the stale 99 if it were used
    runGo(&R, &board, "freq 2402000 10 812 251 64 40");
    fake_t *f = &R.f;
    fqInvariants(&R, "freq-nocarrier");
    CHECK(R.res == RXDIAG_DONE, "nocarrier res %d", R.res);
    int nF = countLines(f, "F,");
    CHECK(nF >= 3, "nocarrier: %d F lines", nF);
    for (int i = 0; i < f->nlines; i++) {
        if (f->lines[i][0] != 'F') continue;
        CHECK(fqF(f, i, 3) > 0 && fqF(f, i, 5) == 0, "nocarrier: ncs 0 line %d", i);
        CHECK(fqF(f, i, 6) == 0 && fqF(f, i, 7) == 0 && fqF(f, i, 8) == 0 && fqF(f, i, 9) == 0 && fqF(f, i, 10) == 0, "nocarrier: zero estimate");
        CHECK((fqF(f, i, 15) & 16) != 0, "nocarrier: flag bit4");
    }
    fakeFree(&R.f);
}

static void testFreqPartial(void)
{
    run_t R; fqSetup(&R);
    R.f.fqOn = 25000; R.f.fqOff = ~(uint64_t)0; R.f.feVal = 13;
    runGo(&R, &board, "freq 2402000 10 812 251 64 60");
    fake_t *f = &R.f;
    fqInvariants(&R, "freq-partial");
    int none = 0, some = 0;
    for (int i = 0; i < f->nlines; i++) {
        if (f->lines[i][0] != 'F') continue;
        if (fqF(f, i, 5) == 0) { none++; CHECK(fqF(f, i, 6) == 0, "partial: stale leak"); }
        else { some++; CHECK(fqF(f, i, 9) == 13 || fqF(f, i, 5) < fqF(f, i, 3), "partial: value"); CHECK(fqF(f, i, 7) == 13 && fqF(f, i, 8) == 13, "partial: min/max"); }
    }
    CHECK(none >= 1 && some >= 1, "partial: none=%d some=%d", none, some);
    fakeFree(&R.f);
}

static void actFqDisagree(fake_t *f) { f->feDisagree = true; }
static void testFreqFaults(void)
{
    // FREQEST never reads stably: no accepted sample, ENOSAMP twice, radio exit
    run_t R; fqSetup(&R);
    R.f.fqOn = 0; R.f.fqOff = ~(uint64_t)0;
    R.f.feDisagree = true;
    runGo(&R, &board, "freq 2402000 10 812 251 64 100");
    fqInvariants(&R, "freq-disagree");
    CHECK(R.res == RXDIAG_EXIT_RADIO && countLines(&R.f, "E,") >= 2 && countLines(&R.f, "F,") == 0, "disagree: res %d", R.res);
    fakeFree(&R.f);
    // never reaches RX
    run_t N; fqSetup(&N); N.f.neverRx = true;
    runGo(&N, &board, "freq 2402000 10 812 251 64 100");
    fqInvariants(&N, "freq-neverrx");
    CHECK(N.res == RXDIAG_EXIT_RADIO && findLine(&N.f, "E,", 0) >= 0 && strstr(N.f.lines[findLine(&N.f, "E,", 0)], "ECAL"), "neverrx res %d", N.res);
    fakeFree(&N.f);
    // chip missing
    run_t C; fqSetup(&C); C.f.resetBad = true;
    runGo(&C, &board, "freq 2402000");
    fqInvariants(&C, "freq-nochip");
    CHECK(C.res == RXDIAG_EXIT_RADIO && findLine(&C.f, "E,", 0) >= 0 && !C.f.lnaEverOn, "nochip res %d", C.res);
    fakeFree(&C.f);
    (void)actFqDisagree;
}

static void testFreqStop(void)
{
    // host byte stops a long run promptly; USB loss and a USB stall also stop it
    run_t R; fqSetup(&R);
    R.f.fqOn = 0; R.f.fqOff = ~(uint64_t)0; R.f.feVal = 5;
    setHook(&R, "H", 1, actStop);
    runGo(&R, &board, "freq 2402000 10 812 251 64 60000");
    fqInvariants(&R, "freq-stop");
    CHECK(R.res == RXDIAG_EXIT_HOST, "stop res %d", R.res);
    CHECK(R.f.now < 200000, "stop latency now=%llu", (unsigned long long)R.f.now);
    fakeFree(&R.f);
    run_t U; fqSetup(&U);
    setHook(&U, "F", 1, actUsbDown);
    runGo(&U, &board, "freq 2402000 10 812 251 64 60000");
    fqInvariants(&U, "freq-usb");
    CHECK(U.res == RXDIAG_EXIT_USB, "usb res %d", U.res);
    fakeFree(&U.f);
    run_t S; fqSetup(&S);
    setHook(&S, "H", 1, actFailForever);
    runGo(&S, &board, "freq 2402000 10 812 251 64 60000");
    fqInvariants(&S, "freq-stall");
    CHECK(S.res == RXDIAG_EXIT_USBSTALL, "stall res %d", S.res);
    fakeFree(&S.f);
}

static void testFreqArgs(void)
{
    const char *bad[] = { "freq", "freq x", "freq 2402000 0", "freq 2402000 10 811", "freq 2402000 10 812 256",
                          "freq 2402000 10 812 251 64 0", "freq 2402000 10 812 251 64 60001", "freq 2402000 10 812 251 64 5000 1",
                          "freq 2402000 1001", "freq 1 10" };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        run_t R; fqSetup(&R);
        runGo(&R, &board, bad[i]);
        CHECK((R.res == RXDIAG_ERR_ARG) && R.f.frames == 0, "freq bad args '%s': res %d frames %llu", bad[i], R.res, (unsigned long long)R.f.frames);
        fakeFree(&R.f);
    }
    CHECK(rxdiagDurationValid(1) && rxdiagDurationValid(60000) && !rxdiagDurationValid(0) && !rxdiagDurationValid(60001), "duration bounds");
    rxdiagBoard_t b2 = board;
    b2.motorProto = "DSHOT600";
    run_t M; fqSetup(&M);
    runGo(&M, &b2, "freq 2402000");
    CHECK(M.res == RXDIAG_ERR_REFUSED && M.f.frames == 0, "freq motor gate");
    fakeFree(&M.f);
    // max duration parses and runs boundedly (virtual time): stop immediately via host byte
    run_t D; fqSetup(&D);
    setHook(&D, "H", 1, actStopNow);
    runGo(&D, &board, "freq 2402000 1000 812 251 64 60000");
    CHECK(D.res == RXDIAG_EXIT_HOST, "max duration accepted: %d", D.res);
    fqInvariants(&D, "freq-maxdur");
    fakeFree(&D.f);
}

int main(int argc, char **argv)
{
    const char *vec = argc > 1 ? argv[1] : "vectors-v1.txt";
    testVectors(vec);
    testInfo();
    testNoChip();
    testArgs();
    testMotor();
    testStreamTrace();
    testHostStopLatency();
    testEcal();
    testEstate();
    testEnosamp();
    testUsb();
    testTxFailures();
    testWindows();
    testClockWrap();
    testNegative();
    testEventsBasic();
    testEventsGdo();
    testEventsArgs();
    testEventsDrops();
    testFreqCarrier();
    testFreqNoCarrier();
    testFreqPartial();
    testFreqFaults();
    testFreqStop();
    testFreqArgs();
    printf("%d checks, %d failures\n", checks, fails);
    return fails ? 1 : 0;
}
