/* Freestanding runtime for the WASM build: memcpy/memset and a bump allocator over linear memory. */
#include <stddef.h>
#include <stdint.h>

void *memcpy(void *d, const void *s, size_t n) {
    uint8_t *dd = d;
    const uint8_t *ss = s;
    while (n--) *dd++ = *ss++;
    return d;
}

void *memmove(void *d, const void *s, size_t n) {
    uint8_t *dd = d;
    const uint8_t *ss = s;
    if (dd < ss) while (n--) *dd++ = *ss++;
    else { dd += n; ss += n; while (n--) *--dd = *--ss; }
    return d;
}

void *memset(void *d, int c, size_t n) {
    uint8_t *dd = d;
    while (n--) *dd++ = (uint8_t)c;
    return d;
}

extern uint8_t __heap_base;
static uintptr_t heap_top;

/* 8-byte aligned bump allocation; grows memory as needed. Returns 0 on failure. */
__attribute__((export_name("d8_alloc"))) void *d8_alloc(size_t n) {
    if (!heap_top) heap_top = ((uintptr_t)&__heap_base + 7) & ~(uintptr_t)7;
    uintptr_t p = heap_top, end = p + ((n + 7) & ~(size_t)7);
    size_t have = __builtin_wasm_memory_size(0) * 65536u;
    if (end > have) {
        size_t pages = (end - have + 65535u) / 65536u;
        if (__builtin_wasm_memory_grow(0, pages) == (size_t)-1) return 0;
    }
    heap_top = end;
    return (void *)p;
}

/* Frees everything allocated by d8_alloc. */
__attribute__((export_name("d8_reset"))) void d8_reset(void) { heap_top = 0; }
