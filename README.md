# esp32-d8tx

**An ESP32's Wi-Fi radio, hacked to speak FrSky D8. Plug it in, open a tab, fly.**

[Technical writeup](docs/devkitv1/writeup/tx.md) · [Try it](#try-it)

<!-- Add 'Live app' and 'Demo' links here once the controller is deployed. -->

![The d8tx controller: sticks, 3D drone, live telemetry](docs/media/hero.gif)

First takeoff with the ESP32 as the radio:

https://github.com/mb6611/esp32-d8tx/raw/main/docs/devkitv1/writeup/media/esp32-first-takeoff.mp4

> [!CAUTION]
> **Educational and research use; check your local regulations.** Transmitting is regulated. This firmware turns a Wi-Fi/Bluetooth-certified module into an intentional radiator outside its grant. Output power is *estimated* (about -25 dBm peak EIRP, from receiver RSSI), not measured, and harmonics were not measured. You are responsible for compliance where you are. Full text: [REGULATORY.md](REGULATORY.md).

## Why I built this

The motivation behind this was I wanted to fly my drone with my computer with Claude, but didn't have a radio module. I first tried opening up my E8 controller, and then remembered I was a software developer and did not feel in the mood to drive to the electronics store and buy a soldering iron.

So I researched online and found some people had found undocumented capabilities in the ESP32 family of boards that let it act as an SDR ([esp-sdr](https://github.com/ESPARGOS/esp-sdr)). My board wasn't one they had tested, so I tried it myself and got RX working on it ([esp32-devkitv1-sdr](https://github.com/mb6611/esp32-devkitv1-sdr)). My drone (a Tinyhawk 3) listens for FrSky D8: short 2.4 GHz packets carrying the stick positions, normally sent by a radio like the E8, that hop between 47 channels in a fixed order. So after understanding the D8 protocol (you can read more in the [writeup](docs/devkitv1/writeup/tx.md)), I decided to try to actually send commands to my drone over D8.

The problem is that it's hard to get the ESP32's Wi-Fi chip to transmit an arbitrary signal (raw I/Q); it's built to speak Wi-Fi and Bluetooth. But I eventually discovered the existence of its test tones: an undocumented feature that transmits a single pure tone at a chosen offset from the radio's carrier frequency, in steps of about 39 kHz. Other ESP32 transmitter projects like [esp32-iq-tx](https://github.com/whstudio123/esp32-iq-tx) have to disable these three test tones to do non-continuous TX, but I realized I could just use the test tones themselves, if I could tune them to the frequencies I wanted. D8 doesn't need an arbitrary signal: the receiver is entirely frequency-based and uses GFSK, so it might be possible to send commands using 2-FSK (i.e. just a one-bit symbol based on which frequency was transmitted) along the 47 channels used by D8, as long as the hopping schedule was continuous.

![The trick: two tones are the bits, and the packet hops to the next of 47 channels every 9 ms](docs/diagrams/story-trick.svg)

I first began by stealing the Betaflight config from my E8, which it turned out was stored in my drone (these protocols really are not designed to be secure). It contains the radio's ID, the starting channel and the channels it should jump between, so I tuned my ESP32 to a single channel, chosen deterministically from this config, to see if I could get it to work. (Later I got the ESP32 to bind on its own, with its own ID, like any radio.)

![Copying the binding: the E8's ID and hop table, read from the drone, put into the ESP32](docs/diagrams/story-steal.svg)

To test my packets I needed a receiver. Alas, due to my lazy software engineer predicament, I did not want to go out and buy a radio module, since avoiding that was the whole point of this project. So I used the STM board on my Tinyhawk 3, which already has a CC2500 radio, as my receiver: I had to build custom benchmarking firmware that basically just replaced the Betaflight flight controller firmware on it and reported every packet it heard. Once I was able to get this loop closed, I was basically just able to run cycles of tests on my ESP32 firmware until eventually I got a single packet working, and miraculously was able to get it to retune its radio between the 47 channels fast enough to transmit packets with buffer time.

![The test loop: the drone's own flight controller as a test receiver](docs/diagrams/story-testloop.svg)

Then I built a UI for the controller (though any process on my computer could control it), and properly architected it so that it could just be managed from a browser. I'll probably later add this as a CLI / MCP or something of the sort, but this was the hard part.

![The final setup: browser, USB, ESP32, drone](docs/diagrams/story-final.svg)

## How it works, step by step

### 1. Your sticks become a radio packet, every 9 ms

The page reads your keyboard or touch sticks. A Web Worker turns them into a line of text, `S 1500 1500 …`, and sends it to the ESP32 over USB. The ESP32 builds a D8 packet from it and sends it by wiggling its Wi-Fi radio's frequency, on the next of 47 channels each time, the way a real FrSky radio hops. The drone receives it and flies.

<details>
<summary>Show every layer</summary>

![Control path: key press to motor, through the browser, USB, the ESP32 and the drone](docs/diagrams/overview-control.svg)

</details>

### 2. Every 12th packet asks the drone to talk back

That packet is marked as a telemetry request. The drone answers right away, on the next channel, so the ESP32 skips one packet and listens there instead.

![Three slots to scale: the request, the ESP32 listening, the drone's reply](docs/diagrams/timeline.svg)

### 3. The reply is decoded in your browser

The ESP32 records the raw radio signal and streams it to the page. A decoder compiled to WebAssembly turns it back into the drone's message: battery, signal strength and more, shown live.

<details>
<summary>Show every layer</summary>

![Telemetry path: the reply in the air, recorded by the ESP32, decoded in the browser](docs/diagrams/overview-telemetry.svg)

</details>

### Proof: the ESP32 hops like the real radio

The same receiver logged which channel each packet arrived on, for the E8 and for the ESP32. The patterns match, and about 98% of the ESP32's packets arrived.

| Real E8 | ESP32 |
|---|---|
| ![](docs/devkitv1/writeup/img/tx-evidence/hop-e8-map.png) | ![](docs/devkitv1/writeup/img/tx-evidence/hop-esp-runB-map.png) |

How the ESP32 was made to do this, with every measurement, is in the [technical writeup](docs/devkitv1/writeup/tx.md). The code's design is in [ARCHITECTURE.md](ARCHITECTURE.md).

## What I used

| Part | Role |
|---|---|
| **ESP32 DevKit V1** (classic ESP32, CP2102 USB bridge) | The radio. No other RF hardware. |
| **EMAX Tinyhawk III** RTF kit, drone | The aircraft: built-in CC2500 FrSky D8 receiver on a MATEKF411RX-target flight controller, Betaflight 4.2.11 |
| **EMAX E8** radio (in the same kit) | The reference: its packets and hop table are what the ESP32 had to match |
| Mac + Chrome / Electron | Runs the app over Web Serial |

## Try it

Use the hosted app (link coming), or run it locally: `pnpm install && pnpm --filter web dev` and open it in Chrome or Edge (Web Serial). Add `?mock=1` to try it with a simulated ESP32 and drone. Firmware install and bind happen in the same page; step by step in [docs/getting-started.md](docs/getting-started.md).

## Status

Works: control, hopping, bind, telemetry, in-browser flashing, desktop (Electron) build, [validated on the bench](docs/validation/d8tx-web-desktop.md) and flown once (see the video above).

Not yet: range tests, a measured output power, D16 protocol, ESP32-S3/C3, Firefox and Safari (no Web Serial).

## Repo

| Path | What |
|---|---|
| `firmware/` | ESP-IDF firmware `d8tone` for the ESP32 |
| `packages/core`, `packages/serial`, `packages/ui` | link, telemetry, flight-controller client and worker; Web Serial transport; React UI |
| `apps/web`, `apps/desktop` | the web app and the Electron shell |
| `demod/` | C demodulator for D8 telemetry (native and WASM) |
| `protocol/` | [PROTOCOL.md](protocol/PROTOCOL.md), golden vectors, I/Q captures |
| `python/` | reference library (`D8Link`, `BetaflightMSP`) |
| `bench/` | bench runner, decoders, raw results behind the writeup |
| `docs/` | [writeup](docs/devkitv1/writeup/tx.md), [validation](docs/validation/d8tx-web-desktop.md), guides |

See [CONTRIBUTING.md](CONTRIBUTING.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT, see [LICENSE](LICENSE), except `bench/betaflight-patch/` and `bench/cc2500-rxdiag/` (Betaflight derivatives, GPL-3.0-or-later). See [NOTICE.md](NOTICE.md).
