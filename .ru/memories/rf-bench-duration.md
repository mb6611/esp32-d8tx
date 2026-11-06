---
name: rf-bench-duration
description: Read before planning or running RF TX bench tests for this project; prior 444 µs duration was experiment-specific, not a standing limit.
load: description
---
The user clarified that the 444 µs keyed-burst rule was an arbitrary rule for an earlier experiment, **not a standing limit**. Do not impose it on new D8 packet or hopping tests: those necessarily require longer transmissions. Define the duration and safeguards that the *new experiment* actually needs, and keep the user's preference for separate test-gate approval rather than treating the old cap as binding.

**Why:** On 2026-11-06 the user rejected applying the earlier bench rule to packet-length tests.
**How to apply:** Historical results may describe the old 444 µs envelope, but a new test proposal should specify its own bounded envelope appropriate to the measurement.
