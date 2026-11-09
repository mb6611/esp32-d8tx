/** Injected time source. now() is milliseconds (monotonic). */
export interface Clock {
  now(): number
  setTimeout(fn: () => void, ms: number): unknown
  clearTimeout(h: unknown): void
}

export const realClock: Clock = {
  now: () => performance.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
}

/** Deterministic clock for tests: time moves only through advance(). */
export class FakeClock implements Clock {
  private t = 0
  private seq = 0
  private timers = new Map<number, { at: number; fn: () => void }>()
  now(): number {
    return this.t
  }
  setTimeout(fn: () => void, ms: number): number {
    const id = ++this.seq
    this.timers.set(id, { at: this.t + Math.max(0, ms), fn })
    return id
  }
  clearTimeout(h: unknown): void {
    this.timers.delete(h as number)
  }
  /** Let queued promise continuations run. */
  async flush(): Promise<void> {
    // a macrotask turn drains every pending microtask chain
    const si = (globalThis as { setImmediate?: (f: () => void) => unknown }).setImmediate
    await new Promise<void>((r) => (si ? si(r) : setTimeout(r, 0)))
  }
  /** Move time forward without firing timers: the event loop was blocked (e.g. a long decode). */
  stall(ms: number): void {
    this.t += ms
  }
  /** Advance by ms, firing timers in order and flushing microtasks after each. */
  async advance(ms: number): Promise<void> {
    const end = this.t + ms
    await this.flush()
    for (;;) {
      let best: number | null = null
      for (const [id, tm] of this.timers) if (tm.at <= end && (best === null || tm.at < this.timers.get(best)!.at)) best = id
      if (best === null) break
      const tm = this.timers.get(best)!
      this.timers.delete(best)
      this.t = Math.max(this.t, tm.at)
      tm.fn()
      await this.flush()
    }
    this.t = end
    await this.flush()
  }
}
