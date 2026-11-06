#!/usr/bin/env python3
import os, re, sys, subprocess

FW = os.path.abspath(sys.argv[1])
BF = os.path.join(FW, "work", "betaflight")
OVL = os.path.join(FW, "overlay", "src", "main")
fails = []
passes = []

def ok(msg): passes.append(msg)
def bad(msg): fails.append(msg)
def rd(p): return open(p, encoding="utf-8", errors="replace").read()
def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)

core_c = os.path.join(OVL, "rx", "rxdiag_core.c")
glue_c = os.path.join(OVL, "rx", "rxdiag_cc2500.c")
cfg_c = os.path.join(OVL, "target", "MATEKF411RX", "config.c")
for p in (core_c, glue_c, cfg_c):
    if not os.path.exists(p):
        bad("missing " + p)
if fails:
    print("\n".join("FAIL " + f for f in fails)); sys.exit(1)

core = strip_comments(rd(core_c)); glue = strip_comments(rd(glue_c)); cfg = strip_comments(rd(cfg_c))

# 1. no cc2500[A-Z] calls anywhere in diagnostic code
for name, s in (("core", core), ("glue", glue), ("config.c", cfg)):
    m = re.search(r"\bcc2500[A-Z]\w*", s)
    (bad if m else ok)(f"{name}: no cc2500[A-Z] symbol" + (f" (found {m.group(0)})" if m else ""))

# 2. TX_EN is never driven high
for name, s in (("glue", glue), ("config.c", cfg), ("core", core)):
    hi = [l for l in s.splitlines() if re.search(r"tx_?en", l, re.I) and re.search(r"IOHi\s*\(|IOWrite\s*\(.*(true|1)\s*\)|IOToggle|cc2500TxEnable", l)]
    (bad if hi else ok)(f"{name}: no IOHi/IOWrite-high on TX_EN" + (f" {hi}" if hi else ""))
if re.search(r"IOHi\s*\(\s*c->txen", glue) or re.search(r"IOHi\s*\(\s*\w*txen", glue, re.I):
    bad("glue: IOHi on txen")
m = re.search(r"rxdiagPinOut\(\s*rxCc2500SpiConfig\(\)->txEnIoTag\s*,\s*OWNER_RX_SPI_CC2500_TX_EN\s*,\s*(\w+)\)", cfg)
(ok if m and m.group(1) == "false" else bad)("config.c: targetPreInit drives TX_EN low (false)")
m = re.search(r"rxdiagPinOut\(\s*rxCc2500SpiConfig\(\)->lnaEnIoTag\s*,\s*OWNER_RX_SPI_CC2500_LNA_EN\s*,\s*(\w+)\)", cfg)
(ok if m and m.group(1) == "false" else bad)("config.c: targetPreInit drives LNA_EN low")
# Only these IOHi sites are allowed in glue: ant and lna (inside hFrontEnd)
sites = re.findall(r"IOHi\s*\(\s*([^)]*)\)", glue)
(ok if sorted(sites) == ["c->ant", "c->ant", "c->lna"] else bad)(f"glue: IOHi sites are exactly ant (hFrontEnd, hAntSet), lna (got {sites})")
for fn, want in (("hFrontEnd", ["c->ant", "c->lna"]), ("hAntSet", ["c->ant"])):
    mfn = re.search(r"static \w+ " + fn + r"\([^)]*\)\s*\{(.*?)\n\}", glue, re.S)
    got = re.findall(r"IOHi\s*\(\s*([^)]*)\)", mfn.group(1)) if mfn else None
    (ok if got == want else bad)(f"glue: IOHi inside {fn} only {want} (got {got})")
# GDO0/EXTI: input-only pin, disarm path disables EXTI, no output drive of the gdo pin
(ok if not re.search(r"IO(Hi|Lo|Write|Toggle)\s*\(\s*c->gdo", glue) else bad)("glue: GDO0 pin is never driven by the MCU")
marm = re.search(r"static bool hEdgeArm\([^)]*\)\s*\{(.*?)\n\}", glue, re.S)
(ok if marm and re.search(r"if \(!on\) \{\s*edgeArmed = false;\s*EXTIEnable\(c->gdo, false\);\s*return true;", marm.group(1)) else bad)("glue: edgeArm(false) clears edgeArmed and disables EXTI")

# 3. glue SPI uses only the three raw helpers
rxspi = set(re.findall(r"\b(rxSpi\w+)\s*\(", glue))
allowed = {"rxSpiReadCommand", "rxSpiWriteCommand", "rxSpiWriteByte", "rxSpiDeviceInit", "rxSpiConfig"}
(ok if rxspi <= allowed else bad)(f"glue: rxSpi* calls subset of allow-list (got {sorted(rxspi)})")
for forb in ("rxSpiReadCommandMulti", "rxSpiWriteCommandMulti", "rxSpiTransferByte", "spiBusWriteRegisterBuffer"):
    (bad if forb in glue else ok)(f"glue: no {forb}")

# 4. core: raw HAL SPI calls only inside the four whitelist helpers; arguments restricted
raw = re.findall(r"->\s*(spiStrobe|spiRead|spiWrite)\s*\(", core)
(ok if len(raw) == 4 else bad)(f"core: exactly 4 raw HAL SPI call sites (got {len(raw)})")
enum = re.search(r"enum\s*\{(.*?)\};", core, re.S)
consts = dict((n, int(v, 16)) for n, v in re.findall(r"\b([RS]_\w+|STROBE_\w+)\s*=\s*(0x[0-9A-Fa-f]+)", enum.group(1))) if enum else {}
allowed_strobes = {0x30, 0x33, 0x34, 0x36, 0x3D}
for n, v in consts.items():
    if n.startswith("STROBE_") and v not in allowed_strobes: bad(f"core: strobe {n}=0x{v:02X} not allowed")
    if n.startswith("R_") and v > 0x2E and n != "R_PATABLE": bad(f"core: register {n}=0x{v:02X} > 0x2E")
    if n.startswith("S_") and not (0x30 <= v <= 0x3D): bad(f"core: status {n}=0x{v:02X} outside 0x30-0x3D")
for c in re.findall(r"\bspiStrobe\s*\(\s*st\s*,\s*([^)]*)\)", core):
    if not re.fullmatch(r"STROBE_(SRES|SCAL|SRX|SIDLE|SNOP)", c.strip()): bad(f"core: spiStrobe arg {c!r}")
# readStable() forwards its addr parameter (its callers are checked by the same allow-list below)
core_nostable = re.sub(r"static bool readStable\(.*?\n\}\n", "", core, flags=re.S)
for c in re.findall(r"\bspiReadStatus\s*\(\s*st\s*,\s*([^)]*)\)", core_nostable):
    if not re.fullmatch(r"S_\w+", c.strip()): bad(f"core: spiReadStatus arg {c!r}")
for c in re.findall(r"\bspiReadCfg\s*\(\s*st\s*,\s*([^)]*)\)", core):
    if not re.fullmatch(r"R_\w+|cfg\[i\]\.addr", c.strip()): bad(f"core: spiReadCfg arg {c!r}")
for c in re.findall(r"\bspiWriteReg\s*\(\s*st\s*,\s*([^,]*),", core):
    if not re.fullmatch(r"R_\w+|(?:base|tail)Regs\[i\]\.addr|cfg\[i\]\.addr", c.strip()): bad(f"core: spiWriteReg addr {c!r}")
# table-driven events config: every cfg[...] address is a named R_ register (never PATABLE/strobe) or a copy of base/tailRegs
for a in re.findall(r"cfg\[nc(?:\+\+)?\]\.addr\s*=\s*(R_\w+);", core):
    if not re.fullmatch(r"R_(?!PATABLE)\w+", a.strip()): bad(f"core: cfg[nc].addr assigned {a!r}")
for a in re.findall(r"cfg\[nc\]\s*=\s*([^;]+);", core):
    if not re.fullmatch(r"(?:base|tail)Regs\[i\]", a.strip()): bad(f"core: cfg[nc] assigned {a!r}")
(ok if "for (size_t i = 0; i < nc; i++) {\n        spiWriteReg(st, cfg[i].addr" in core and re.search(r"cfg\[sizeof baseRegs", core) else bad)("core: events cfg[] loops bounded by nc, sized from base+4+tail")
# GDO0 mode cleanup: IOCFG0 only written with idle/CS/wire-test values; finish() disarms EXTI and restores 0x2E
vals = set(re.findall(r"spiWriteReg\(st, R_IOCFG0, (0x[0-9A-Fa-f]+)\)", core)) | {"0x2E"}
(ok if {v.upper().replace("0X","0x") for v in vals} <= {"0x2E", "0x0E", "0x2F", "0x6F"} else bad)(f"core: IOCFG0 written only with 2E/0E/2F/6F (got {sorted(vals)})")
mf = re.search(r"static rxdiagResult_e finish\(.*?\n\}", core, re.S)
fb = mf.group(0) if mf else ""
(ok if fb and fb.find("edgeArm(st->h->ctx, false)") != -1 and fb.find("edgeArm(st->h->ctx, false)") < fb.find("R_IOCFG0, 0x2E") < fb.find("STROBE_SIDLE") < fb.find("frontEnd(st->h->ctx, false)") else bad)("core: finish(): EXTI disarm, then IOCFG0 0x2E, then SIDLE, then LNA off")
(ok if core.count("edgeArm(h->ctx, true)") == 1 and "st->gdoOut = true" in core else bad)("core: single EXTI arm site; gdoOut flagged so finish() restores IOCFG0")
for tbl in ("baseRegs", "tailRegs"):
    mt = re.search(tbl + r"\[\]\s*=\s*\{(.*?)\};", core, re.S)
    if not mt: bad(f"core: table {tbl} not found"); continue
    for a, v in re.findall(r"\{\s*(\w+)\s*,\s*(\w+)\s*\}", mt.group(1)):
        if not re.fullmatch(r"R_\w+", a) or a == "R_PATABLE" and v not in ("0", "0x00"): bad(f"core: {tbl} entry {a},{v}")
# no burst / FIFO header literals handed to the HAL
for lit in re.findall(r"0x(?:3F|7F|BF|FF|B[0-9A-D])\b", core, re.I):
    if lit.upper() not in ("0XFF",): bad(f"core: forbidden header literal {lit}")
if not any(f.startswith("core:") for f in fails): ok("core: SPI helper arguments / literals within §6 allow-list")

# 4b. freq mode (proto 3): receive-only status reads, no TX opcode reachable
for sym in ("STX", "SFTX", "SFRX", "STROBE_STX", "STROBE_SFTX", "STROBE_SXOFF", "STROBE_SWOR", "STROBE_SPWD"):
    (bad if re.search(r"\b" + sym + r"\b", core + glue) else ok)(f"core+glue: no {sym} symbol")
strobes = set(re.findall(r"STROBE_\w+", core))
(ok if strobes <= {"STROBE_SRES", "STROBE_SCAL", "STROBE_SRX", "STROBE_SIDLE", "STROBE_SNOP"} else bad)(f"core: strobe set {sorted(strobes)}")
(ok if re.search(r"S_FREQEST\s*=\s*0x32", core) and re.search(r"S_PKTSTATUS\s*=\s*0x38", core) and re.search(r"S_LQI\s*=\s*0x33", core) else bad)("core: FREQEST/PKTSTATUS/LQI addresses 0x32/0x38/0x33")
# FREQEST / PKTSTATUS / LQI only ever read through the guarded status helper (header 0xC0|addr, addr 0x30-0x3D)
raw = re.findall(r"spiRead\s*\(", core)
(ok if len(raw) == 2 else bad)(f"core: raw hal spiRead called from exactly 2 guarded helpers (found {len(raw)})")
for reg in ("S_FREQEST", "S_PKTSTATUS", "S_LQI"):
    total = len(re.findall(r"\b" + reg + r"\b", core)) - 1   # minus the enum definition
    via = len(re.findall(r"\b(?:readStable|spiReadStatus)\s*\(\s*st\s*,\s*" + reg + r"\b", core))
    (ok if total > 0 and total == via else bad)(f"core: {reg} only via readStable/spiReadStatus ({via}/{total})")
cs = re.findall(r"\breadStable\s*\(\s*st\s*,\s*(\w+)", core)
(ok if cs and set(cs) <= {"S_FREQEST", "S_PKTSTATUS", "S_RSSI"} else bad)(f"core: readStable callers {sorted(set(cs))}")
(ok if re.search(r"if \(addr < 0x30 \|\| addr > 0x3D\)", core) else bad)("core: status helper restricted to 0x30-0x3D (no FIFO/PATABLE read)")
(ok if not re.search(r"txen|tx_en|TX_EN", core, re.I) or "txen=0" in core else bad)("core: txen only reported as 0")
fq = core[core.index("static rxdiagResult_e doFreq("):core.index("static bool parseByte(")]
(ok if "frontEnd(h->ctx, true)" in fq and fq.index("liveness(st, &l)") < fq.index("frontEnd(h->ctx, true)") else bad)("doFreq: LNA on only after liveness")
(ok if "finish(st, RXDIAG_DONE" in fq and "durUs" in fq and fq.count("for (;;)") == 1 else bad)("doFreq: bounded by duration, ends through finish()")
(ok if re.search(r"rxdiagDurationValid\(dur\)", core) and re.search(r"FREQ_DUR_MAX_MS\s+60000u", core) else bad)("freq: duration validated, max 60000 ms")

# 5. patches: purely additive; every added line inside a MATEKF411RXDIAG / USE_RXDIAG_CC2500 guard
GUARD = re.compile(r"MATEKF411RXDIAG|USE_RXDIAG_CC2500")
DIRX = re.compile(r"\s*(?:#\s*)?(if|ifdef|ifndef|ifeq|ifneq|elif|else|endif)\b(.*)")
def directive(line, f):
    if f.endswith(".mk"):
        m = re.match(r"(ifeq|ifneq|ifdef|ifndef|else|endif)\b(.*)", line)
        if not m: return None
        k, r = m.groups(); return ({"ifeq": "if", "ifneq": "if"}.get(k, k), r)
    m = re.match(r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", line)
    return m.groups() if m else None
def check_patch(pfile):
    text = rd(pfile)
    files = {}
    cur = None; newln = 0
    for line in text.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else line[4:]
            files[cur] = set()
        elif line.startswith("--- ") or line.startswith("diff ") or line.startswith("index "):
            continue
        elif line.startswith("@@"):
            newln = int(re.search(r"\+(\d+)", line).group(1))
        elif cur:
            if line.startswith("-"):
                bad(f"{os.path.basename(pfile)}: removes a line ({line[:60]!r})")
            elif line.startswith("+"):
                files[cur].add(newln); newln += 1
            else:
                newln += 1
    for f, added in files.items():
        src = rd(os.path.join(BF, f)).splitlines()
        stack = []  # entries: (is_guard_branch_active)
        for i, l in enumerate(src, 1):
            t = l.strip()
            m = directive(l, f)
            line_guarded = bool(stack) and any(stack)
            if m:
                k, rest = m
                if k in ("if", "ifdef"): stack.append(bool(GUARD.search(rest)))
                elif k == "ifndef": stack.append(False)
                elif k == "elif": stack[-1] = bool(GUARD.search(rest))
                elif k == "else": stack[-1] = False
                elif k == "endif": stack.pop()
                if i in added:
                    # structural line added by the patch: must belong to a guarded construct
                    if k in ("else", "endif"):
                        pass  # closes/pairs a guard opened by this patch (checked by balance below)
                    elif not GUARD.search(rest):
                        bad(f"{f}:{i}: added directive without guard: {t}")
                continue
            if i in added and not line_guarded and t:
                # allowed: end-of-file DIAG block lines are guarded by stack; anything else is a violation
                bad(f"{f}:{i}: added line outside guard: {t[:70]}")
        if stack: bad(f"{f}: unbalanced preprocessor after patch")
    return list(files)

pdir = os.path.join(FW, "patches")
touched = []
for p in sorted(os.listdir(pdir)):
    if p.endswith(".patch"):
        before = len(fails)
        touched += check_patch(os.path.join(pdir, p))
        (ok if len(fails) == before else bad)(f"patch {p}: additive and fully guarded")
if not os.path.isdir(BF): bad("applied tree missing")

# 6. config.c fully guarded
body = [l for l in cfg.splitlines() if l.strip()]
first_pp = next(i for i, l in enumerate(body) if l.strip().startswith("#if defined(MATEKF411RXDIAG)"))
pre = [l for l in body[:first_pp] if not l.strip().startswith("#include")]
last = body[-1].strip()
(ok if not pre and last.startswith("#endif") else bad)("config.c: only includes before the MATEKF411RXDIAG guard, ends with #endif")
depth = 0; closes_early = False
for i, l in enumerate(body[first_pp:]):
    t = l.strip()
    if re.match(r"#\s*(if|ifdef|ifndef)\b", t): depth += 1
    elif t.startswith("#endif"):
        depth -= 1
        if depth == 0 and i != len(body[first_pp:]) - 1: closes_early = True
(ok if not closes_early else bad)("config.c: outer guard spans the whole file")
m = re.search(r"#include\s+\"platform.h\"", cfg)
(ok if m else bad)("config.c includes platform.h")

# 7. CLI table sorted + rxdiag present between resource and rxfail
cli = rd(os.path.join(BF, "src/main/cli/cli.c"))
names = re.findall(r'CLI_COMMAND_DEF\("([^"]+)"', cli[cli.index("const clicmd_t cmdTable[]"):])
i = names.index("rxdiag") if "rxdiag" in names else -1
if i < 0: bad("cli: rxdiag entry missing")
else:
    # compare only against neighbours (stock table has its own pre-existing ordering quirks)
    (ok if names[i-1] < "rxdiag" < names[i+1] else bad)(f"cli: rxdiag sorted between {names[i-1]} and {names[i+1]}")
    (ok if names.count("rxdiag") == 1 else bad)("cli: rxdiag defined once")

# 8. no motor/ESC bypass: guards in motor.c and target.h
motor = rd(os.path.join(BF, "src/main/drivers/motor.c"))
m = re.search(r"#if defined\(MATEKF411RXDIAG\)(.*?)#endif", motor, re.S)
blk = m.group(1) if m else ""
need = ["motorNullDevice.vTable = motorNullVTable;", "motorDevice = &motorNullDevice;", "return;"]
(ok if m and all(n in blk for n in need) and blk.find(need[0]) < blk.find(need[1]) < blk.find("return;") else bad)("motor.c: DIAG block assigns null vtable + motorDevice then returns")
ms = motor.index("void motorDevInit(")
(ok if motor.index("memset(motors, 0, sizeof(motors));", ms) < motor.index("#if defined(MATEKF411RXDIAG)", ms) < motor.index("motorPwmDevInit(", ms) else bad)("motor.c: memset, then DIAG null-device block before any motor init call")
for sym in ("motorPwmDevInit", "dshotPwmDevInit", "dshotBitbangDevInit"):
    for name, s in (("glue", glue), ("config.c", cfg), ("core", core)):
        if sym in s: bad(f"{name}: references {sym}")
th = rd(os.path.join(BF, "src/main/target/MATEKF411RX/target.h"))
tail = th[th.rindex("#if defined(MATEKF411RXDIAG)"):]
for tok in ("#undef USE_ESCSERIAL", "#undef USE_ESCSERIAL_SIMONK", "#undef USE_SERIAL_4WAY_BLHELI_BOOTLOADER",
            "#undef USE_SERIAL_4WAY_SK_BOOTLOADER", "#undef DEFAULT_RX_FEATURE", "#define DEFAULT_RX_FEATURE      FEATURE_RX_MSP",
            "#undef DEFAULT_FEATURES", "#define DEFAULT_FEATURES        0", "#define USE_TARGET_CONFIG",
            "#define TARGET_VALIDATECONFIG", "#define TARGET_PREINIT", "#undef USE_TELEMETRY"):
    (ok if tok in tail else bad)(f"target.h DIAG block: {tok}")
(ok if re.search(r"TARGET_BOARD_IDENTIFIER \"M41R\"\n#define USBD_PRODUCT_STRING     \"MATEKF411RX-RXDIAG\"", th) else bad)("target.h: board M41R, product MATEKF411RX-RXDIAG")
radio = th[th.index("#elif defined(MATEKF411RXDIAG)", th.index("SPI3 CC2500")):th.index("#else // MATEKF411RX")]
(ok if re.search(r"RX_SPI_DEFAULT_PROTOCOL|USE_RX_FRSKY|USE_RX_SFHSS|USE_RX_REDPINE|USE_RX_FLYSKY", radio) is None else bad)("target.h radio branch: no protocol defines")
(ok if "USE_RX_CC2500" in radio and "USE_RXDIAG_CC2500" in radio else bad)("target.h radio branch: USE_RX_CC2500 + USE_RXDIAG_CC2500")
mk = rd(os.path.join(BF, "src/main/target/MATEKF411RX/target.mk"))
(ok if "ifeq ($(TARGET),MATEKF411RXDIAG)" in mk and "rx/rxdiag_core.c" in mk and "rx/rxdiag_cc2500.c" in mk else bad)("target.mk: DIAG appends core+glue")
altmk = [l for l in rd(os.path.join(OVL, "target/MATEKF411RX/MATEKF411RXDIAG.mk")).splitlines() if l.strip() and not l.startswith("#")]
(ok if not altmk else bad)("MATEKF411RXDIAG.mk is comment-only")
vcp = rd(os.path.join(BF, "src/main/vcpf4/usbd_cdc_vcp.c"))
(ok if "CDC_Send_DATA_NB" in vcp and vcp.count(">= 50U") == 2 and "waited >= 50U" in vcp else bad)("vcp: NB writer + both waits bounded to 50")
# stock path unchanged when DIAG undefined: removing the DIAG-guarded text must restore the original file
def strip_diag(text, f):
    out = []
    stack = []  # [kind, skipping]  kind: 'diag' (opened by a DIAG #if) | 'norm'
    def skipping(): return any(e[1] for e in stack)
    for l in text.split("\n"):
        m = directive(l, f)
        if not m:
            if not skipping(): out.append(l)
            continue
        k, rest = m
        if k in ("if", "ifdef", "ifndef"):
            if k != "ifndef" and GUARD.search(rest) and not stack_is_skipping(stack):
                stack.append(["diag", True]); continue
            stack.append(["norm", False])
            if not skipping(): out.append(l)
        elif k == "elif":
            e = stack[-1]
            if e[0] == "diag": e[1] = bool(GUARD.search(rest)); 
            elif GUARD.search(rest): e[1] = True; continue
            else: e[1] = False
            if e[0] == "diag": continue
            if not skipping(): out.append(l)
        elif k == "else":
            e = stack[-1]
            if e[0] == "diag": e[1] = False; continue
            was = e[1]; e[1] = False
            if not skipping(): out.append(l)
        else:
            e = stack.pop()
            if e[0] == "diag": continue
            if not skipping(): out.append(l)
    return "\n".join(out)
def stack_is_skipping(stack): return any(e[1] for e in stack)
for f in sorted(set(touched)):
    if f.endswith(".patch"): continue
    orig = subprocess.run(["git", "-C", BF, "show", "HEAD:" + f], capture_output=True, text=True).stdout
    cur = rd(os.path.join(BF, f))
    nb = lambda x: "\n".join(l for l in x.split("\n") if l.strip())
    (ok if nb(strip_diag(cur, f)) == nb(orig) else bad)(f"{f}: with DIAG branches removed, equals stock source")

# 9. F411 SPI3 divisor translation regression (BF 4.2.11): the driver argument is halved for SPI2/SPI3
std = rd(os.path.join(BF, "src/main/drivers/bus_spi_stdperiph.c"))
sysf = rd(os.path.join(BF, "src/main/startup/system_stm32f4xx.c"))
halves = re.search(r"if \(instance == SPI2 \|\| instance == SPI3\) \{\s*divisor /= 2;", std) is not None
f411 = re.search(r"#if defined\(STM32F410xx\) \|\| defined\(STM32F411xE\)\s*.*?RCC_CFGR_PPRE2_DIV1;.*?RCC_CFGR_PPRE1_DIV2;", sysf, re.S) is not None
(ok if halves else bad)("bus_spi_stdperiph.c halves the divisor for SPI2/SPI3")
(ok if f411 else bad)("system_stm32f4xx.c: F411 APB2=/1, APB1=/2")
def br_hz(arg, pclk):
    d = arg // 2; d = max(2, min(256, d))
    br = ((d & -d).bit_length()) - 2          # ffs(d) - 2
    return pclk // (2 << br)
SYS = 100_000_000; PCLK1 = SYS // 2
m = re.search(r"#define RXDIAG_SPI_DIVISOR\s+(\d+)", glue)
arg = int(m.group(1)) if m else 0
hz = br_hz(arg, PCLK1)
(ok if arg == 32 and hz == 3_125_000 and br_hz(arg, 54_000_000) <= 6_500_000 else bad)(f"glue driver divisor {arg} -> SPI3 {hz} Hz (<= 6.5 MHz; also at measured PCLK1=54 MHz; divisor 16 measured 6.75 MHz)")
(ok if br_hz(8, PCLK1) == 12_500_000 else bad)("model check: SPI_CLOCK_STANDARD(8) would be 12.5 MHz on SPI3")
(ok if "(inst->CR1 >> 3) & 7" in glue and "RCC_GetClocksFreq" in glue and "spiSetDivisor(spiInst, RXDIAG_SPI_DIVISOR)" in glue else bad)("glue: spi_hz from actual CR1.BR and PCLK; divisor set via spiSetDivisor")

print("\n".join("PASS " + p for p in passes))
if fails:
    print("\n".join("FAIL " + f for f in fails)); print(f"check_source: {len(fails)} FAIL"); sys.exit(1)
print("check_source: ALL PASS"); 
