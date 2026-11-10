/* rxdiag glue: binds rxdiag_core to Betaflight (SPI, IO, USB CDC). Built only under USE_RXDIAG_CC2500. */
#pragma once

struct serialPort_s;

// CLI entry: "rxdiag <args>"; cmdline is the text after the command name.
void rxdiagCliRun(struct serialPort_s *port, char *cmdline);
