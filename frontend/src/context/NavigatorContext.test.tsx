import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import { NavigatorProvider, useNavigator } from './NavigatorContext'

vi.mock('../config/endpoints', () => ({
  getApiBaseUrl: () => 'http://api.local',
  getWebSocketUrl: () => 'ws://ws.local',
}))

class MockWebSocket {
  static CLOSED = 3
  static instances: MockWebSocket[] = []
  url: string
  sent: string[] = []
  readyState = 0
  onmessage: ((event: { data: string }) => void) | null = null
  onopen: (() => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = 1
      this.onopen?.()
    }, 0)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close(code = 1000, reason = '') {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.({ code, reason })
  }

  triggerMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
})

const TestHarness = () => {
  const navigator = useNavigator()

  return (
    <div>
      <output data-testid="room">{navigator.currentRoom ?? 'none'}</output>
      <output data-testid="admin-token">{navigator.adminToken ?? 'none'}</output>
      <output data-testid="activity">
        {navigator.activity.map((entry) => entry.summary).join('\n')}
      </output>
      <button
        type="button"
        onClick={() => void navigator.startSession('Opal', 7)}
      >
        Start game
      </button>
      <button type="button" onClick={() => navigator.setAdminToken('admin-token')}>
        Set admin
      </button>
      <button
        type="button"
        onClick={() =>
          navigator.startScry({
            player_id: 'hero',
            display_name: 'Hero',
            active: true,
          })
        }
      >
        Start SCRY
      </button>
    </div>
  )
}

describe('NavigatorContext SCRY state handling', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    MockWebSocket.instances.length = 0
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/auth/session')) {
          expect(JSON.parse(String(init?.body))).toMatchObject({
            player_id: 'Opal',
            room_id: 7,
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'created',
              session: {
                token: 'game-token',
                player_id: 'Opal',
                room_id: 7,
                session_kind: 'game',
              },
            }),
          } as unknown as Response)
        }
        if (url.endsWith('/world/locations')) {
          return Promise.resolve({
            ok: true,
            json: async () => [
              { id: 7, brfdes: 'Temple threshold', objects: [] },
              { id: 8, brfdes: 'Observed clearing', objects: [] },
            ],
          } as unknown as Response)
        }
        if (url.endsWith('/objects')) {
          return Promise.resolve({
            ok: true,
            json: async () => [],
          } as unknown as Response)
        }
        if (url.endsWith('/commands')) {
          return Promise.resolve({
            ok: true,
            json: async () => [],
          } as unknown as Response)
        }
        if (url.endsWith('/i18n/en-US/messages')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ messages: {} }),
          } as unknown as Response)
        }
        throw new Error(`Unexpected fetch call: ${url}`)
      }
    )
  })

  it('renders SCRY output without moving the active game room', async () => {
    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    await screen.findByText('7')
    await waitFor(() =>
      expect(
        MockWebSocket.instances.some((socket) => socket.url === 'ws://ws.local/rooms/7?token=game-token')
      ).toBe(true)
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /set admin/i }))
    })
    await screen.findByText('admin-token')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start scry/i }))
    })

    const scrySocket = await waitFor(() => {
      const socket = MockWebSocket.instances.find((entry) =>
        entry.url.includes('/admin/scry/hero')
      )
      expect(socket).toBeTruthy()
      return socket as MockWebSocket
    })

    act(() => {
      scrySocket.triggerMessage({
        type: 'scry_started',
        player_id: 'Hero',
        display_name: 'Hero',
        room: 8,
      })
      scrySocket.triggerMessage({
        type: 'scry_event',
        player_id: 'Hero',
        event: {
          event_type: 'output',
          payload: {
            type: 'command_response',
            room: 8,
            payload: {
              event: 'location_update',
              location: 8,
            },
          },
        },
      })
      scrySocket.triggerMessage({
        type: 'scry_event',
        player_id: 'Hero',
        event: {
          event_type: 'output',
          payload: {
            type: 'command_response',
            room: 8,
            payload: {
              event: 'location_description',
              location: 8,
              text: 'Scry room only.',
              objects: [],
            },
          },
        },
      })
    })

    await waitFor(() =>
      expect(screen.getByTestId('activity')).toHaveTextContent('Scry room only.')
    )
    expect(screen.getByTestId('room')).toHaveTextContent('7')
  })
})
