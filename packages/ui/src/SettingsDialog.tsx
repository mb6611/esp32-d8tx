// Settings as a modal dialog (closes on the X, Esc or a click outside): Radio, Sticks and Identity. Bind is in Pairing.
import { useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './components/ui/dialog'
import { Tip } from './components/ui/tooltip'
import type { EspStatus, StartOptions } from './types'

function Section({ title, tip, note, children }: { title: string; tip?: string; note?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-t border-line pt-2.5 pb-3 first-of-type:border-t-0 first-of-type:pt-0 last-of-type:pb-0">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="m-0 font-sans text-[11px] font-semibold tracking-wider text-muted uppercase">{tip ? <Tip tip={tip}>{title}</Tip> : title}</h3>
        {note && <span className="text-[11px] text-muted">{note}</span>}
      </div>
      {children}
    </section>
  )
}

function Field({ label, tip, children }: { label: string; tip: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      <Tip tip={tip} className="self-start">{label}</Tip>
      {children}
    </label>
  )
}

function IdentityBody({ esp, armed, onNewId }: { esp?: EspStatus; armed: boolean; onNewId: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const running = esp?.bind_state === 'binding' || esp?.bind_state === 'confirming'
  // the worker pauses the link for it and restarts it afterwards; never while armed
  const idle = !!esp?.connected && !armed && !running && !esp?.binding
  return (
    <div className="text-xs">
      <div className="flex items-center justify-between gap-3">
        <span className="text-muted">
          <Tip tip="This ESP32's own transmitter ID (4 hex digits), stored in its flash.">Transmitter ID</Tip>{' '}
          <span className="ml-1 font-mono text-sm text-fg">{esp?.txid ?? '–'}</span>
        </span>
        {!confirm && (
          <button className="btn !py-0.5 text-muted" disabled={!idle} onClick={() => setConfirm(true)}>
            <Tip tip="Generates a new random transmitter ID and hop table. The radio link pauses for it. Drones bound to the old identity stop responding until they bind again.">New identity…</Tip>
          </button>
        )}
      </div>
      {confirm && (
        <div role="alertdialog" className="mt-2 border border-warn bg-warn/10 p-2">
          <p className="m-0 mb-2 text-warn">Generate a new identity? Every drone bound to this ESP32 must be bound again.</p>
          <div className="flex justify-end gap-2">
            <button className="btn !py-0.5" onClick={() => setConfirm(false)} autoFocus>Cancel</button>
            <button
              className="btn !border-bad !py-0.5 text-bad"
              disabled={!idle}
              onClick={() => {
                setConfirm(false)
                onNewId()
              }}
            >Generate new identity</button>
          </div>
        </div>
      )}
    </div>
  )
}

export interface SettingsDialogProps {
  open: boolean
  onOpenChange(v: boolean): void
  opts: StartOptions
  setOpts(o: StartOptions): void
  maxThr: number
  setMaxThr(v: number): void
  esp?: EspStatus
  armed: boolean
  onNewId(): void
}

export default function SettingsDialog(s: SettingsDialogProps) {
  const num = (k: keyof StartOptions) => (e: React.ChangeEvent<HTMLInputElement>) => s.setOpts({ ...s.opts, [k]: Number(e.target.value) })
  return (
    <Dialog open={s.open} onOpenChange={s.onOpenChange}>
      {/* focus the dialog itself on open: the first focusable is a tooltip label, whose tip would cover the header */}
      <DialogContent onOpenAutoFocus={(e) => { e.preventDefault(); (e.currentTarget as HTMLElement | null)?.focus() }}>
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>Saved in this browser. Changing a radio setting restarts the link (about a second).</DialogDescription>
        </DialogHeader>
        <Section title="Radio" note={s.armed ? 'locked while armed' : undefined}>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Power (0–127)" tip="ESP32 transmit power setting for the D8 packets."><input type="number" min={0} max={127} value={s.opts.power} onChange={num('power')} disabled={s.armed} /></Field>
            <Field label="FOFS, Hz" tip="Frequency offset added to every channel, to match the drone receiver's tuning. Bind (in Pairing) uses it too, so links and binds must agree."><input type="number" min={-200000} max={200000} step={1000} value={s.opts.fofs_hz} onChange={num('fofs_hz')} disabled={s.armed} /></Field>
            <Field label="Timeout, ms" tip="The ESP32 stops transmitting when no stick frame arrives from this computer for this long."><input type="number" min={50} max={2000} step={50} value={s.opts.timeout_ms} onChange={num('timeout_ms')} disabled={s.armed} /></Field>
          </div>
        </Section>
        <Section title="Sticks">
          <div className="grid grid-cols-3 gap-3">
            <Field label="Max throttle, %" tip="Caps the throttle stick (keys and mouse). Applies immediately."><input type="number" min={0} max={100} value={s.maxThr} onChange={(e) => s.setMaxThr(Number(e.target.value))} /></Field>
          </div>
        </Section>
        <Section title="Identity">
          <IdentityBody esp={s.esp} armed={s.armed} onNewId={s.onNewId} />
        </Section>
      </DialogContent>
    </Dialog>
  )
}
