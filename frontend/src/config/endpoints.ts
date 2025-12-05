const trimTrailingSlash = (value: string) => value.replace(/\/$/, '')

export const getApiBaseUrl = (): string => {
  const envValue = (import.meta.env.VITE_API_BASE_URL || '').trim()
  if (envValue) {
    return trimTrailingSlash(envValue)
  }

  const devPorts = new Set(['5173', '4173'])
  if (devPorts.has(window.location.port)) {
    const protocol = window.location.protocol.startsWith('https')
      ? 'https'
      : 'http'
    return `${protocol}://${window.location.hostname}:8000`
  }

  return window.location.origin
}

export const getWebSocketUrl = (): string => {
  const override = (import.meta.env.VITE_WS_URL || '').trim()
  if (override) {
    return trimTrailingSlash(override)
  }

  const apiBase = trimTrailingSlash(getApiBaseUrl())
  const wsUrl = new URL('/ws', apiBase)
  wsUrl.protocol = wsUrl.protocol.replace('http', 'ws')
  return trimTrailingSlash(wsUrl.toString())
}
