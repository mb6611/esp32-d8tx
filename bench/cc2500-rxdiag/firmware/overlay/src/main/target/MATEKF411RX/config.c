/*
 * MATEKF411RXDIAG target configuration (receive-only CC2500 diagnostic).
 * Whole file is guarded: every *.c in the target directory is compiled for every variant.
 */

#include <stdbool.h>
#include <stdint.h>

#include "platform.h"

#if defined(MATEKF411RXDIAG)

#include "config/config.h"
#include "config/feature.h"

#include "drivers/io.h"
#include "drivers/motor.h"
#include "drivers/resource.h"

#include "io/beeper.h"

#include "pg/beeper.h"
#include "pg/motor.h"
#include "pg/rx_spi_cc2500.h"

#ifdef USE_TARGET_CONFIG
void targetValidateConfiguration(void)
{
    motorConfigMutable()->dev.motorPwmProtocol = PWM_TYPE_DISABLED;
    motorConfigMutable()->dev.useDshotTelemetry = false;

    featureConfigClear(FEATURE_RX_SPI);
    featureConfigClear(FEATURE_TELEMETRY);
    featureConfigClear(FEATURE_OSD);
    featureConfigClear(FEATURE_LED_STRIP);
    featureConfigClear(FEATURE_SOFTSERIAL);
    featureConfigClear(FEATURE_ESC_SENSOR);
    featureConfigClear(FEATURE_DASHBOARD);
    featureConfigClear(FEATURE_RX_PPM);
    featureConfigClear(FEATURE_RX_SERIAL);
    featureConfigClear(FEATURE_RX_PARALLEL_PWM);
    featureConfigSet(FEATURE_RX_MSP);

    beeperConfigMutable()->beeper_off_flags = BEEPER_ALLOWED_MODES;
}

void targetConfiguration(void)
{
    targetValidateConfiguration();
}
#endif

#ifdef TARGET_PREINIT
// Drive the PA/LNA/diversity pins to a known receive-only state before anything else:
// TX_EN low, LNA_EN low, ANT_SEL high. TX_EN is never driven high anywhere in this build.
static void rxdiagPinOut(ioTag_t tag, resourceOwner_e owner, bool high)
{
    if (!tag) {
        return;
    }
    IO_t io = IOGetByTag(tag);
    if (!io) {
        return;
    }
    IOInit(io, owner, 0);
    IOConfigGPIO(io, IOCFG_OUT_PP);
    if (high) {
        IOHi(io);
    } else {
        IOLo(io);
    }
}

void targetPreInit(void)
{
    rxdiagPinOut(rxCc2500SpiConfig()->txEnIoTag, OWNER_RX_SPI_CC2500_TX_EN, false);
    rxdiagPinOut(rxCc2500SpiConfig()->lnaEnIoTag, OWNER_RX_SPI_CC2500_LNA_EN, false);
    rxdiagPinOut(rxCc2500SpiConfig()->antSelIoTag, OWNER_RX_SPI_CC2500_ANT_SEL, true);
}
#endif

#endif // MATEKF411RXDIAG
