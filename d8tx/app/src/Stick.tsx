import { useRef } from 'react'

interface Props {
  label: string
  xLabel: string
  yLabel: string
  x: number // -1..1
  y: number // -1..1, up positive
  yPct?: number // overrides y caption (0..100)
  yUs?: number
  onDrag: (x: number, y: number) => void
  onRelease: () => void
}

const SIZE = 240

export default function Stick({ label, xLabel, yLabel, x, y, yPct, yUs, onDrag, onRelease }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const active = useRef(false)

  const update = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect()
    const nx = ((e.clientX - r.left) / r.width) * 2 - 1
    const ny = -(((e.clientY - r.top) / r.height) * 2 - 1)
    onDrag(Math.max(-1, Math.min(1, nx)), Math.max(-1, Math.min(1, ny)))
  }
  const end = () => {
    active.current = false
    onRelease()
  }
  const c = SIZE / 2
  const r = c - 8

  return (
    <figure>
      <svg
        ref={ref}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="block w-[min(40vw,320px)] min-w-[200px] cursor-crosshair touch-none rounded-md border border-line"
        onPointerDown={(e) => {
          active.current = true
          e.currentTarget.setPointerCapture(e.pointerId)
          update(e)
        }}
        onPointerMove={(e) => active.current && update(e)}
        onPointerUp={end}
        onPointerCancel={end}
      >
        <line x1={c} y1={8} x2={c} y2={SIZE - 8} stroke="var(--color-grid)" />
        <line x1={8} y1={c} x2={SIZE - 8} y2={c} stroke="var(--color-grid)" />
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--color-line)" />
        <circle cx={c} cy={c} r={r / 2} fill="none" stroke="var(--color-grid)" />
        <line x1={c} y1={c} x2={c + x * r} y2={c - y * r} stroke="var(--color-muted)" />
        <circle cx={c + x * r} cy={c - y * r} r={7} fill="var(--color-fg)" />
      </svg>
      <figcaption className="mt-2 font-sans text-[.8rem] leading-snug text-muted">
        {label}: {xLabel} <b className="font-mono font-normal text-fg">{(x * 100).toFixed(0)}%</b>, {yLabel}{' '}
        <b className="font-mono font-normal text-fg">{yPct !== undefined ? yPct.toFixed(0) : (y * 100).toFixed(0)}%</b>
        {yUs !== undefined && <span title="throttle pulse width"> ({yUs.toFixed(0)} µs)</span>}
      </figcaption>
    </figure>
  )
}
