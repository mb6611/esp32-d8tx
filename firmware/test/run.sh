#!/bin/sh
# Offline parser tests (host cc, no hardware). The parser is built twice: release (default) and bench (-DCONFIG_D8_BENCH=1).
set -e
cd "$(dirname "$0")"
for cfg in "" "-DCONFIG_D8_BENCH=1"; do
  cc -Wall -Wextra $cfg -o test_cmd_parse test_cmd_parse.c ../main/cmd_parse.c ../main/packet.c
  ./test_cmd_parse
  cc -Wall -Wextra -Werror $cfg -o test_packet test_packet.c bf_bind_port.c ../main/packet.c ../main/cmd_parse.c
  ./test_packet
done
cc -Wall -Wextra -o test_line_in test_line_in.c
./test_line_in
for cfg in "" "-DCONFIG_D8_BENCH=1"; do
  cc -Wall -Wextra -Werror $cfg -o test_vectors test_vectors.c ../main/cmd_parse.c ../main/packet.c
  ./test_vectors
done
