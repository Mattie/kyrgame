const readPort = (name: string, fallback: number) => {
  const raw = process.env[name]
  if (!raw) return fallback
  const parsed = Number(raw)
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`)
  }
  return parsed
}

export const e2eHost = process.env.PLAYWRIGHT_HOST ?? '127.0.0.1'
export const backendPort = readPort('PLAYWRIGHT_BACKEND_PORT', 8011)
export const frontendPort = readPort('PLAYWRIGHT_FRONTEND_PORT', 5179)
export const adminToken = process.env.PLAYWRIGHT_ADMIN_TOKEN ?? 'e2e-admin'
export const apiBaseUrl =
  process.env.PLAYWRIGHT_API_BASE_URL ?? `http://${e2eHost}:${backendPort}`
export const wsUrl = process.env.PLAYWRIGHT_WS_URL ?? `ws://${e2eHost}:${backendPort}/ws`
export const frontendBaseUrl =
  process.env.PLAYWRIGHT_FRONTEND_BASE_URL ?? `http://${e2eHost}:${frontendPort}`
