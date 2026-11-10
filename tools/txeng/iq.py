"""Unpack classic-ESP32 capture words and measure tone lines."""
import numpy as np


def unpack(words):
    w = np.asarray(words, dtype=np.uint32)
    i = (w & 0x3FF).astype(np.int32)
    q = ((w >> 10) & 0x3FF).astype(np.int32)
    i[i >= 512] -= 1024
    q[q >= 512] -= 1024
    return i - 1j * q  # esp-sdr: Q is negated in the capture


def line_db(x, fs, f, nfft=1024):
    """Averaged-periodogram power at +f and -f relative to the median bin, plus DC and rms.
    Returns dict(pos, neg, dc, rms, peak_f, peak_db)."""
    x = np.asarray(x, dtype=np.complex128)
    x = x - 0  # keep DC: we want to see LO feedthrough too
    nseg = len(x) // nfft
    win = np.hanning(nfft)
    p = np.zeros(nfft)
    for k in range(nseg):
        p += np.abs(np.fft.fft(x[k * nfft:(k + 1) * nfft] * win)) ** 2
    p /= max(nseg, 1)
    p = np.fft.fftshift(p)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs))
    med = np.median(p) + 1e-12

    def at(fr):
        k = int(np.argmin(np.abs(freqs - fr)))
        return 10 * np.log10(p[max(k - 1, 0):k + 2].max() / med)

    nodc = p.copy()
    nodc[nfft // 2 - 2:nfft // 2 + 3] = 0
    kp = int(np.argmax(nodc))
    return dict(pos=at(f), neg=at(-f), dc=at(0.0), rms=float(np.sqrt(np.mean(np.abs(x) ** 2))),
                peak_f=float(freqs[kp]), peak_db=float(10 * np.log10(nodc[kp] / med)))
