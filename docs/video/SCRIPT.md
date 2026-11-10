# Narration script (approved draft, Nov 2026)

Owner-approved wording. Spoken text may be split across animation beats, but keep the words. Numbers to be spelled for TTS where needed (e.g. "6BD" -> "six B D", "CC2500" -> "C C twenty-five hundred", "kHz" -> "kilohertz", "µs" -> "microseconds", "ESP32" -> "E S P thirty-two", "SPI" -> "S P I").

## S01 · the app

This is the browser app we fly the drone with. Everything the pilot can control is a channel, and there are eight of them. Four come from the sticks: throttle, yaw, pitch and roll. Move the sticks and all four change at once.

Let's follow just one of them, the throttle, from the key press all the way to the motors.

## S02 · into a packet

Pressing W raises the throttle to 1150. That's measured in microseconds, on a scale where 1000 is off and 2000 is full power, so 1150 is a gentle 15 %.

About every 9 ms the browser sends the current value of all eight channels down the USB cable to the ESP32. The ESP32 builds a packet out of them.

First the ESP32 converts each value into the units the radio protocol uses, which is the value times 1.5. So 1150 becomes 1725, and in hex that's 6BD.

The packet is 20 bytes. It starts with a length byte. Then come the transmitter's ID, so the drone only listens to its own transmitter, and a counter that numbers the packets. Then the eight channel values, and finally a two-byte checksum. The checksum lets the receiver check that nothing got corrupted in the air.

Each channel value needs 12 bits, which is a byte and a half. Rather than spend two full bytes on each one, the ESP32 splits the value. The low 8 bits, BD, get a byte of their own. The top 4 bits, the 6, share a byte with the top 4 bits of the next channel. Packed like that, eight channels fit in 12 bytes instead of 16.

Written out, the whole packet is 160 ones and zeros.

## S03 · bits onto a carrier

Now we need to get those bits into the air. Each radio channel has a carrier, a steady wave at one frequency around 2.4 GHz. To send a 1 we nudge the carrier up by 39 kHz, and to send a 0 we nudge it down by 39 kHz. That's 1 part in 60,000, so the picture exaggerates it a lot.

The ESP32's processor can't make a 2.4 GHz wave itself. Its Wi-Fi radio can, though. A synthesizer inside it makes the carrier. The radio also has a built-in tone generator, meant for testing, and that tone gets mixed onto the carrier. We key that tone up and down, one bit every 32 µs.

On another channel the carrier sits at a different frequency, so the wave is different. It still carries the same bits.

So one packet is one short burst of this wave on one channel.

## S04 · hopping

The burst leaves the ESP32's antenna. The next packet doesn't go out on the same channel; it goes out on a different one, about 9 ms later. The transmitter and the drone agreed on the order when they were bound, so both know where the next packet will be and when.

That matters because the drone's radio can only listen to one narrow channel at a time. After every packet it retunes to the next channel on the list, in step with the transmitter.

D8 hops across 47 channels. If one of them is noisy, say a Wi-Fi network sits on top of it, we lose one packet in every 47, and the link carries on.

From the drone's side, this is just a steady stream of packets. One of them is ours, carrying 1150.

## S05 · into the drone

The drone's CC2500 radio catches the burst. It reads the up and down nudges in the wave back as ones and zeros, reassembles the packet, and checks the checksum. Everything checks out.

It passes the packet over SPI, a short wire, to the flight controller running Betaflight. The flight controller unpacks the throttle, 1150, and mixes it into commands for all four motors, along with the corrections that keep the drone level. The motor drivers turn those commands into spin, and the drone lifts.
