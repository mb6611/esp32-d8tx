// The subset of Vite's import.meta.env this package reads (apps/web gets the full types from vite/client).
interface ImportMetaEnv {
  readonly DEV: boolean
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
