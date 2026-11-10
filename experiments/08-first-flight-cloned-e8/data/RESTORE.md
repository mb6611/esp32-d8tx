# Restore stock Betaflight on the Tinyhawk (MATEKF411RX)

Source: `bench/cc2500-rxdiag/README.md` "Restored afterwards".

1. Put the FC in DFU mode and flash the stock image
   `bench/cc2500-rxdiag/recovery/assets/betaflight_4.2.11_MATEKF411RX.bin`.
   Verify its sha256 starts with `bb32b85a` (`shasum -a 256 <bin>`) before flashing.
2. After the board boots: defaults, then replay the evidence diff from `bench/cc2500-rxdiag/recovery/`
   (the earlier replay log ended in an OSError when the board re-enumerated: wait for re-enumeration and check
   the serial port again; do not trust the log alone).
3. Set acc_calibration / acc_trim to the pre-flash values (the recovery diff has older ones).
4. Verify: CLI `diff all` saved to a file must be identical (`cmp`) to `bench/cc2500-rxdiag/diff_all_final.txt`
   (287 lines). Also check `version` against `version_final.txt`.
5. Close the serial port in every tool before flashing; no process may hold it.
