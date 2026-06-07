import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ActivePlayerIndicator } from './ActivePlayerIndicator'

const navigatorState = vi.hoisted(() => ({
  value: {
    apiBaseUrl: 'http://api.local',
    connectionStatus: 'connected',
    adminToken: null as string | null,
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

  it('opens and stops a SCRY observer socket for admins', async () => {
    navigatorState.value = {
      apiBaseUrl: 'http://api.local',
      connectionStatus: 'connected',
      adminToken: 'admin-session-token',
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

    render(<ActivePlayerIndicator />)

    fireEvent.click(await screen.findByRole('button', { name: /active players: 1/i }))
    fireEvent.click(screen.getByRole('button', { name: /start scry for hero/i }))

    const socket = await waitFor(() => MockWebSocket.instances[0])
    expect(socket.url).toBe('ws://ws.local/admin/scry/hero?token=admin-session-token')
    expect(await screen.findByText(/SCRY active: Hero/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /stop/i }))
    expect(socket.readyState).toBe(3)
  })
})
