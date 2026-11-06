# U4 rerun3 (2412 MHz, agc 203/66, ESP power 127, 150 ms tones). Script rerun3.py (stage control|tone BW list)
STM fw=3b26d459, ESP `P,d8tone,1`. No overruns/stuck keys/reboots (STAT keyed=0 after every rep, PING OK after).
## Source-off control (30 windows)
- bw 203: SATURATED (fe_min -16 / fe_max 15 in 24/30 windows, ncs 3-111). Per rule, tried 102.
- bw 102: quiet: only 2/30 windows with CS (ncs 3), fe within -8..7. Used bw 102 for tones.
## Keyed (bw 102, 3 reps each; keyed windows 4-6; w5 is peak). ncs per w4/w5/w6; baseline ncs ~0-3 (f=-16 r1 baseline had noisy 76-665 in other windows)
| setting | rep | ncs w4/w5/w6 | fe_mean_hz w4/w5/w6 | fe_min/max w4,w5 |
| 0  | 1 | 580/1969/398 | -9521/-9521/-9393 | -6/-6, -6/-6 |
| 0  | 2 | 641/1966/331 | 11108/11108/10806 | 7/7, 7/7 |
| 0  | 3 | 328/1971/661 | -12695/-12695/-12584 | -8/-8, -8/-8 |
| +16| 1 | 620/1941/356 | -6368/5307/11037 | -8/-4, -8/7 |
| +16| 2 | 715/1944/248 | 4760/9159/10206 | 3/3, -8/7 |
| +16| 3 | 688/1933/347 | 6347/5761/8332 | 4/4, -8/7 |
| -16| 1 | 613/1921/398 | -10608/-7970/2400 | -8/7 both |
| -16| 2 | 420/1954/540 | 5251/11077/6706 | -8/7, 4/7 |
| -16| 3 | 646/1944/331 | 10759/11022/11070 | -4/7, -1/7 |
(-8/7 are the freq-estimate rails at bw 102; -12695 Hz = -8, +11108 = +7.)
## Verdict
Gate passed: ncs rises to 330-1970 vs ~0-3 baseline in exactly the keyed windows, at both 812 and 102 bw, so the carrier stays inside the 102 kHz filter. But FREQEST is NOT usable: the f=0 reps alone give -9521, +11108, -12695 Hz (sign flips, rails), spread larger than any +-16 difference; +16 and -16 are not ordered vs 0 (w5 means: f0 -9.5/+11.1/-12.7k, +16 5.3/9.2/5.8k, -16 -8.0/+11.1/+11.0k). +16/0/-16 are NOT distinguishable by this method. Likely the carrier lies near/beyond the +-edge of the estimate range or the estimator is railed by the strong tone (CS-count/AGC dynamics); not resolved. No bw 406 rerun (ncs did not drop). ALT not run (budget/pointless without resolved offset). Used 9 good + 3 aborted keyed commands (aborted/ = STM serial truncation, ESP unaffected).
