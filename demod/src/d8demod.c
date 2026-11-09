#include "d8demod.h"

float atan2f(float, float);
float sinf(float);
float cosf(float);
float floorf(float);

#define PI 3.14159265358979323846
#define NTAPS 63
#define PACKET_BYTES 20
#define PRE_SYNC_BITS 48
#define AIR_BITS 208
#define MAXRES 8
#define REPLY_LEN 0x11
#define XTAL 26e6

static const double BAUD = XTAL * (256 + 0x39) * 1024.0 / 268435456.0;
static const double DEVIATION = XTAL / 131072.0 * (8 + (0x42 & 7)) * 16.0; /* 2^((0x42>>4)&7) */
static const double CUTS[4] = {40e3, 50e3, 35e3, 45e3};
static const uint8_t PRE_SYNC[6] = {0xAA, 0xAA, 0xAA, 0xAA, 0xD3, 0x91};

struct d8_work {
    double *x0r, *x0i, *xr, *xi, *yr, *yi, *d, *cf, *sym, *pos, *cs, *taps;
    uint8_t *bits;
    size_t n;
};

typedef struct {
    uint8_t raw[PACKET_BYTES];
    int crc_ok;
    double t, cfo;
} res_t;

static size_t a8(size_t v) { return (v + 7) & ~(size_t)7; }

size_t d8_work_size(size_t n) {
    return a8(sizeof(struct d8_work)) + 11 * 8 * (n + 2) + 8 * 64 + a8(n + 8) + 64;
}

void d8_opts_default(d8_opts *o) {
    o->txid[0] = 66;
    o->txid[1] = 178;
    o->has_hint = 0;
    o->hint_hz = 0;
}

static unsigned crc16(const uint8_t *p, int n) {
    unsigned crc = 0xFFFF;
    for (int i = 0; i < n; i++) {
        crc ^= (unsigned)p[i] << 8;
        for (int k = 0; k < 8; k++) crc = (crc & 0x8000) ? (((crc << 1) ^ 0x8005) & 0xFFFF) : ((crc << 1) & 0xFFFF);
    }
    return crc;
}

static int crc_ok_raw(const uint8_t *raw) { return crc16(raw, 18) == (unsigned)(raw[18] << 8 | raw[19]); }

static double rint_even(double v) { /* v >= 0 expected, small */
    double f = (double)floorf((float)v);
    double r = v - f;
    if (r > 0.5) return f + 1;
    if (r < 0.5) return f;
    return (((long long)f) & 1) ? f + 1 : f;
}

static void make_taps(double *h, double fs, double cutoff) {
    double sum = 0;
    for (int n = 0; n < NTAPS; n++) {
        double m = n - (NTAPS - 1) / 2.0;
        double u = 2 * cutoff / fs * m;
        double s = (u == 0) ? 1.0 : (double)sinf((float)(PI * u)) / (PI * u);
        double hw = 0.54 - 0.46 * (double)cosf((float)(2 * PI * n / (NTAPS - 1)));
        h[n] = s * hw;
        sum += h[n];
    }
    for (int n = 0; n < NTAPS; n++) h[n] /= sum;
}

/* numpy convolve(x, h, 'same'), kernel odd length */
static void conv_same(const double *xr, const double *xi, double *yr, double *yi, size_t n, const double *h) {
    for (long i = 0; i < (long)n; i++) {
        double ar = 0, ai = 0;
        for (int k = 0; k < NTAPS; k++) {
            long j = i + (NTAPS - 1) / 2 - k;
            if (j < 0 || j >= (long)n) continue;
            ar += h[k] * xr[j];
            ai += h[k] * xi[j];
        }
        yr[i] = ar;
        yi[i] = ai;
    }
}

static void fm_demod(const double *yr, const double *yi, double *d, size_t n, double fs) {
    for (size_t i = 1; i < n; i++) {
        double re = yr[i] * yr[i - 1] + yi[i] * yi[i - 1];
        double im = yi[i] * yr[i - 1] - yr[i] * yi[i - 1];
        d[i] = (double)atan2f((float)im, (float)re) * fs / (2 * PI);
    }
    d[0] = n > 1 ? d[1] : 0;
}

static void boxcar_same(const double *d, double *out, size_t n, size_t w, double *cs) {
    cs[0] = 0;
    for (size_t i = 0; i < n; i++) cs[i + 1] = cs[i] + d[i];
    for (long i = 0; i < (long)n; i++) {
        long hi = i + (long)((w - 1) / 2), lo = hi - (long)(w - 1);
        if (lo < 0) lo = 0;
        if (hi > (long)n - 1) hi = (long)n - 1;
        out[i] = (hi >= lo ? cs[hi + 1] - cs[lo] : 0) / (double)w;
    }
}

static size_t mm_clock(const double *dl, size_t n, double sps, double *out, double *pos) {
    const double mu = 0.5, gain_mu = 0.175, omega_limit = 0.005;
    double gain_omega = 0.25 * gain_mu * gain_mu;
    double omega = sps, om_lo = sps * (1 - omega_limit), om_hi = sps * (1 + omega_limit);
    double i = mu, last_s = 0, last_dec = 0;
    size_t cnt = 0;
    while (i < (double)n - 2 && cnt < n) {
        long k = (long)i;
        double f = i - (double)k;
        double s = dl[k] * (1 - f) + dl[k + 1] * f;
        double dec = s >= 0 ? 1.0 : -1.0;
        double err = last_dec * s - dec * last_s;
        if (err > 1.0) err = 1.0;
        else if (err < -1.0) err = -1.0;
        last_s = s;
        last_dec = dec;
        out[cnt] = s;
        pos[cnt] = i;
        cnt++;
        omega += gain_omega * err;
        if (omega < om_lo) omega = om_lo;
        else if (omega > om_hi) omega = om_hi;
        i += omega + gain_mu * err;
    }
    return cnt;
}

static int bit_of(const uint8_t *b, int i) { return (b[i >> 3] >> (7 - (i & 7))) & 1; }

static double lerp_u(const double *f, size_t len, double p) {
    if (p < 0) p = 0;
    if (p > (double)len - 1) p = (double)len - 1;
    long k = (long)p;
    if (k > (long)len - 2) k = (long)len - 2;
    return f[k] + (p - (double)k) * (f[k + 1] - f[k]);
}

/* _std_refine: returns best t0, carrier, fills air bits (AIR_BITS) */
static void refine(const double *d, size_t n, double sps, double p0, double *cs, double *t0o, double *co, uint8_t *air) {
    const double dump = 0.6;
    cs[0] = 0;
    for (size_t i = 0; i < n; i++) cs[i + 1] = cs[i] + d[i];
    size_t L = n + 1;
    double lo_f = 0.5 - 0.5 * dump, hi_f = 0.5 + 0.5 * dump;
    double best_m = 0, best_t = 0, best_c = 0;
    int have = 0;
    for (int s = 0; s < 33; s++) {
        double t0 = p0 + (-1.0 + 2.0 * s / 32.0) * sps;
        double csum = 0, v[PRE_SYNC_BITS];
        for (int k = 0; k < PRE_SYNC_BITS; k++) {
            double a = lerp_u(cs, L, t0 + (k + lo_f) * sps + 0.5);
            double b = lerp_u(cs, L, t0 + (k + hi_f) * sps + 0.5);
            v[k] = (b - a) / (dump * sps);
            if (k < 32) csum += v[k];
        }
        double c = csum / 32.0, m = 0;
        for (int k = 0; k < PRE_SYNC_BITS; k++) m += (v[k] - c) * (bit_of(PRE_SYNC, k) ? 1.0 : -1.0);
        m /= PRE_SYNC_BITS;
        if (!have || m > best_m) {
            have = 1;
            best_m = m;
            best_t = t0;
            best_c = c;
        }
    }
    for (int k = 0; k < AIR_BITS; k++) {
        double a = lerp_u(cs, L, best_t + (k + lo_f) * sps + 0.5);
        double b = lerp_u(cs, L, best_t + (k + hi_f) * sps + 0.5);
        air[k] = ((b - a) / (dump * sps) - best_c) > 0 ? 1 : 0;
    }
    *t0o = best_t;
    *co = best_c;
}

static void bits_to_bytes(const uint8_t *bits, int nbytes, uint8_t *out) {
    for (int i = 0; i < nbytes; i++) {
        uint8_t v = 0;
        for (int k = 0; k < 8; k++) v = (uint8_t)(v << 1 | bits[8 * i + k]);
        out[i] = v;
    }
}

static int decode_once(struct d8_work *W, double fs, size_t w_len, res_t *out, int maxout) {
    size_t n = W->n;
    double sps = fs / BAUD;
    conv_same(W->xr, W->xi, W->yr, W->yi, n, W->taps);
    fm_demod(W->yr, W->yi, W->d, n, fs);
    boxcar_same(W->d, W->cf, n, w_len, W->cs);
    /* normalised signal into yr (free after demod) */
    for (size_t i = 0; i < n; i++) W->yr[i] = (W->d[i] - W->cf[i]) / DEVIATION;
    size_t ns = mm_clock(W->yr, n, sps, W->sym, W->pos);
    for (size_t i = 0; i < ns; i++) W->bits[i] = W->sym[i] > 0 ? 1 : 0;
    /* sync search: sync word D3 91 */
    static const uint8_t SY[16] = {1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 1};
    int starts[64], errs[64], nh = 0;
    if (ns >= 16) {
        for (size_t i = 0; i + 16 <= ns; i++) {
            int e = 0;
            for (int k = 0; k < 16; k++) e += W->bits[i + k] != SY[k];
            if (e > 2) continue;
            if (nh && (long)i - (starts[nh - 1] - 16) + 16 < 8 * PACKET_BYTES) {
                if (e < errs[nh - 1]) {
                    starts[nh - 1] = (int)i + 16;
                    errs[nh - 1] = e;
                }
                continue;
            }
            if (nh < 64) {
                starts[nh] = (int)i + 16;
                errs[nh] = e;
                nh++;
            }
        }
    }
    int nout = 0;
    for (int h = 0; h < nh && nout < maxout; h++) {
        int start = starts[h];
        if ((size_t)start + 8 * PACKET_BYTES > ns || start < PRE_SYNC_BITS) continue;
        int i0 = start - PRE_SYNC_BITS;
        int match = 0;
        for (int k = 0; k < 32; k++) match += W->bits[i0 + k] == (k & 1 ? 0 : 1); /* 0xAA = 1010... */
        if ((double)match / 32.0 < 0.75) continue;
        double t0, c;
        uint8_t air[AIR_BITS];
        refine(W->d, n, sps, W->pos[i0], W->cs, &t0, &c, air);
        res_t *r = &out[nout];
        bits_to_bytes(air + PRE_SYNC_BITS, PACKET_BYTES, r->raw);
        r->crc_ok = crc_ok_raw(r->raw);
        if (!r->crc_ok) {
            uint8_t alt[PACKET_BYTES];
            bits_to_bytes(W->bits + start, PACKET_BYTES, alt);
            if (crc_ok_raw(alt)) {
                for (int k = 0; k < PACKET_BYTES; k++) r->raw[k] = alt[k];
                r->crc_ok = 1;
            }
        }
        r->t = t0 / fs;
        r->cfo = c;
        nout++;
    }
    return nout;
}

static void mix(struct d8_work *W, double fs, double shift) {
    size_t n = W->n;
    for (size_t k = 0; k < n; k++) {
        if (shift == 0) {
            W->xr[k] = W->x0r[k];
            W->xi[k] = W->x0i[k];
            continue;
        }
        double turns = shift * (double)k / fs; /* exp(-2j*pi*turns) */
        turns -= (double)(long long)turns;
        float a = (float)(2 * PI * turns);
        double c = (double)cosf(a), s = -(double)sinf(a);
        W->xr[k] = W->x0r[k] * c - W->x0i[k] * s;
        W->xi[k] = W->x0r[k] * s + W->x0i[k] * c;
    }
}

/* StandardDecoder.decode(first_ok=True) for one shift. Returns number of merged results, sorted by t. */
static int decode_shift(struct d8_work *W, double fs, res_t *merged) {
    size_t n = W->n;
    double wide = 0.45 * fs < 75e3 ? 0.45 * fs : 75e3;
    double cuts[5];
    int nc = 0;
    for (int i = 0; i < 4; i++)
        if (CUTS[i] < wide) cuts[nc++] = CUTS[i];
    cuts[nc++] = wide;
    double sps = fs / BAUD;
    size_t w_len = (size_t)(32 * sps);
    if (w_len < 3) w_len = 3;
    double mc[MAXRES];
    int nm = 0;
    res_t tmp[MAXRES];
    for (int ci = 0; ci < nc; ci++) {
        make_taps(W->taps, fs, cuts[ci]);
        int nt = decode_once(W, fs, w_len, tmp, MAXRES);
        for (int j = 0; j < nt; j++) {
            int same = -1;
            for (int i = 0; i < nm; i++) {
                double dt = merged[i].t - tmp[j].t;
                if (dt < 0) dt = -dt;
                if (dt < 2e-3) {
                    same = i;
                    break;
                }
            }
            if (same < 0) {
                if (nm < MAXRES) {
                    merged[nm] = tmp[j];
                    mc[nm++] = cuts[ci];
                }
                continue;
            }
            if (tmp[j].crc_ok && (!merged[same].crc_ok || cuts[ci] > mc[same])) {
                merged[same] = tmp[j];
                mc[same] = cuts[ci];
            }
        }
        int any = 0;
        for (int i = 0; i < nm; i++) any |= merged[i].crc_ok;
        if (any) break;
    }
    int need = 0;
    for (int i = 0; i < nm; i++) need |= (mc[i] < wide && merged[i].crc_ok);
    if (need) {
        make_taps(W->taps, fs, wide);
        conv_same(W->xr, W->xi, W->yr, W->yi, n, W->taps);
        fm_demod(W->yr, W->yi, W->d, n, fs);
        size_t np_ = (size_t)(32 * sps);
        for (int i = 0; i < nm; i++) {
            if (mc[i] < wide && merged[i].crc_ok) {
                double ri = rint_even(merged[i].t * fs);
                if (ri >= 0 && (size_t)ri + np_ <= n) {
                    double s = 0;
                    for (size_t k = 0; k < np_; k++) s += W->d[(size_t)ri + k];
                    merged[i].cfo = s / (double)np_;
                }
            }
        }
    }
    for (int i = 1; i < nm; i++) { /* insertion sort by t (stable) */
        res_t r = merged[i];
        int j = i - 1;
        while (j >= 0 && merged[j].t > r.t) {
            merged[j + 1] = merged[j];
            j--;
        }
        merged[j + 1] = r;
    }
    return nm;
}

int d8_decode(const int8_t *iq, size_t n, float fsf, const d8_opts *o, d8_work *w, d8_result *out) {
    d8_opts def;
    if (!iq || !w || !out || n < NTAPS || !(fsf > 0)) return -1;
    if (!o) {
        d8_opts_default(&def);
        o = &def;
    }
    double fs = (double)fsf;
    uint8_t *base = (uint8_t *)w;
    struct d8_work *W = (struct d8_work *)base;
    double *p = (double *)(base + a8(sizeof(struct d8_work)));
    W->n = n;
    W->x0r = p; p += n + 2;
    W->x0i = p; p += n + 2;
    W->xr = p; p += n + 2;
    W->xi = p; p += n + 2;
    W->yr = p; p += n + 2;
    W->yi = p; p += n + 2;
    W->d = p; p += n + 2;
    W->cf = p; p += n + 2;
    W->sym = p; p += n + 2;
    W->pos = p; p += n + 2;
    W->cs = p; p += n + 2;
    W->taps = p; p += 64;
    W->bits = (uint8_t *)p;
    double sr = 0, si = 0;
    for (size_t i = 0; i < n; i++) {
        W->x0r[i] = iq[2 * i];
        W->x0i[i] = -(double)iq[2 * i + 1];
        sr += W->x0r[i];
        si += W->x0i[i];
    }
    sr /= (double)n;
    si /= (double)n;
    int nonzero = 0;
    for (size_t i = 0; i < n; i++) {
        W->x0r[i] -= sr;
        W->x0i[i] -= si;
        nonzero |= (W->x0r[i] != 0 || W->x0i[i] != 0);
    }
    if (!nonzero) return 0;
    double order[13];
    int no = 0;
    if (o->has_hint) order[no++] = (double)o->hint_hz;
    for (int s = -150000; s <= 150000; s += 25000)
        if (!(o->has_hint && (double)s == (double)o->hint_hz)) order[no++] = (double)s;
    for (int oi = 0; oi < no; oi++) {
        double s = order[oi];
        if ((s < 0 ? -s : s) + 40e3 > fs / 2) continue;
        mix(W, fs, s);
        res_t merged[MAXRES];
        int nm = decode_shift(W, fs, merged);
        for (int i = 0; i < nm; i++) {
            res_t *r = &merged[i];
            if (r->crc_ok && r->raw[1] == o->txid[0] && r->raw[2] == o->txid[1] && r->raw[0] == REPLY_LEN) {
                for (int k = 0; k < PACKET_BYTES; k++) out->pkt[k] = r->raw[k];
                out->crc_ok = 1;
                out->cfo_hz = (float)(r->cfo + s);
                out->shift_hz = (float)s;
                out->t_ms = (float)(r->t * 1e3);
                return 1;
            }
        }
    }
    return 0;
}
