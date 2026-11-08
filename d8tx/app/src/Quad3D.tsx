import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export interface Att { roll: number; pitch: number; yaw: number | null }

const rad = Math.PI / 180
const wrap = (d: number) => ((((d + 180) % 360) + 360) % 360) - 180

/** Line-drawn quad on a ground grid; rotates with attitude (deg, Betaflight sign convention), eased ~0.3 s. */
/** Per-motor speed 0..1 in Betaflight order (1 RR, 2 FR, 3 RL, 4 FL); null = stopped. */
export type Spin = (number | null)[] | null
const REV_S = 25 // visual revs/s at full speed
const SPIN: [number, number, number][] = [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]] // x, z side, dir (+1 = CW from above)

export default function Quad3D({ att, dim, tau = 100, spin = null, src = '' }: { att: Att; dim: boolean; tau?: number; spin?: Spin; src?: string }) {
  const spinRef = useRef<Spin>(spin)
  useEffect(() => { spinRef.current = spin }, [spin])
  const host = useRef<HTMLDivElement>(null)
  const target = useRef<Att>(att)
  // Heading is shown relative to a reference: the first heading received counts as 'forward' (nose away
  // from the viewer). Click the view to make the drone's current heading forward again.
  const yawZero = useRef<number | null>(null)
  const tauRef = useRef(tau)
  useEffect(() => { tauRef.current = tau }, [tau])
  const srcRef = useRef(src)
  useEffect(() => {
    // yaw zero belongs to one attitude source; a different source (radio vs USB MSP) may have another offset or be stale, so re-capture
    if (srcRef.current !== src) { srcRef.current = src; yawZero.current = null }
    if (att.yaw != null && yawZero.current == null) yawZero.current = att.yaw
    const y = att.yaw != null ? att.yaw - (yawZero.current ?? 0) : target.current.yaw // yaw unknown: keep last
    target.current = { ...att, yaw: y }
  }, [att.roll, att.pitch, att.yaw, src]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const el = host.current
    if (!el) return
    let W = el.clientWidth || 150, H = el.clientHeight || 150
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(W, H)
    el.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    const scene = new THREE.Scene()
    const cam = new THREE.PerspectiveCamera(40, W / H, 0.1, 50)
    cam.position.set(0, 3.2, 5.4)
    cam.lookAt(0, 0, 0)
    const ink = 0x1a1a1a, grey = 0xbdbdbd, red = 0xb3261e

    const grid = new THREE.GridHelper(6, 12, grey, grey)
    grid.position.y = -0.9
    scene.add(grid)

    const quad = new THREE.Group()
    const pts: number[] = []
    const s = 1
    for (const [x, z] of [[s, -s], [-s, s]]) pts.push(x * 0.9, 0, z * 0.9, -x * 0.9, 0, -z * 0.9)
    quad.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(pts, 3)), new THREE.LineBasicMaterial({ color: ink })))
    const props: { g: THREE.Group; blades: THREE.Mesh; disc: THREE.Mesh; dir: number }[] = []
    for (const [x, z, dir] of SPIN) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.12, 12), new THREE.MeshBasicMaterial({ color: ink }))
      c.position.set(x * 0.9, 0.06, z * 0.9)
      const col = z < 0 ? red : grey // front props red
      const g = new THREE.Group()
      g.position.set(x * 0.9, 0.15, z * 0.9)
      const bm = new THREE.MeshBasicMaterial({ color: col, side: THREE.DoubleSide, transparent: true })
      const b1 = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.07), bm)
      const b2 = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.07), bm)
      b1.rotation.x = b2.rotation.x = -Math.PI / 2
      b2.rotation.z = Math.PI / 2 // second blade pair crosses the first: 4 blades
      const blades = new THREE.Group() as unknown as THREE.Mesh
      blades.add(b1, b2)
      const disc = new THREE.Mesh(new THREE.CircleGeometry(0.4, 28), new THREE.MeshBasicMaterial({ color: col, side: THREE.DoubleSide, transparent: true, opacity: 0.05, depthWrite: false }))
      disc.rotation.x = -Math.PI / 2
      g.add(disc, blades)
      quad.add(c, g)
      props.push({ g, blades, disc, dir })
    }
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.12, 0.7), new THREE.MeshBasicMaterial({ color: grey }))
    quad.add(body)
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.4, 3), new THREE.MeshBasicMaterial({ color: red }))
    nose.rotation.x = -Math.PI / 2 // tip toward -z (front)
    nose.position.set(0, 0.02, -0.6)
    quad.add(nose)
    // long FRONT arrow so the nose cannot be mistaken for the tail
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.05, -0.3), 1.6, red, 0.35, 0.22)
    quad.add(arrow)
    scene.add(quad)

    const cur = { roll: target.current.roll, pitch: target.current.pitch, yaw: target.current.yaw ?? 0 }
    const ro = new ResizeObserver(() => {
      W = el.clientWidth; H = el.clientHeight
      if (!W || !H) return
      renderer.setSize(W, H)
      cam.aspect = W / H
      cam.updateProjectionMatrix()
    })
    ro.observe(el)
    let last = performance.now(), raf = 0, tPrev = last
    const loop = (t: number) => {
      const k = 1 - Math.exp(-(t - last) / tauRef.current) // ~0.3 s to settle
      last = t
      const g = target.current
      cur.roll += (g.roll - cur.roll) * k
      cur.pitch += (g.pitch - cur.pitch) * k
      const dt = Math.min(0.1, (t - tPrev) / 1000)
      tPrev = t
      props.forEach((p, i) => {
        const f = Math.max(0, Math.min(1, spinRef.current?.[i] ?? 0))
        p.g.rotation.y -= p.dir * f * REV_S * 2 * Math.PI * dt // CW from above = negative about +y
        ;((p.blades.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial).opacity = 1 - 0.75 * f
        ;(p.disc.material as THREE.MeshBasicMaterial).opacity = 0.05 + 0.15 * f
      })
      cur.yaw += wrap((g.yaw ?? 0) - cur.yaw) * k
      quad.rotation.set(-cur.pitch * rad, -cur.yaw * rad, -cur.roll * rad, 'YXZ') // camera is behind the model (nose -z, away from viewer); Betaflight heading grows clockwise, so the nose turns right as yaw grows (bench: 152->268 deg turning right)
      renderer.render(scene, cam)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      scene.traverse((o) => {
        const m = o as THREE.Mesh
        m.geometry?.dispose()
        const mat = m.material as THREE.Material | undefined
        mat?.dispose()
      })
      renderer.dispose()
      el.removeChild(renderer.domElement)
    }
  }, [])

  const zero = () => {
    if (att.yaw == null) return
    yawZero.current = att.yaw
    target.current = { ...target.current, yaw: 0 }
  }
  return (
    <div
      ref={host}
      onClick={zero}
      title="Click to make the drone's current heading 'forward'"
      className={`aspect-square w-full cursor-pointer ${dim ? 'opacity-40' : ''}`}
    />
  )
}
