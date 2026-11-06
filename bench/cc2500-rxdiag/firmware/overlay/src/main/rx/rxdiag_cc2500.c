/*
 * rxdiag glue (MATEKF411RXDIAG). Receive-only: no cc2500* function is referenced here,
 * TX_EN is never driven high, and SPI uses only the three raw rxSpi helpers.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#include "platform.h"

#if defined(USE_RXDIAG_CC2500)

#include "common/utils.h"

#include "drivers/bus_spi.h"
#include "drivers/exti.h"
#include "drivers/nvic.h"
#include "drivers/io.h"
#include "drivers/motor.h"
#include "drivers/rx/rx_spi.h"
#include "drivers/serial.h"
#include "drivers/time.h"

#include "pg/motor.h"
#include "pg/rx_spi.h"
#include "pg/rx_spi_cc2500.h"

#include "sensors/battery.h"

#include "vcpf4/usbd_cdc_vcp.h"

#include "rx/rxdiag_cc2500.h"
#include "rx/rxdiag_core.h"

#ifndef RXDIAG_BUILD_ID
#define RXDIAG_BUILD_ID "00000000"
#endif
#define RXDIAG_BF_REV "948ba63"
// Driver divisor argument. On F411 SPI2/SPI3 sit on APB1 and bus_spi_stdperiph halves the argument,
// so 16 gave BR=/8 = 6.75 MHz measured (over the 6.5 MHz burst limit); 32 gives BR=/16 => ~3.4 MHz (SPI_CLOCK_STANDARD=8 would give 12.5 MHz).
#define RXDIAG_SPI_DIVISOR 32

typedef struct {
    serialPort_t *port;
    IO_t lna;
    IO_t txen;
    IO_t ant;
    IO_t gdo;          // CC2500 GDO0 (rx_spi EXTI pin), input only
    bool antHigh;
} rxdiagCtx_t;

// ---- events: GDO0 both-edge capture. ISR writes head, main loop reads tail (single producer/consumer).
#define EDGE_RING 256u   // power of two
typedef struct { uint32_t t; uint8_t level; } edge_t;
static volatile edge_t edgeRing[EDGE_RING];
static volatile uint32_t edgeHead, edgeTail, edgeSeen, edgeLost;
static volatile bool edgeArmed;
static IO_t edgeIo = IO_NONE;
static extiCallbackRec_t edgeCb;
static bool edgeCfgDone = false;

static void edgeIsr(extiCallbackRec_t *cb)
{
    UNUSED(cb);
    const uint32_t t = (uint32_t)microsISR();
    if (!edgeArmed) {
        return;
    }
    const uint8_t level = IORead(edgeIo) ? 1 : 0;
    edgeSeen++;
    const uint32_t h = edgeHead;
    if (h - edgeTail >= EDGE_RING) {
        edgeLost++;
        return;
    }
    edgeRing[h & (EDGE_RING - 1u)].t = t;
    edgeRing[h & (EDGE_RING - 1u)].level = level;
    edgeHead = h + 1u;
}

static const char *const motorProtoNames[] = {
    "PWM", "ONESHOT125", "ONESHOT42", "MULTISHOT", "BRUSHED",
    "DSHOT150", "DSHOT300", "DSHOT600", "PROSHOT1000", "DISABLED"
};

static bool spiReady = false;
static bool spiOk = false;
static SPI_TypeDef *spiInst = NULL;

static uint8_t hSpiRead(void *ctx, uint8_t header)
{
    (void)ctx;
    return rxSpiReadCommand(header, 0xFF);
}

static void hSpiWrite(void *ctx, uint8_t header, uint8_t data)
{
    (void)ctx;
    rxSpiWriteCommand(header, data);
}

static void hSpiStrobe(void *ctx, uint8_t strobe)
{
    (void)ctx;
    rxSpiWriteByte(strobe);
}

static uint32_t hMicros(void *ctx)
{
    (void)ctx;
    return (uint32_t)micros();
}

static void hDelayUs(void *ctx, uint32_t us)
{
    (void)ctx;
    delayMicroseconds(us);
}

static void hFrontEnd(void *ctx, bool lnaOn)
{
    rxdiagCtx_t *c = (rxdiagCtx_t *)ctx;
    if (c->txen) {
        IOLo(c->txen);          // TX_EN forced low on every call
    }
    if (c->ant) {
        if (c->antHigh) {       // antenna select: fixed per session (events may choose 0)
            IOHi(c->ant);
        } else {
            IOLo(c->ant);
        }
    }
    if (c->lna) {
        if (lnaOn) {
            IOHi(c->lna);
        } else {
            IOLo(c->lna);
        }
    }
}

static uint32_t hRxWaiting(void *ctx)
{
    return serialRxBytesWaiting(((rxdiagCtx_t *)ctx)->port);
}

static void hRxDrain(void *ctx)
{
    serialPort_t *p = ((rxdiagCtx_t *)ctx)->port;
    while (serialRxBytesWaiting(p)) {
        (void)serialRead(p);
    }
}

static bool hUsbConnected(void *ctx)
{
    (void)ctx;
    return usbIsConnected() && usbIsConfigured();
}

static bool hTxTry(void *ctx, const char *buf, uint32_t len)
{
    (void)ctx;
    return CDC_Send_DATA_NB((const uint8_t *)buf, len);
}

static int hGdoRead(void *ctx)
{
    rxdiagCtx_t *c = (rxdiagCtx_t *)ctx;
    return c->gdo ? (IORead(c->gdo) ? 1 : 0) : -1;
}

static bool hEdgeArm(void *ctx, bool on)
{
    rxdiagCtx_t *c = (rxdiagCtx_t *)ctx;
    if (!c->gdo) {
        return false;
    }
    if (!on) {
        edgeArmed = false;
        EXTIEnable(c->gdo, false);
        return true;
    }
    if (!edgeCfgDone) {
        edgeIo = c->gdo;
        EXTIHandlerInit(&edgeCb, edgeIsr);
        EXTIConfig(edgeIo, &edgeCb, NVIC_PRIO_MPU_INT_EXTI, IOCFG_IPD, BETAFLIGHT_EXTI_TRIGGER_BOTH);
        edgeCfgDone = true;
    }
    EXTIEnable(edgeIo, false);
    edgeHead = edgeTail = 0;
    edgeSeen = edgeLost = 0;
    edgeArmed = true;
    EXTIEnable(edgeIo, true);
    return true;
}

static bool hEdgePop(void *ctx, uint32_t *tUs, uint8_t *level)
{
    UNUSED(ctx);
    const uint32_t t = edgeTail;
    if (t == edgeHead) {
        return false;
    }
    *tUs = edgeRing[t & (EDGE_RING - 1u)].t;
    *level = edgeRing[t & (EDGE_RING - 1u)].level;
    edgeTail = t + 1u;
    return true;
}

static void hEdgeCounts(void *ctx, uint32_t *edges, uint32_t *lost)
{
    UNUSED(ctx);
    *edges = edgeSeen;
    *lost = edgeLost;
}

static void hAntSet(void *ctx, bool high)
{
    rxdiagCtx_t *c = (rxdiagCtx_t *)ctx;
    c->antHigh = high;
    if (c->ant) {
        if (high) {
            IOHi(c->ant);
        } else {
            IOLo(c->ant);
        }
    }
}

// Writes "A15" style name into out (cap >= 5); "none" if the tag is empty.
static const char *pinName(ioTag_t tag, char *out)
{
    if (!tag) {
        out[0] = 'n'; out[1] = 'o'; out[2] = 'n'; out[3] = 'e'; out[4] = 0;
        return out;
    }
    unsigned port = DEFIO_TAG_GPIOID(tag);
    unsigned pin = DEFIO_TAG_PIN(tag);
    unsigned i = 0;
    out[i++] = (char)('A' + port);
    if (pin >= 10) {
        out[i++] = (char)('0' + pin / 10);
    }
    out[i++] = (char)('0' + pin % 10);
    out[i] = 0;
    return out;
}

static uint32_t spiActualHz(SPI_TypeDef *inst)
{
    if (!inst) {
        return 0;
    }
    RCC_ClocksTypeDef clocks;
    RCC_GetClocksFreq(&clocks);
    const uint32_t pclk = (inst == SPI2 || inst == SPI3) ? clocks.PCLK1_Frequency : clocks.PCLK2_Frequency;
    const uint32_t br = (inst->CR1 >> 3) & 7;     // actual BR bits in hardware
    return pclk / (2u << br);
}

void rxdiagCliRun(serialPort_t *port, char *cmdline)
{
    static rxdiagCtx_t ctx;
    static char csN[6], extiN[6], txN[6], lnaN[6], antN[6];

    if (!spiReady) {
        spiReady = true;
        spiOk = rxSpiDeviceInit(rxSpiConfig());
        if (spiOk) {
            spiInst = spiInstanceByDevice(SPI_CFG_TO_DEV(rxSpiConfig()->spibus));
            if (spiInst) {
                spiSetDivisor(spiInst, RXDIAG_SPI_DIVISOR);
            }
        }
    }

    ctx.port = port;
    ctx.antHigh = true;   // stock default; events may override for its session
    ctx.gdo = rxSpiConfig()->extiIoTag ? IOGetByTag(rxSpiConfig()->extiIoTag) : IO_NONE;
    if (ctx.gdo && !edgeCfgDone) {
        IOConfigGPIO(ctx.gdo, IOCFG_IPD);   // input only; the MCU never drives GDO0
    }
    ctx.lna = rxCc2500SpiConfig()->lnaEnIoTag ? IOGetByTag(rxCc2500SpiConfig()->lnaEnIoTag) : IO_NONE;
    ctx.txen = rxCc2500SpiConfig()->txEnIoTag ? IOGetByTag(rxCc2500SpiConfig()->txEnIoTag) : IO_NONE;
    ctx.ant = rxCc2500SpiConfig()->antSelIoTag ? IOGetByTag(rxCc2500SpiConfig()->antSelIoTag) : IO_NONE;

    static const rxdiagHal_t hal = {
        .ctx = &ctx,
        .spiRead = hSpiRead, .spiWrite = hSpiWrite, .spiStrobe = hSpiStrobe,
        .micros = hMicros, .delayUs = hDelayUs, .frontEnd = hFrontEnd,
        .rxWaiting = hRxWaiting, .rxDrain = hRxDrain,
        .usbConnected = hUsbConnected, .txTry = hTxTry,
        .gdoRead = hGdoRead, .edgeArm = hEdgeArm, .edgePop = hEdgePop, .edgeCounts = hEdgeCounts,
        .antSet = hAntSet,
    };

    const uint8_t proto = motorConfig()->dev.motorPwmProtocol;
    rxdiagBoard_t board = {
        .fw = RXDIAG_BUILD_ID,
        .bf = RXDIAG_BF_REV,
        .cs = pinName(rxSpiConfig()->csnTag, csN),
        .exti = pinName(rxSpiConfig()->extiIoTag, extiN),
        .txen = pinName(rxCc2500SpiConfig()->txEnIoTag, txN),
        .lna = pinName(rxCc2500SpiConfig()->lnaEnIoTag, lnaN),
        .ant = pinName(rxCc2500SpiConfig()->antSelIoTag, antN),
        .motorProto = (proto < sizeof(motorProtoNames) / sizeof(motorProtoNames[0])) ? motorProtoNames[proto] : "UNKNOWN",
        .spiBus = rxSpiConfig()->spibus,
        .spiDiv = RXDIAG_SPI_DIVISOR,
        .spiHz = spiOk ? spiActualHz(spiInst) : 0,
        .motorDevNull = (motorGetVTable().write == motorWriteNull) && !motorIsEnabled(),
        .vbatCv = (int32_t)getBatteryVoltage(),
    };

    // If the SPI device could not be set up, refuse: motor-state style error without touching the chip.
    if (!spiOk) {
        static const char msg[] = "E,0,ENOCHIP,spi=init\r\n";
        (void)CDC_Send_DATA_NB((const uint8_t *)msg, sizeof(msg) - 1);
        return;
    }

    (void)rxdiagRun(&hal, &board, cmdline ? cmdline : "");
}

#endif // USE_RXDIAG_CC2500
