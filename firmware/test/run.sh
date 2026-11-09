#!/bin/sh
# Offline parser tests (host cc, no hardware).
set -e
cd "$(dirname "$0")"
cc -Wall -Wextra -o test_cmd_parse test_cmd_parse.c ../main/cmd_parse.c
./test_cmd_parse
cc -Wall -Wextra -Werror -o test_packet test_packet.c ../main/packet.c ../main/cmd_parse.c
./test_packet
cc -Wall -Wextra -o test_line_in test_line_in.c
./test_line_in
cc -Wall -Wextra -Werror -o test_vectors test_vectors.c ../main/cmd_parse.c
./test_vectors
