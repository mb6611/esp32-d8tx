/* Checks the golden command vectors (generated from the Python package, protocol/vectors/commands.json) against the
 * firmware parser: every S line the host formats must parse to the same stick values, and every host/firmware
 * command line must be accepted or rejected with the expected protocol v1 error code. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../main/cmd_parse.h"
#include "../../protocol/vectors/commands.h"

int main(void) {
    unsigned i, j, n = 0;
    for (i = 0; i < sizeof VEC_S / sizeof VEC_S[0]; i++) {
        char b[128];
        strcpy(b, VEC_S[i].line);
        cmd_t c = cmd_parse(b);
        if (c.kind != CMD_S) { printf("S vector %u (%s) -> kind %d\n", i, VEC_S[i].line, c.kind); return 1; }
        for (j = 0; j < 8; j++)
            if (c.sticks[j] != VEC_S[i].ch[j]) { printf("S vector %u ch%u: %d != %d\n", i, j, c.sticks[j], VEC_S[i].ch[j]); return 1; }
        n++;
    }
    for (i = 0; i < sizeof VEC_LINES / sizeof VEC_LINES[0]; i++) {
        char b[128];
        strcpy(b, VEC_LINES[i].line);
        cmd_t c = cmd_parse(b);
        int ok = c.kind != CMD_ERR && c.kind != CMD_NONE;
        if (ok != VEC_LINES[i].ok) { printf("line '%s': ok=%d want %d\n", VEC_LINES[i].line, ok, VEC_LINES[i].ok); return 1; }
        if (!ok && strcmp(err_code(c.err), VEC_LINES[i].err)) {
            printf("line '%s': err %s want %s\n", VEC_LINES[i].line, err_code(c.err), VEC_LINES[i].err); return 1;
        }
        n++;
    }
    printf("test_vectors: %u vectors ok\n", n);
    return 0;
}
