# Narration script

The approved narration, about 1,400 spoken words, split into the eleven scene files of STORYBOARD.md: every sentence below belongs to exactly one scene. It tells the earlier, longer version in about a fifth fewer words, with six claims corrected: the Wi-Fi loss, where "1 part in 60,000" applies, the width of the ESP32's signal, the source of the E8's glide, the USB bridge chip, and what binding shares. The terms are used consistently: "control channel" is a number the pilot sets, "radio channel" is a band of frequencies, "transmitter" is the handheld (or the ESP32 in its place), "radio" is a radio chip.

On screen, not spoken: the demo address `d8tx.mb6611.workers.dev` in S01, and `github.com/mb6611/esp32-d8tx` at the end of the recap.

## S00 · introduction

This drone is a Tinyhawk 3. It is normally flown with a handheld transmitter, the E8.

The two talk by radio in a protocol called FrSky D8. A protocol is an agreed format for messages. In D8 each message is a short packet, a few bytes carrying the stick positions, sent at about 2.4 GHz, the band Wi-Fi uses.

I wanted to fly the drone from my computer, without an extra radio module made for D8. What I had was an ESP32, a small board with a Wi-Fi radio, so I hacked that radio to speak D8.

That makes the ESP32 a pseudo software-defined radio, or SDR: a radio where software decides what wave goes out. This one is only partly that, as we'll see.

We'll follow one key press all the way to the motors: through a browser, a USB cable, the ESP32, the air, and the drone.

## S01 · the app

This is the browser app that flies the drone; you can try it at the address on screen. Everything the pilot controls is a number, called a control channel. There are eight: throttle, yaw, pitch and roll from the two sticks, and four auxiliary ones, such as the arm switch. Moving the sticks changes all four stick channels at once.

Let's follow the throttle.

## S02a · the number and the wire

Pressing W raises the throttle to 1150. That's in microseconds, a convention from servo control pulses: 1000 is off and 2000 is full power. So 1150 is a gentle 15 %.

D8 sends one packet about every 9 ms, a bit over a hundred a second. The ESP32 keeps that pace, and the browser sends it all eight values just as often, down the USB cable.

On the board, a small chip turns USB into a serial connection called UART: bits on a wire, one after another, at a speed both ends have agreed on.

The ESP32 builds a D8 packet from the values.

## S02b · into the packet

D8 counts in smaller ticks, one and a half to a microsecond, so each value is multiplied by 1.5, and 1150 becomes 1725: the same throttle in a smaller unit. In hex that is 6BD: three hex digits, which is 12 bits.

A D8 packet is 20 bytes. A length byte. The transmitter's two-byte ID, so the drone only listens to its own transmitter. Three bookkeeping bytes, one of them a counter that numbers the packets. The eight control channel values, in 12 bytes. And a two-byte checksum, so the receiver can check that nothing got corrupted in the air.

Twelve bits is a byte and a half, so D8 splits each value. The low 8 bits, BD, get a byte of their own. The top 4 bits, the 6, share a byte with the top 4 of the next channel. So eight channels fit in 12 bytes instead of 16.

Written out, the 20 bytes are 160 ones and zeros.

## S03a · carrier and 2-FSK

Now those bits have to get into the air. A radio signal is built around a carrier: a steady wave at one frequency, here about 2.4 GHz, or 2.4 billion swings a second.

D8 sends bits by shifting that frequency: a little up for a 1, a little down for a 0, each bit in its own slot of time. This is frequency-shift keying, or FSK; with two frequencies, 2-FSK. The real shift is far too small to see, so the picture exaggerates it.

## S03b · how the E8 does it

The E8 has a radio chip built for FSK. It hands the chip the packet's bytes, and for each bit the chip moves the frequency about 32 kHz up or down. Each bit lasts 32 µs, about 31,000 bits a second.

With D8's settings, the chip doesn't jump between the two frequencies. It glides. The smoothing has a bell-curve shape, a Gaussian, so this is Gaussian FSK, or GFSK. Still two frequencies, one bit at a time; only the move between them is smooth.

Why glide? A steady wave sits at exactly one frequency. A sudden change is made of many frequencies at once, and the sharper the change, the wider they spread. Fourier analysis explains why; we won't go into it. So a signal that jumps leaks into neighbouring frequencies, where other radios may be listening. Gliding keeps it narrow.

The smoothing is for the neighbours, not the receiver. The drone can read plain 2-FSK without it.

## S03c · how the ESP32 does it

The ESP32's Wi-Fi radio works in the same band and can tune its carrier where we want. But it is built for Wi-Fi and Bluetooth. Copying the glide would take an arbitrary signal, any wave we choose, which is hard to get out of it.

But it has an undocumented test feature, a test tone: one steady wave at a single frequency, offset from the carrier in steps of about 39 kHz, about 1 part in 60,000 of the carrier.

And D8 doesn't need an arbitrary signal. The receiver only asks whether the frequency is above the centre or below. So two tones are enough: one step above for a 1, one step below for a 0. That's 39 kHz where the E8 uses 32, which makes no difference to that question.

Software switches the radio between the two tones, one bit every 32 µs. Software picks which tone goes out, and when: that is the software-defined part. It has only these tones, not any wave: that is the pseudo part.

So the E8's frequency glides and the ESP32's jumps. The ESP32's signal should be the wider of the two, though I haven't measured it. The drone reads the same bits from both.

In the air, a short fixed pattern goes in front of the packet, so the receiver can find its start. One packet is one short burst of this wave, about 7 ms long.

## S04a · radio channels and hopping

The burst leaves the ESP32's antenna around one carrier frequency. The band is divided into numbered radio channels, 300 kHz apart, each a narrow band of frequencies with a carrier at its centre. On another radio channel the carrier is different, so the wave is different, but it carries the same bits.

D8 doesn't stay on one radio channel. Each packet goes out on a different one, about 9 ms after the last. This is frequency hopping. D8 hops across 47 radio channels, spread over the band.

Hopping protects the link. A Wi-Fi network sits on about a dozen of the 47 radio channels, so packets sent there can interfere with it if both are sent at the same time. The rest get through.

There is a catch. The drone's radio can only listen to one radio channel at a time, the green bar. After every packet it retunes, so it is already waiting when the next packet arrives. The transmitter makes the same move, so both ends are always on the same radio channel.

## S04b · the hop sequence and binding

For that, both need the same list of radio channels in the same order: the hop sequence.

The drone gets it once, in a step called binding. In bind mode it listens on radio channel 0, where the transmitter sends bind packets. They carry the transmitter's ID and the hop sequence, a few entries at a time, and the drone stores both. The ESP32 binds the same way, with its own ID. From then on the drone only listens to that ID, and it knows which radio channel comes next. The timing it takes from the packets themselves.

To the drone, this is a steady stream of packets. One of them is ours, carrying 1150.

## S05 · into the drone

The drone's radio chip, a CC2500, is built for FSK. It catches the burst, reads the shifts back as ones and zeros, reassembles the packet, and checks the checksum. Everything checks out.

It hands the packet to the flight controller, the drone's main computer, over a link on the board called SPI. Like UART, SPI sends bits over wires, but an extra wire carries a clock that says when to read each bit.

The flight controller runs firmware called Betaflight. It unpacks the throttle, 1150 again, and mixes it into commands for the four motors, along with the corrections that keep the drone level. The motor drivers turn those into spin, and the drone lifts.

## S06 · recap

To recap: a key press becomes a number in the browser, then bytes in a D8 packet, then frequency shifts, sent by a Wi-Fi radio switching between two test tones. The drone's receiver reads the packet and acts on it.
