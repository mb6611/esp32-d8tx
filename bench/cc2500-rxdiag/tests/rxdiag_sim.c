#define _POSIX_C_SOURCE 200809L
// rxdiag_sim: host executable running rxdiagRun against the fake CC2500, behind a Betaflight-CLI-like
// prompt on a file descriptor. Used by the host end-to-end tests (U3.D).
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>
#include "fake.h"
#include "rxdiag_core.h"

typedef struct {
    int fd;
    fake_t f;
    char fault[24];
    uint64_t faultAtUs, streamBase;
    bool inStream, usbDown, txStall, closeNow;
} sim_t;

static sim_t S;

static const char *HELP =
    "usage: rxdiag_sim [options]\n"
    "  Fake Betaflight CLI + fake CC2500 on a file descriptor. Send '#' to enter the CLI, then\n"
    "  'rxdiag info' or 'rxdiag stream <freq_khz> [window_ms] [bw]' (LF terminated). Any byte stops a stream.\n"
    "options:\n"
    "  --fd N             file descriptor for both directions (default 0)\n"
    "  --rssi-off V       RSSI raw value when the source is OFF (default -100)\n"
    "  --rssi-on V        RSSI raw value when the source is ON (default -60)\n"
    "  --on-at-ms T       source switches ON T ms after stream start (default: never ON)\n"
    "  --off-at-ms T      source switches OFF T ms after stream start (default: stays ON)\n"
    "  --fault NAME       fault scenario (see below); --fault-at-ms T sets when, from stream start (default 100)\n"
    "  --disagree-ms D    with --fault enosamp: duration of RSSI read disagreement (default: forever)\n"
    "  --motor-proto NAME motor protocol name printed in I (default DISABLED)\n"
    "  --motor-active     report motor_dev=active\n"
    "  --spi-hz N         spi_hz printed in I/H (default 5250000)\n"
    "  --selftest         run a built-in socketpair self test and exit\n"
    "  --help\n"
    "fault scenarios:\n"
    "  none        no fault\n"
    "  nochip      FREQ1 does not read 0xC4 after reset (ENOCHIP / reset_ok=0)\n"
    "  rbfail      FREQ0 readback fails (rb_ok=0)\n"
    "  ecal        radio never reaches RX (ECAL then X,radio)\n"
    "  estate      at fault time MARCSTATE leaves RX and does not recover (ESTATE then X,radio)\n"
    "  estate-rec  at fault time MARCSTATE leaves RX once; recovers (ESTATE, flags 9)\n"
    "  enosamp     RSSI reads disagree from fault time for --disagree-ms (forever = two ENOSAMP, X,radio)\n"
    "  usbstall    records can no longer be queued from fault time (X,usbstall best effort)\n"
    "  usbdown     usbConnected() turns false at fault time (X,usb best effort)\n"
    "  close       the fd is closed and the process exits abruptly at fault time\n"
    "  emotor      motor_proto=DSHOT600 and motor_dev=active (stream refused with EMOTOR)\n";

static uint32_t sRxWaiting(void *c)
{
    sim_t *s = c;
    if (s->closeNow || (!strcmp(s->fault, "close") && s->inStream && fakeNow(&s->f) >= s->faultAtUs)) {
        close(s->fd);
        _exit(0);
    }
    struct pollfd p = { s->fd, POLLIN, 0 };
    return poll(&p, 1, 0) > 0 && (p.revents & (POLLIN | POLLHUP | POLLERR)) ? 1 : 0;
}

static void sRxDrain(void *c)
{
    sim_t *s = c;
    char b[256];
    for (;;) {
        struct pollfd p = { s->fd, POLLIN, 0 };
        if (poll(&p, 1, 0) <= 0 || !(p.revents & POLLIN)) {
            break;
        }
        ssize_t n = read(s->fd, b, sizeof b);
        if (n <= 0) {
            break;
        }
    }
}

static bool sUsb(void *c)
{
    sim_t *s = c;
    if (!strcmp(s->fault, "usbdown") && s->inStream && fakeNow(&s->f) >= s->faultAtUs) {
        return false;
    }
    return true;
}

static bool sTx(void *c, const char *buf, uint32_t len)
{
    sim_t *s = c;
    if (!strcmp(s->fault, "usbstall") && s->inStream && fakeNow(&s->f) >= s->faultAtUs) {
        return false;
    }
    ssize_t n = write(s->fd, buf, len);
    if (n < 0) {
        return false;
    }
    uint32_t done = (uint32_t)n;
    while (done < len) {
        struct pollfd p = { s->fd, POLLOUT, 0 };
        if (poll(&p, 1, 50) <= 0) {
            return true; // cannot unsend a partial write
        }
        n = write(s->fd, buf + done, len - done);
        if (n < 0 && errno != EAGAIN) {
            return true;
        }
        if (n > 0) {
            done += (uint32_t)n;
        }
    }
    return true;
}

static void say(sim_t *s, const char *t)
{
    sTx(s, t, (uint32_t)strlen(t));
}

static long optNum(const char *v) { return strtol(v, NULL, 10); }

typedef struct {
    int rssiOff, rssiOn;
    long onAtMs, offAtMs, faultAtMs, disagreeMs;
    const char *motorProto;
    bool motorActive;
    uint32_t spiHz;
} cfg_t;

static void dispatch(sim_t *s, const cfg_t *cfg, char *line, rxdiagHal_t *hal)
{
    while (*line == ' ') line++;
    size_t n = strlen(line);
    while (n && line[n - 1] == ' ') line[--n] = 0;
    if (n == 0 || line[0] == '#') {
        return;
    }
    if (!strcmp(line, "rxdiag") || !strncmp(line, "rxdiag ", 7)) {
        const char *args = line[6] ? line + 7 : "";
        fake_t *f = &s->f;
        const uint64_t base = fakeNow(f);
        s->streamBase = base;
        s->faultAtUs = base + (uint64_t)cfg->faultAtMs * 1000u;
        // per-command chip state
        f->estateAt = 0; f->estateDone = false; f->estateStuck = false; f->neverRx = false;
        f->disagreeFrom = f->disagreeTo = 0;
        f->resetBad = !strcmp(s->fault, "nochip");
        f->rbBad = !strcmp(s->fault, "rbfail");
        f->neverRx = !strcmp(s->fault, "ecal");
        if (!strncmp(s->fault, "estate", 6)) {
            f->estateAt = s->faultAtUs;
            f->estateStuck = !strcmp(s->fault, "estate");
        }
        if (!strcmp(s->fault, "enosamp")) {
            f->disagreeFrom = s->faultAtUs;
            f->disagreeTo = cfg->disagreeMs > 0 ? s->faultAtUs + (uint64_t)cfg->disagreeMs * 1000u : ~(uint64_t)0;
        }
        f->rssiMode = RSSI_STEP;
        f->stepOff = (int8_t)cfg->rssiOff;
        f->stepOn = (int8_t)cfg->rssiOn;
        f->stepOnAt = cfg->onAtMs >= 0 ? base + (uint64_t)cfg->onAtMs * 1000u : ~(uint64_t)0;
        f->stepOffAt = cfg->offAtMs >= 0 ? base + (uint64_t)cfg->offAtMs * 1000u : ~(uint64_t)0;
        f->state = 0x01;
        rxdiagBoard_t b = { "SIM00000", "SIMBF00", "A15", "C14", "A8", "A13", "A14", cfg->motorProto, 1, 2, cfg->spiHz, !cfg->motorActive, 0 };
        s->inStream = true;
        rxdiagRun(hal, &b, args);
        s->inStream = false;
        return;
    }
    if (!strcmp(line, "exit")) {
        return;
    }
    say(s, "Unknown command, try 'help'\r\n");
}

// returns 0 on EOF
static int cliLoop(sim_t *s, const cfg_t *cfg, rxdiagHal_t *hal)
{
    bool cli = false;
    char line[256];
    size_t len = 0;
    for (;;) {
        char c;
        struct pollfd p = { s->fd, POLLIN, 0 };
        if (poll(&p, 1, -1) < 0) {
            if (errno == EINTR) continue;
            return 0;
        }
        ssize_t n = read(s->fd, &c, 1);
        if (n <= 0) {
            if (n < 0 && (errno == EAGAIN || errno == EINTR)) continue;
            return 0;
        }
        if (!cli) {
            if (c == '#') {
                cli = true;
                len = 0;
                say(s, "\r\nEntering CLI Mode, type 'exit' to return, or 'help'\r\n\r\n# ");
            }
            continue;
        }
        if (c == '\n' || c == '\r') {
            say(s, "\r\n");
            line[len] = 0;
            if (!strcmp(line, "exit")) {
                cli = false;
                say(s, "\r\nLeaving CLI mode\r\n");
            } else {
                dispatch(s, cfg, line, hal);
                say(s, "\r\n# ");
            }
            len = 0;
        } else if (c == 0x7f || c == 8) {
            if (len) len--;
        } else if (len + 1 < sizeof line) {
            line[len++] = c;
            sTx(s, &c, 1);
        }
    }
}

static int simMain(int fd, const cfg_t *cfg, const char *fault)
{
    signal(SIGPIPE, SIG_IGN);
    memset(&S, 0, sizeof S);
    S.fd = fd;
    fakeInit(&S.f);
    S.f.real = true;
    S.f.simRxWaiting = sRxWaiting;
    S.f.simRxDrain = sRxDrain;
    S.f.simUsb = sUsb;
    S.f.simTx = sTx;
    S.f.simCtx = &S;
    snprintf(S.fault, sizeof S.fault, "%s", fault);
    int fl = fcntl(fd, F_GETFL);
    fcntl(fd, F_SETFL, fl | O_NONBLOCK);
    rxdiagHal_t hal;
    fakeHal(&S.f, &hal);
    cliLoop(&S, cfg, &hal);
    return 0;
}

static ssize_t readSome(int fd, char *buf, size_t cap, int ms)
{
    struct pollfd p = { fd, POLLIN, 0 };
    if (poll(&p, 1, ms) <= 0) return -1;
    return read(fd, buf, cap);
}

static int selftest(cfg_t *cfg)
{
    int sv[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv)) return 1;
    pid_t pid = fork();
    if (pid == 0) {
        close(sv[0]);
        _exit(simMain(sv[1], cfg, "none"));
    }
    close(sv[1]);
    int fd = sv[0];
    static char all[1 << 16];
    size_t len = 0;
    int rc = 1;
    #define PUMP(ms) do { ssize_t k; while ((k = readSome(fd, all + len, sizeof all - len - 1, ms)) > 0) { len += (size_t)k; } all[len] = 0; } while (0)
    write(fd, "#", 1);
    PUMP(300);
    if (!strstr(all, "# ")) { fprintf(stderr, "selftest: no prompt\n"); goto out; }
    write(fd, "rxdiag info\n", 12);
    PUMP(300);
    if (!strstr(all, "\nI,proto=1,fw=SIM00000") || !strstr(all, "reset_ok=1,rb_ok=1")) { fprintf(stderr, "selftest: bad I\n%s\n", all); goto out; }
    len = 0; all[0] = 0;
    write(fd, "rxdiag stream 2440000 10\n", 25);
    PUMP(150);
    if (!strstr(all, "\nH,proto=1") || !strstr(all, "\nS,0,")) { fprintf(stderr, "selftest: no H/S\n%s\n", all); goto out; }
    write(fd, "\n", 1);
    len = 0; all[0] = 0;
    PUMP(300);
    if (!strstr(all, ",host\r\n") || !strstr(all, "# ")) { fprintf(stderr, "selftest: no X host / prompt\n"); goto out; }
    printf("rxdiag_sim selftest OK\n");
    rc = 0;
out:
    close(fd);
    kill(pid, SIGTERM);
    waitpid(pid, NULL, 0);
    return rc;
}

int main(int argc, char **argv)
{
    cfg_t cfg = { -100, -60, -1, -1, 100, 0, "DISABLED", false, 5250000 };
    int fd = 0;
    const char *fault = "none";
    bool self = false;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : "";
        if (!strcmp(a, "--help") || !strcmp(a, "-h")) { fputs(HELP, stdout); return 0; }
        else if (!strcmp(a, "--fd")) { fd = (int)optNum(v); i++; }
        else if (!strcmp(a, "--rssi-off")) { cfg.rssiOff = (int)optNum(v); i++; }
        else if (!strcmp(a, "--rssi-on")) { cfg.rssiOn = (int)optNum(v); i++; }
        else if (!strcmp(a, "--on-at-ms")) { cfg.onAtMs = optNum(v); i++; }
        else if (!strcmp(a, "--off-at-ms")) { cfg.offAtMs = optNum(v); i++; }
        else if (!strcmp(a, "--fault")) { fault = v; i++; }
        else if (!strcmp(a, "--fault-at-ms")) { cfg.faultAtMs = optNum(v); i++; }
        else if (!strcmp(a, "--disagree-ms")) { cfg.disagreeMs = optNum(v); i++; }
        else if (!strcmp(a, "--motor-proto")) { cfg.motorProto = v; i++; }
        else if (!strcmp(a, "--motor-active")) { cfg.motorActive = true; }
        else if (!strcmp(a, "--spi-hz")) { cfg.spiHz = (uint32_t)optNum(v); i++; }
        else if (!strcmp(a, "--selftest")) { self = true; }
        else { fprintf(stderr, "unknown option %s (try --help)\n", a); return 2; }
    }
    static const char *known[] = { "none", "nochip", "rbfail", "ecal", "estate", "estate-rec", "enosamp", "usbstall", "usbdown", "close", "emotor" };
    bool ok = false;
    for (size_t i = 0; i < sizeof known / sizeof known[0]; i++) ok = ok || !strcmp(fault, known[i]);
    if (!ok) { fprintf(stderr, "unknown fault %s (try --help)\n", fault); return 2; }
    if (!strcmp(fault, "emotor")) { cfg.motorProto = "DSHOT600"; cfg.motorActive = true; }
    if (self) return selftest(&cfg);
    return simMain(fd, &cfg, fault);
}
