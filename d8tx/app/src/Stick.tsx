import { useRef } from 'react'

interface Props {
  label: string
  xLabel: string
  yLabel: string
  x: number // -1..1
  y: number // -1..1, up positive
  yPct?: number // overrides y caption (0..100)
  yUs?: number
  xUs?: number
  accent?: string
  onDrag: (x: number, y: number) => void
  onRelease: () => void
}

const S = 320
const PAD = 26 // room for the trim-style scales around the square
const T = S + PAD * 2

function Ticks({ horizontal, side }: { horizontal: boolean; side: 'a' | 'b' }) {
  const out = []
  for (let i = 0; i <= 20; i++) {
    const p = PAD + (i / 20) * S
    const major = i % 5 === 0
    const mid = i === 10
    const len = mid ? 12 : major ? 8 : 4
    const off = side === 'a' ? PAD - 4 : PAD + S + 4
    const dir = side === 'a' ? -1 : 1
    const stroke = mid ? 'var(--color-fg)' : major ? 'var(--color-muted)' : '#b9b9be'
    out.push(
      horizontal
        ? <line key={i} x1={p} x2={p} y1={off} y2={off + dir * len} stroke={stroke} />
        : <line key={i} y1={p} y2={p} x1={off} x2={off + dir * len} stroke={stroke} />,
    )
  }
  return <>{out}</>
}

export default function Stick({ label, xLabel, yLabel, x, y, yPct, yUs, xUs, accent = 'var(--color-ch1)', onDrag, onRelease }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const active = useRef(false)

  const update = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect()
    const k = T / Math.min(r.width, r.height)
    const nx = (e.clientX - r.left - (r.width - T / k) / 2) * k - PAD
    const ny = (e.clientY - r.top - (r.height - T / k) / 2) * k - PAD
    const cl = (v: number) => Math.max(-1, Math.min(1, v))
    onDrag(cl((nx / S) * 2 - 1), cl(-((ny / S) * 2 - 1)))
  }
  const end = () => {
    active.current = false
    onRelease()
  }
  const cx = PAD + S / 2
  const px = cx + x * (S / 2)
  const py = cx - y * (S / 2)
  const g = 'var(--color-grid)'

  return (
    <figure className="m-0 flex h-full min-h-0 select-none flex-col">
      <div className="mb-0.5 flex shrink-0 items-baseline justify-between font-sans text-[11px] font-semibold tracking-wide text-muted uppercase">
        <span>{label}</span>
        <span className="font-mono font-normal normal-case">{xLabel} / {yLabel}</span>
      </div>
      <svg
        ref={ref}
        viewBox={`0 0 ${T} ${T}`}
        className="block min-h-0 w-full flex-1 cursor-crosshair touch-none"
        onPointerDown={(e) => {
          active.current = true
          e.currentTarget.setPointerCapture(e.pointerId)
          update(e)
        }}
        onPointerMove={(e) => active.current && update(e)}
        onPointerUp={end}
        onPointerCancel={end}
      >
        <rect x={PAD} y={PAD} width={S} height={S} fill="var(--color-paper)" stroke="var(--color-fg)" strokeWidth={1} />
        {[0.25, 0.75].map((f) => (
          <g key={f}>
            <line x1={PAD + f * S} x2={PAD + f * S} y1={PAD} y2={PAD + S} stroke={g} />
            <line y1={PAD + f * S} y2={PAD + f * S} x1={PAD} x2={PAD + S} stroke={g} />
          </g>
        ))}
        <line x1={cx} x2={cx} y1={PAD} y2={PAD + S} stroke="var(--color-line)" />
        <line y1={cx} y2={cx} x1={PAD} x2={PAD + S} stroke="var(--color-line)" />
        {/* centre detent */}
        <circle cx={cx} cy={cx} r={14} fill="none" stroke="var(--color-line)" />
        <circle cx={cx} cy={cx} r={2} fill="var(--color-muted)" />
        <Ticks horizontal side="a" /><Ticks horizontal side="b" />
        <Ticks horizontal={false} side="a" /><Ticks horizontal={false} side="b" />
        {/* position indicators riding on the scales */}
        <path d={`M${px} ${PAD - 16} l-4 -7 h8 z`} fill={accent} />
        <path d={`M${px} ${PAD + S + 16} l-4 7 h8 z`} fill={accent} />
        <path d={`M${PAD - 16} ${py} l-7 -4 v8 z`} fill={accent} />
        <path d={`M${PAD + S + 16} ${py} l7 -4 v8 z`} fill={accent} />
        {/* crosshair to the stick head */}
        <line x1={px} x2={px} y1={PAD} y2={PAD + S} stroke={accent} strokeOpacity={0.35} />
        <line y1={py} y2={py} x1={PAD} x2={PAD + S} stroke={accent} strokeOpacity={0.35} />
        <circle cx={px} cy={py} r={11} fill="var(--color-paper)" stroke={accent} strokeWidth={2} />
        <circle cx={px} cy={py} r={2.5} fill={accent} />
      </svg>
      <div className="mt-0.5 flex shrink-0 justify-between font-mono text-xs tabular-nums">
        <span><span className="font-sans text-muted">{xLabel} </span>{(x * 100).toFixed(0).padStart(4)}%{xUs !== undefined && <span className="text-muted"> {xUs.toFixed(0)}µs</span>}</span>
        <span><span className="font-sans text-muted">{yLabel} </span>{(yPct !== undefined ? yPct : y * 100).toFixed(0).padStart(4)}%{yUs !== undefined && <span className="text-muted"> {yUs.toFixed(0)}µs</span>}</span>
      </div>
    </figure>
  )
}
