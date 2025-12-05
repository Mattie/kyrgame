import { afterEach, describe, expect, it, vi } from 'vitest'

const setLocation = (url: string) => {
  Object.defineProperty(window, 'location', {
    value: new URL(url),
    writable: true,
  })
}

afterEach(() => {
  vi.resetModules()
  vi.unstubAllEnvs()
})

describe('getApiBaseUrl', () => {
  it('prefers explicit environment override', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.override/')
    const { getApiBaseUrl } = await import('./endpoints')

    expect(getApiBaseUrl()).toBe('http://api.override')
  })

  it('falls back to the backend dev port when running on the Vite host', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    setLocation('http://127.0.0.1:5173')
    const { getApiBaseUrl } = await import('./endpoints')

    expect(getApiBaseUrl()).toBe('http://127.0.0.1:8000')
  })
})
