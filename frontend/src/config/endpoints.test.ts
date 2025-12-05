import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { getApiBaseUrl, getWebSocketUrl } from './endpoints'

describe('endpoints configuration', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    vi.stubEnv('VITE_WS_URL', '')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('prefers VITE_API_BASE_URL when provided', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')

    expect(getApiBaseUrl()).toBe('https://api.example.com')
  })

  it('removes trailing slashes from VITE_API_BASE_URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/')

    expect(getApiBaseUrl()).toBe('https://api.example.com')
  })

  it('falls back to window location when API base env is missing', () => {
    vi.unstubAllEnvs()

    expect(getApiBaseUrl()).toBe(window.location.origin)
  })

  it('uses VITE_WS_URL when defined', () => {
    vi.stubEnv('VITE_WS_URL', 'wss://ws.example.com/rooms')

    expect(getWebSocketUrl()).toBe('wss://ws.example.com/rooms')
  })

  it('removes trailing slashes from VITE_WS_URL', () => {
    vi.stubEnv('VITE_WS_URL', 'wss://ws.example.com/')

    expect(getWebSocketUrl()).toBe('wss://ws.example.com')
  })

  it('builds websocket url from the API base when no override is set', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')

    expect(getWebSocketUrl()).toBe('wss://api.example.com/ws')
  })
})
