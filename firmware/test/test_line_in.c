#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../main/line_in.h"

static const char *in; static size_t pos; static int feeds, idle_left;
static int rd(void *c) { (void)c; if (idle_left > 0) { idle_left--; return -1; } return pos < strlen(in) ? (unsigned char)in[pos++] : -1; }
static void fd(void *c) { (void)c; feeds++; }

int main(void) {
    line_in_t l = {0};
    /* idle: every poll feeds and returns promptly, no data */
    idle_left = 1000; in = "";
    for (int i = 0; i < 1000; i++) assert(line_poll(&l, rd, fd, NULL) == LINE_NONE);
    assert(feeds == 1000);
    /* line with idle gaps */
    in = "PING\r\n"; pos = 0; feeds = 0; idle_left = 3;
    line_res_t r; int n = 0;
    while ((r = line_poll(&l, rd, fd, NULL)) == LINE_NONE) n++;
    assert(r == LINE_READY && !strcmp(l.buf, "PING") && feeds == n + 1);
    assert(line_poll(&l, rd, fd, NULL) == LINE_NONE); /* \n after \r: empty, ignored */
    /* overlong rejected, then recovers */
    char big[200]; memset(big, 'A', 150); big[150] = '\n'; strcpy(big + 151, "U\n");
    in = big; pos = 0; idle_left = 0;
    assert(line_poll(&l, rd, fd, NULL) == LINE_NONE);
    int got_long = 0, got_u = 0;
    for (int i = 0; i < 400; i++) { r = line_poll(&l, rd, fd, NULL); if (r == LINE_LONG) got_long++; if (r == LINE_READY && !strcmp(l.buf, "U")) got_u++; }
    assert(got_long == 1 && got_u == 1);
    puts("line_in tests ok");
    return 0;
}
