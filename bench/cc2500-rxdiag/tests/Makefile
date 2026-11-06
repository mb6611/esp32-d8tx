# Core tests. `make test` from bench/cc2500-rxdiag/tests (or: make -C bench/cc2500-rxdiag/tests test).
CORE_DIR := ../firmware/overlay/src/main/rx
VECTORS  := vectors-v1.txt
CC       ?= cc
CFLAGS   := -std=c99 -Wall -Wextra -Werror -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=undefined -I$(CORE_DIR) -I.
# fake.c and rxdiag_sim.c use POSIX clock/poll APIs and define _POSIX_C_SOURCE themselves.

all: test_core rxdiag_sim

test_core: test_core.c fake.c fake.h $(CORE_DIR)/rxdiag_core.c $(CORE_DIR)/rxdiag_core.h
	$(CC) $(CFLAGS) -o $@ test_core.c fake.c $(CORE_DIR)/rxdiag_core.c

rxdiag_sim: rxdiag_sim.c fake.c fake.h $(CORE_DIR)/rxdiag_core.c $(CORE_DIR)/rxdiag_core.h
	$(CC) $(CFLAGS) -o $@ rxdiag_sim.c fake.c $(CORE_DIR)/rxdiag_core.c

test: clean all
	./test_core $(VECTORS)
	./rxdiag_sim --help >/dev/null
	./rxdiag_sim --selftest

clean:
	rm -f test_core rxdiag_sim
	rm -rf *.dSYM

.PHONY: all test clean
