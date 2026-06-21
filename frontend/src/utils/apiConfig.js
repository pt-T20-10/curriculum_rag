const configuredApiUrl = import.meta.env.VITE_API_URL
const defaultApiUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''

// Development keeps the existing localhost default. Production defaults to
// same-origin behind Caddy, even when VITE_API_URL is not defined at build time.
export const API_BASE_URL = (
  configuredApiUrl ?? defaultApiUrl
).replace(/\/+$/, '')

export function buildBackendUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`
}
