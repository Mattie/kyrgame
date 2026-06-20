import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ActivePlayerIndicator } from './ActivePlayerIndicator'

const navigatorState = vi.hoisted(() => ({
  value: {
    apiBaseUrl: 'http://api.local',
    connectionStatus: 'connected',
    adminToken: null as string | null,
    session: null as { playerId: string; sessionKind?: 'game' | 'admin' } | null,
    scrySession: null as
      | {
          targetPlayerId: string
          displayName: string
          status: 'connecting' | 'active' | 'closed' | 'error'
          eventCount: number
        }
      | null,
    startScry: vi.fn(() => {}),
    stopScry: vi.fn(() => {}),
    logoutSession: vi.fn(async () => {}),
  },
}))

vi.mock('../config/endpoints', () => ({
  getWebSocketUrl: () => 'ws://ws.local',
}))

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => navigatorState.value,
}))

class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = 1
      this.onopen?.()
    }, 0)
  }

  close() {
    this.readyState = 3
    this.onclose?.()
  }

  triggerMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
})

describe('ActivePlayerIndicator', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    navigatorState.value = {
      apiBaseUrl: 'http://api.local',
      connectionStatus: 'connected',
      adminToken: null,
      session: null,
      scrySession: null,
      startScry: vi.fn(() => {}),
      stopScry: vi.fn(() => {}),
      logoutSession: vi.fn(async () => {}),
    }
    MockWebSocket.instances.length = 0
  })

  it('aborts pending active-player refreshes when unmounted', async () => {
    const signals: Array<AbortSignal | undefined> = []
    vi.spyOn(global, 'fetch').mockImplementation((_input, init) => {
      signals.push(init?.signal as AbortSignal | undefined)
      return new Promise<Response>(() => {})
    })

    const { unmount } = render(<ActivePlayerIndicator />)

    await waitFor(() => expect(signals).toHaveLength(2))

    unmount()

    expect(signals.every((signal) => signal?.aborted)).toBe(true)
  })

  it('marks connection durations with a machine-readable duration', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        active: [
          {
            player_id: 'hero',
            display_name: 'Hero',
            level: 12,
            rank_title: 'Wizard',
            active: true,
            connection_duration_seconds: 135,
          },
        ],
      }),
    } as unknown as Response)

    render(<ActivePlayerIndicator />)

    const trigger = await screen.findByRole('button', { name: /active players: 1/i })
    fireEvent.click(trigger)

    expect(screen.getByText('2m 15s').closest('time')).toHaveAttribute('dateTime', 'PT2M15S')
  })

  it('logs out the active game session from the active-player popover', async () => {
    const logoutSession = vi.fn(async () => {})
    navigatorState.value = {
      apiBaseUrl: 'http://api.local',
      connectionStatus: 'connected',
      adminToken: null,
      session: { playerId: 'Hero', sessionKind: 'game' },
      scrySession: null,
      startScry: vi.fn(() => {}),
      stopScry: vi.fn(() => {}),
      logoutSession,
    }
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ active: [] }),
    } as unknown as Response)

    render(<ActivePlayerIndicator />)

    fireEvent.click(await screen.findByRole('button', { name: /active players: 0/i }))
    fireEvent.click(screen.getByRole('button', { name: /log out hero/i }))

    await waitFor(() => expect(logoutSession).toHaveBeenCalledTimes(1))
  })

  it('starts and stops SCRY through navigator state for admins', async () => {
    const startScry = vi.fn()
    const stopScry = vi.fn(() => {})
    navigatorState.value = {
      apiBaseUrl: 'http://api.local',
      connectionStatus: 'connected',
      adminToken: 'admin-session-token',
      session: null,
      scrySession: null,
      startScry,
      stopScry,
      logoutSession: vi.fn(async () => {}),
    }
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        active: [
          {
            player_id: 'hero',
            display_name: 'Hero',
            level: 12,
            rank_title: 'Wizard',
            active: true,
            connection_duration_seconds: 10,
          },
        ],
      }),
    } as unknown as Response)

    const { rerender } = render(<ActivePlayerIndicator />)

    fireEvent.click(await screen.findByRole('button', { name: /active players: 1/i }))
    fireEvent.click(screen.getByRole('button', { name: /start scry for hero/i }))

    expect(startScry).toHaveBeenCalledWith(
      expect.objectContaining({ player_id: 'hero', display_name: 'Hero' })
    )
    expect(MockWebSocket.instances).toHaveLength(0)

    navigatorState.value = {
      ...navigatorState.value,
      scrySession: {
        targetPlayerId: 'hero',
        displayName: 'Hero',
        status: 'active',
        eventCount: 2,
      },
    }
    rerender(<ActivePlayerIndicator />)
    expect(await screen.findByText(/SCRY active: Hero \(2\)/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /stop/i }))
    expect(stopScry).toHaveBeenCalledTimes(1)
  })
})
