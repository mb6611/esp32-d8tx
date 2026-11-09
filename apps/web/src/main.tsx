import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@d8tx/ui/index.css'
import { App, ErrorBoundary } from '@d8tx/ui'

const createWorker = () => new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App createWorker={createWorker} />
    </ErrorBoundary>
  </StrictMode>,
)
