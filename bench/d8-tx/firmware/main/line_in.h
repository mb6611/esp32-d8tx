/* Idle-safe line input. The poll never blocks past one read timeout and calls feed() every pass,
 * so a silent UART cannot starve the RTC WDT. (IDF uart_vfs fgetc() blocks with portMAX_DELAY and
 * never returns EOF in the default blocking mode, which is why the old loop was reset every ~3.3 s.) */
#ifndef LINE_IN_H
#define LINE_IN_H
#include <stddef.h>

typedef struct { char buf[96]; size_t len; } line_in_t;
typedef enum { LINE_NONE, LINE_READY, LINE_LONG } line_res_t;

/* rd(ctx): next byte 0..255, or -1 on timeout/no data (must return within bounded time). */
static inline line_res_t line_poll(line_in_t *l, int (*rd)(void *), void (*feed)(void *), void *ctx) {
    feed(ctx);
    int ch = rd(ctx);
    if (ch < 0) return LINE_NONE;
    if (ch != '\n' && ch != '\r') {
        if (l->len < sizeof l->buf - 1) l->buf[l->len++] = (char)ch;
        else l->len = sizeof l->buf; /* overlong: mark, reject at EOL */
        return LINE_NONE;
    }
    if (!l->len) return LINE_NONE;
    int over = l->len >= sizeof l->buf;
    l->buf[over ? 0 : l->len] = 0;
    l->len = 0;
    return over ? LINE_LONG : LINE_READY;
}
#endif
