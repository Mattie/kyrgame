const trimTrailingSlash = (value: string) => value.replace(/\/$/, '')

export const getApiBaseUrl = (): string => {
  const envValue = (import.meta.env.VITE_API_BASE_URL || '').trim()
  if (envValue) {
    return trimTrailingSlash(envValue)
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
