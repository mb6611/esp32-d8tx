import { Component, type ReactNode } from 'react'

export default class ErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) {
    return { err }
  }
  render() {
    if (!this.state.err) return this.props.children
    return (
      <div className="mx-auto max-w-[900px] p-8 font-sans">
        <h1 className="text-bad text-xl font-bold">UI error</h1>
        <pre className="mt-3 whitespace-pre-wrap text-sm">{String(this.state.err.stack ?? this.state.err)}</pre>
        <button className="btn mt-4" onClick={() => location.reload()}>Reload</button>
      </div>
    )
  }
}
