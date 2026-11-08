import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export interface Att { roll: number; pitch: number; yaw: number | null }

const rad = Math.PI / 180
const wrap = (d: number) => ((((d + 180) % 360) + 360) % 360) - 180

/** Line-drawn quad on a ground grid; rotates with attitude (deg, Betaflight sign convention), eased ~0.3 s. */
export default function Quad3D({ att, dim }: { att: Att; dim: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const target = useRef<Att>(att)
  useEffect(() => {
    const y = att.yaw ?? target.current.yaw // yaw unknown: keep last
    target.current = { ...att, yaw: y }
  }, [att.roll, att.pitch, att.yaw]) // eslint-disable-line react-hooks/exhaustive-deps

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
    for (const [x, z] of [[s, -s], [-s, -s], [s, s], [-s, s]]) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.12, 12), new THREE.MeshBasicMaterial({ color: ink }))
      c.position.set(x * 0.9, 0.06, z * 0.9)
      const prop = new THREE.Mesh(new THREE.RingGeometry(0.4, 0.43, 28), new THREE.MeshBasicMaterial({ color: grey, side: THREE.DoubleSide }))
      prop.rotation.x = -Math.PI / 2
      prop.position.set(x * 0.9, 0.14, z * 0.9)
      quad.add(c, prop)
    }
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.12, 0.7), new THREE.MeshBasicMaterial({ color: grey }))
    quad.add(body)
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.4, 3), new THREE.MeshBasicMaterial({ color: red }))
    nose.rotation.x = -Math.PI / 2 // tip toward -z (front)
    nose.position.set(0, 0.02, -0.6)
    quad.add(nose)
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
    let last = performance.now(), raf = 0
    const loop = (t: number) => {
      const k = 1 - Math.exp(-(t - last) / 100) // ~0.3 s to settle
      last = t
      const g = target.current
      cur.roll += (g.roll - cur.roll) * k
      cur.pitch += (g.pitch - cur.pitch) * k
      cur.yaw += wrap((g.yaw ?? 0) - cur.yaw) * k
      quad.rotation.set(cur.pitch * rad, -cur.yaw * rad, -cur.roll * rad, 'YXZ')
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

  return <div ref={host} className={`aspect-square w-full ${dim ? 'opacity-40' : ''}`} />
}
