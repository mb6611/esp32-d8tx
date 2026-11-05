// Channel value range (µs) and the shared mapping to 0..1.
export const LO = 980, HI = 2020, MID = 1500;
export const frac = (us: number) => Math.min(1, Math.max(0, (us - LO) / (HI - LO)));
