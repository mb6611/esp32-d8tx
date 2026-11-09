/* Decodes every capture listed in test/expected.txt and compares with the Python reference. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "d8demod.h"

static void unpack4(const uint8_t *in, size_t n, int8_t *out) { /* mirrors python/d8tx/link.py unpack4 */
    for (size_t i = 0; i < n; i++) {
        out[2 * i] = (int8_t)(((in[i] & 0xF) ^ 8) - 8);
        out[2 * i + 1] = (int8_t)(((in[i] >> 4) ^ 8) - 8);
    }
}

int main(int argc, char **argv) {
    const char *root = argc > 1 ? argv[1] : "protocol/captures";
    char path[512];
    snprintf(path, sizeof path, "%s/../../demod/test/expected.txt", root);
    FILE *ef = fopen(argc > 2 ? argv[2] : path, "r");
    if (!ef) { perror("expected.txt"); return 2; }
    char line[512];
    int fails = 0, rows = 0;
    printf("%-22s %-5s %-12s %-12s %s\n", "file", "match", "py_cfo", "c_cfo", "shift");
    while (fgets(line, sizeof line, ef)) {
        char file[200], hex[64];
        int bits, found, shift;
        double fs, cfo, pycfo;
        if (sscanf(line, "%199s %d %lf %d %63s %lf %lf %d", file, &bits, &fs, &found, hex, &cfo, &pycfo, &shift) != 8) continue;
        snprintf(path, sizeof path, "%s/%s", root, file);
        FILE *f = fopen(path, "rb");
        if (!f) { perror(path); return 2; }
        uint8_t *buf = malloc(1 << 20);
        size_t nb = fread(buf, 1, 1 << 20, f);
        fclose(f);
        size_t n = bits == 4 ? nb : nb / 2;
        int8_t *iq = malloc(2 * n);
        if (bits == 4) unpack4(buf, nb, iq); else memcpy(iq, buf, nb);
        d8_work *w = aligned_alloc(8, (d8_work_size(n) + 7) & ~(size_t)7);
        d8_result r;
        memset(&r, 0, sizeof r);
        int rc = d8_decode(iq, n, (float)fs, NULL, w, &r);
        int ok = rc == found;
        char got[64] = "-";
        if (rc == 1) {
            for (int i = 0; i < D8_PKT_BYTES; i++) sprintf(got + 2 * i, "%02x", r.pkt[i]);
            ok = ok && !strcmp(got, hex) && r.crc_ok && fabs(r.cfo_hz - cfo) < 500.0;
        }
        printf("%-22s %-5s %-12.1f %-12.1f %.0f\n", file, ok ? "ok" : "FAIL", found ? cfo : 0.0, rc == 1 ? r.cfo_hz : 0.0, rc == 1 ? r.shift_hz : 0.0);
        if (!ok) { fails++; printf("  expected %s found=%d, got %s rc=%d\n", hex, found, got, rc); }
        rows++;
        free(buf); free(iq); free(w);
    }
    fclose(ef);
    printf("%d captures, %d failures\n", rows, fails);
    return rows > 0 && !fails ? 0 : 1;
}
