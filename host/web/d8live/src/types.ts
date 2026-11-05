// Messages from the d8live backend (host/esp32sdr/d8_live.py), WebSocket /ws.
export interface PacketMsg {
  type: "packet"; t: number; tx_id: [number, number]; counter: number;
  ch: number[]; raw: number[]; crc_ok: boolean; cfo: number; mode: string; latency_ms: number;
}

export interface FollowStats {
  hops: number; ok_locked: number; slot_pct: number; losses: number; reacq_s: number[];
  first_lock_s: number | null; schedules: number; slot_mismatch: number; counter_mismatch: number;
}

export interface StatsMsg {
  type: "stats"; uptime: number; packets_per_s: number; crc_rate: number | null; n_ok: number; n_all: number;
  mode: string; period_ms: number; decode_frac: number; latency_ms: number | null; frames: number;
  samples: number; lost_samples: number; loss_frac: number; bad_crc: number; short_frames: number;
  center_mhz: number; gain: number | string; gain_index: number | null;
  follow?: FollowStats;
}
