"""Shared style for the d8tx explainer scenes: the 3Blue1Brown look (see STYLE-3b1b.md section 4 'Look').

Sources: 3b1b/videos custom_config.yml (background #000000, text font CMU Serif) and 3b1b/manim
manimlib/default_config.yml `colors:` (BLUE_C 58C4DD, YELLOW_C FFFF00, GREEN_C 83C167, RED_C FC6255, GREY_A..E).
Manim CE ships the same hex values under the same names; the project names below shadow a few of them
(BLUE_A, GREEN_A, ...) with the *role* colours the scenes use, so always take colours from here.
All text is LaTeX (Computer Modern): `label`/`caption` are Tex (roman), `num` is Tex digits, `mono` is \texttt."""
from manim import *

# -- palette (3b1b manimlib names in the comments) --
BG = "#000000"        # custom_config.yml camera.background_color
INK = "#FFFFFF"       # WHITE: captions, the key cap letter
MUTED = "#BBBBBB"     # GREY_B: labels, braces, axis lines
STRUCT = "#888888"    # GREY_C: outlines of boxes we do not follow
GRID = "#444444"      # GREY_D: grid and structure lines (use with stroke_opacity <= 0.6)
DIM = 0.3             # opacity for everything that is not the piece while it moves
BLUE_A = "#58C4DD"    # BLUE_C: app / host, bit 1   (shadows manim's light BLUE_A on purpose)
BLUE_DK = "#29ABCA"   # BLUE_D: secondary blue (other channels, struts)
BLUE_LT = "#9CDCEB"   # BLUE_B: mechanical / drone (was purple)
GREEN_A = "#83C167"   # GREEN_C: ok / checksum good / firmware
YELLOW_A = "#FFFF00"  # YELLOW_C: the piece we follow (1150, bd, the packet)
RED_A = "#FC6255"     # RED_C: bit 0 / RF / check bytes
PURPLE_A = BLUE_LT    # no purple in the palette; kept as a name for the drone scenes
ONE = BLUE_A          # bit 1 / +39 kHz
ZERO = RED_A          # bit 0 / -39 kHz

config.background_color = BG
FW = config.frame_width   # 14.22
FH = config.frame_height  # 8

# -- strokes (frame units; CE scales them with resolution, so 480p and 1080p look alike) --
SW_THIN = 1.0         # grid, cross hairs, dashed guides
SW = 2.0              # boxes, axes, circles
SW_LINE = 3.0         # a line we follow (trace segments, arrows, hop path)
SW_FLASH = 5.0        # ShowPassingFlash pulses

_TEX_CHARS = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
              "~": r"\textasciitilde{}", "^": r"\^{}", "$": r"\$",
              "µ": r"$\mu$", "μ": r"$\mu$", "−": "$-$", "±": r"$\pm$", "×": r"$\times$", "·": r"$\cdot$",
              "✓": r"\checkmark", "→": r"$\rightarrow$", "←": r"$\leftarrow$", "↑": r"$\uparrow$", "↓": r"$\downarrow$", "÷": r"$\div$", "≈": r"$\approx$", "°": r"$^\circ$"}


def tex_escape(text):
    """Plain words (with µ − ± × · ✓) -> LaTeX text-mode source."""
    return "".join(_TEX_CHARS.get(ch, ch) for ch in text)


def caption(text, size=32):
    """Bottom caption, plain and calm, Computer Modern roman."""
    return Tex(tex_escape(text), font_size=size, color=INK).to_edge(DOWN, buff=0.5)


def caption_at(frame, text, size=32):
    """Caption pinned to the bottom of a MovingCameraScene frame, whatever its zoom."""
    s = frame.width / FW
    return Tex(tex_escape(text), font_size=size, color=INK).scale(s).move_to(frame.get_center() + DOWN * (frame.height / 2 - 0.6 * s))


def label(text, size=24, color=MUTED):
    """A word or two next to an object (CM roman)."""
    return Tex(tex_escape(text), font_size=size, color=color)


def num(text, size=26, color=INK):
    """A decimal quantity (1150): CM roman digits, like a DecimalNumber."""
    return Tex(tex_escape(str(text)), font_size=size, color=color)


def mono(text, size=26, color=INK):
    """Bytes, hex and bits: CM typewriter."""
    return Tex(r"\texttt{" + tex_escape(str(text)) + "}", font_size=size, color=color)


def scene_title(text):
    return Tex(tex_escape(text), font_size=34, color=INK).to_edge(UP, buff=0.4)


# ---- shared building blocks, so one object can carry over between scene files ----

# The hero packet: throttle 1150 µs, others 1500, arm 2000 (experiments/14: armed, throttle at the 15 % cap).
# Bytes from tools/d8-tx-host/d8_vectors.py build(0, raw) with raw = (us*3+1)//2 (firmware/main/packet.c d8_us_to_raw).
BODY = bytes.fromhex("1142b2000001bdcacaca8688cacab8ca888b")
CRC = bytes.fromhex("7109")
AIR_HEAD = bytes.fromhex("aaaaaaaad391")   # packet.c d8_air: 4 x 0xaa preamble, sync d3 91
CH = [("T", 1150), ("A", 1500), ("E", 1500), ("R", 1500), ("1", 1500), ("2", 1500), ("ARM", 2000), ("4", 1500)]
LOWI = [6, 7, 8, 9, 12, 13, 14, 15]
HIGHI = [(10, 0), (10, 4), (11, 0), (11, 4), (16, 0), (16, 4), (17, 0), (17, 4)]
HERO_BYTE = 6                                  # byte 6 = low 8 bits of throttle = 0xbd
HERO_BITS = [int(b) for b in f"{BODY[HERO_BYTE]:08b}"]  # 1 0 1 1 1 1 0 1, MSB first (packet.c sends MSB first)
BIT_PITCH = 1.3        # screen spacing of the 8 hero bits in S03 (one wave segment under each, parts.WAVE_W)
BIT_Y = 2.4


def raw(us):
    return (us * 3 + 1) // 2


def _check():
    b = bytearray(18); b[0:6] = bytes([0x11, 0x42, 0xb2, 0, 0, 1])
    for i, (_, us) in enumerate(CH):
        v = raw(us); b[LOWI[i]] = v & 255; b[HIGHI[i][0]] |= (v >> 8) << HIGHI[i][1]
    assert bytes(b) == BODY, bytes(b).hex()
    # CRC-16 poly 0x8005 init 0xffff (d8_vectors.crc16)
    c = 0xFFFF
    for x in b:
        c ^= x << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    assert bytes([c >> 8, c & 255]) == CRC, hex(c)
    assert len(AIR_HEAD) + len(BODY) + len(CRC) == 26 and 26 * 8 == 208


_check()


# ---- carry-over objects: the last frame of one scene and the first of the next are built from these ----

def hero_number(size=72):
    """`1150 µs` as it ends S01 / starts S02, centred."""
    g = VGroup(num("1150", size, YELLOW_A), label("µs", size // 2))
    g.arrange(RIGHT, buff=0.15, aligned_edge=DOWN).move_to(ORIGIN)
    return g


# byte-row geometry shared by S02 (the row) and S05 (its tiny copy)
BCELL, BPITCH = 0.6, 0.66
BHEX = 26
def bit_squares(bits=HERO_BITS, side=0.6, size=34):
    g = VGroup()
    for b in bits:
        sq = Square(side, color=ONE if b else ZERO, stroke_width=SW, fill_color=ONE if b else ZERO, fill_opacity=0.1)
        g.add(VGroup(sq, mono(str(b), size, ONE if b else ZERO).move_to(sq)))
    return g.arrange(RIGHT, buff=0.1)


# hop grid shared by S04 (the grid) and S05 (the block that arrives)
TABLE = [0] + [(2 + 55 * i) % 256 for i in range(1, 47)]   # packet.c d8_hop_table, E8 identity start 2 step 55 (packet.h)
assert len(set(TABLE)) == 47
LANES = sorted(TABLE)
SLOT_W, LANE_H = 0.7, 0.25
CLOSE_W = 5.0                  # camera width while close on one packet cell
PKT_W, PKT_H = SLOT_W * 0.75, LANE_H * 0.8   # packet 6.70 ms of the 8.994 ms slot (experiments/05, 06)


def grid_pos(slot, ch):
    return np.array([(slot + 0.5) * SLOT_W, (LANES.index(ch) + 0.5) * LANE_H, 0])


def packet_block(scale=1.0, color=YELLOW_A):
    # the one filled object: the piece itself, so it reads at any zoom (3b1b fills his highlight rects, nothing else)
    return Rectangle(width=PKT_W * scale, height=PKT_H * scale, color=color, fill_color=color, fill_opacity=0.9,
                     stroke_width=0)


def packet_block_big():
    """The packet as seen through the close camera: S04 end / S05 start, centred."""
    return packet_block(FW / CLOSE_W)


STREAM_W = 2.0                 # camera width when S04 ends zoomed on our packet in the stream row
STREAM_CAP = "our packet, carrying 1150"   # caption on the S04 end / S05 start frame


def packet_stream_close():
    """S04 end / S05 start as seen through the STREAM_W camera: VGroup(our packet, dim neighbours one slot each side)."""
    z = FW / STREAM_W
    ours = packet_block(z)
    side = VGroup(*[packet_block(z).set_fill(opacity=DIM).move_to(RIGHT * d * SLOT_W * z) for d in (-1, 1)])
    return VGroup(ours, side)


def cell_alpha(c, a):
    """Dim/undim a byte cell VGroup(square, chars) without filling the square."""
    c[0].set_stroke(opacity=a)
    c[1].set_fill(opacity=a)
    return c


# ---------------------------------------------------------------------------------------------------------
# Narration (manim-voiceover). Scene files only do:  class S0x(Narrated, MovingCameraScene):  and
#     with self.voiceover(text="Written form, 6BD and 1150 µs.") as tracker:
#         self.play(..., run_time=tracker.duration)
# The text is respelled for the voice (see spoken()) automatically; the caption keeps the written form.
# ---------------------------------------------------------------------------------------------------------
import re as _re
import subprocess as _sp
from pathlib import Path as _Path

from manim_voiceover import VoiceoverScene
from manim_voiceover.helper import remove_bookmarks as _remove_bookmarks
from manim_voiceover.services.base import SpeechService, initialize_speech_service, path_to_string

_SPOKEN = [  # order matters: longer / more specific first
    (r"\bCC2500\b", "C C twenty-five hundred"), (r"\bESP32\b", "E S P thirty-two"), (r"\b6BD\b", "six B D"),
    (r"\bBD\b", "B D"), (r"\b1150\b", "eleven fifty"), (r"\b1725\b", "seventeen twenty-five"),
    (r"\b2-FSK\b", "two F S K"), (r"\bGFSK\b", "G F S K"), (r"\bFSK\b", "F S K"),
    (r"\bUART\b", "Yoo Art"), (r"\bFourier\b", "[Fourier](/fˈʊɹiˌA/)"), (r"\bTinyhawk\b", "Tiny hawk"), (r"\bFrSky\b", "F R Sky"), (r"\b[Cc]hecksums?\b", lambda m: "check " + ("sums" if m.group().endswith("s") else "sum")), (r"\bSPI\b", "S P I"), (r"\bUSB\b", "U S B"), (r"\bSDR\b", "S D R"), (r"\bID\b", "I D"),
    (r"\bE8\b", "E eight"), (r"\bD8\b", "D eight"), (r"\bD 8\b", "D eight"), (r"\bBetaflight\b", "Beta flight"),
    (r"\bkHz\b", "kilohertz"), (r"\bMHz\b", "megahertz"), (r"\bGHz\b", "gigahertz"),
    (r"(\d)\s*%", r"\1 percent"),
    (r"µs|μs", " microseconds"), (r"\bms\b", "milliseconds"), (r"−", "minus "), (r"±", "plus or minus "),
    (r"×", " times "), (r"÷", " divided by "),
]
# Checked for Kokoro am_michael by whisper (small.en) on every synthesized line, 2026-11-10: "Yoo Art" is heard as UART ("You Art"
# came back as "you aren't"/"you art"), "Foo-ree-ay" is heard as Fourier but sounded wrong to the owner; Fourier uses misaki's inline phoneme override (/fˈʊɹiˌA/ = FOOR-ee-ay), checked by phonemes not whisper. Tiny hawk, F R Sky,
# check sum, S P I, kilohertz, microseconds, gigahertz, two F S K, G F S K, E S P thirty-two, six B D, eleven fifty, percent
# all come back right. A sentence-initial "D eight" is transcribed "The 8" by whisper (its onset), fine mid-sentence.


def spoken(text):
    """Written form -> what the TTS should say. Leaves <bookmark mark='X'/> tags untouched. Extend _SPOKEN."""
    out = []
    for part in _re.split(r"(<bookmark\s*mark\s*=\s*['\"]\w*['\"]\s*/>)", text):
        if not part.startswith("<bookmark"):
            for pat, rep in _SPOKEN:
                part = _re.sub(pat, rep, part)
            part = _re.sub(r"\s+", " ", part)
        out.append(part)
    return "".join(out)


class MacSayService(SpeechService):
    """Offline macOS `say` -> aiff -> mp3 (ffmpeg). No word timings: bookmarks use a linear text->time fallback."""

    def __init__(self, voice="Samantha", rate=165, **kwargs):
        initialize_speech_service(self, kwargs)
        self.voice, self.rate = voice, rate

    def generate_from_text(self, text, cache_dir=None, path=None, **kwargs):
        cache_dir = cache_dir or self.cache_dir
        input_text = _remove_bookmarks(text)
        input_data = {"input_text": input_text, "service": "macsay", "voice": self.voice, "rate": self.rate}
        cached = self.get_cached_result(input_data, cache_dir)
        if cached is not None:
            return cached
        audio_path = path_to_string(path) if path else self.get_audio_basename(input_data) + ".mp3"
        aiff = _Path(cache_dir) / (audio_path + ".aiff")
        _sp.run(["say", "-v", self.voice, "-r", str(self.rate), "-o", str(aiff), input_text], check=True)
        _sp.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), str(_Path(cache_dir) / audio_path)], check=True)
        aiff.unlink()
        return {"input_text": text, "input_data": input_data, "original_audio": audio_path}


class KokoroService(SpeechService):
    """Local Kokoro-82M (free, offline after the first download). Synthesises wav -> mp3 (ffmpeg), cached on disk like
    MacSayService. Returns WORD BOUNDARIES from Kokoro's per-token timestamps (text_offset = character offset in the
    bookmark-free spoken text), so manim-voiceover bookmarks work and frac_to_seconds() below is exact."""

    _pipeline = None          # one model per process

    def __init__(self, voice="am_michael", speed=1.0, tail=0.2, **kwargs):
        initialize_speech_service(self, kwargs)
        self.voice, self.speed, self.tail = voice, speed, tail

    @classmethod
    def pipeline(cls):
        if cls._pipeline is None:
            import warnings
            import logging
            warnings.filterwarnings("ignore")
            logging.getLogger("httpx").setLevel(logging.WARNING)
            from kokoro import KPipeline
            cls._pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        return cls._pipeline

    def generate_from_text(self, text, cache_dir=None, path=None, **kwargs):
        import numpy as np
        import soundfile as sf
        cache_dir = cache_dir or self.cache_dir
        input_text = _remove_bookmarks(text)
        input_data = {"input_text": input_text, "service": "kokoro", "voice": self.voice, "speed": self.speed,
                      "tail": self.tail, "v": 2}
        cached = self.get_cached_result(input_data, cache_dir)
        if cached is not None:
            return cached
        audio_path = path_to_string(path) if path else self.get_audio_basename(input_data) + ".mp3"
        chunks, bounds, cursor, t_off = [], [], 0, 0.0
        for r in self.pipeline()(input_text, voice=self.voice, speed=self.speed):
            audio = r.audio.numpy() if hasattr(r.audio, "numpy") else np.asarray(r.audio)
            for tok in r.tokens or []:
                i = input_text.find(tok.text, cursor)
                if i < 0 or tok.start_ts is None or not any(ch.isalnum() for ch in tok.text):
                    continue
                cursor = i + len(tok.text)
                bounds.append({"audio_offset": int((t_off + tok.start_ts) * 1e7), "text_offset": i,
                               "word_length": len(tok.text), "text": tok.text, "boundary_type": "Word"})
            chunks.append(audio)
            t_off += len(audio) / 24000
        audio = np.concatenate(chunks + [np.zeros(int(self.tail * 24000), dtype=chunks[0].dtype)])
        bounds.append({"audio_offset": int(t_off * 1e7), "text_offset": len(input_text), "word_length": 1, "text": ".",
                       "boundary_type": "Word"})
        wav = _Path(cache_dir) / (audio_path + ".wav")
        sf.write(str(wav), audio, 24000)
        _sp.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), str(_Path(cache_dir) / audio_path)], check=True)
        wav.unlink()
        return {"input_text": text, "input_data": input_data, "original_audio": audio_path, "word_boundaries": bounds}


def frac_to_seconds(tr, frac):
    """Seconds from the voiceover start at which `frac` (0..1) of the spoken characters have been said. Exact (word timings)
    with KokoroService, linear (frac * duration) with any service without word boundaries."""
    wb = tr.data.get("word_boundaries") if hasattr(tr, "data") else None
    if not wb or len(wb) < 2:
        return frac * tr.duration
    xs = [b["text_offset"] for b in wb]
    ys = [b["audio_offset"] / 1e7 for b in wb]
    return float(__import__("numpy").interp(frac * xs[-1], xs, ys))


def voice_service():
    """THE ONE LINE TO CHANGE to swap the narrator voice."""
    # from manim_voiceover.services.elevenlabs import ElevenLabsService
    # return ElevenLabsService(voice_name="Chris", model="eleven_multilingual_v2")   # needs ELEVEN_API_KEY; paid
    # return MacSayService(voice="Samantha", rate=165)
    return KokoroService(voice="am_michael", speed=1.1)


class Narrated(VoiceoverScene):
    """Mixin/base: put first, e.g. `class S01(Narrated, MovingCameraScene)`. Sets the voice and respells the text."""

    def setup(self):
        super().setup()
        self.set_speech_service(voice_service(), create_subcaption=False)

    def voiceover(self, text=None, **kwargs):
        return super().voiceover(text=spoken(text), **kwargs)
