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
      <output data-testid="connection-status">{navigator.connectionStatus}</output>
      <output data-testid="game-session-replaced">
        {navigator.gameSessionReplaced ? 'true' : 'false'}
      </output>
      <output data-testid="latest-level-up-cue">
        {navigator.latestLevelUpCue
          ? `${navigator.latestLevelUpCue.sequence}:${navigator.latestLevelUpCue.level}`
          : 'none'}
      </output>
      <output data-testid="error">{navigator.error ?? 'none'}</output>
      <output data-testid="activity">
        {navigator.activity.map((entry) => entry.summary).join('\n')}
      </output>
      <output data-testid="activity-count">{navigator.activity.length}</output>
      <output data-testid="visible-activity-count">
        {navigator.activity.filter((entry) => !entry.hidden).length}
      </output>
      <output data-testid="hidden-activity-count">
        {navigator.activity.filter((entry) => entry.hidden).length}
      </output>
      <output data-testid="hydrated-activity-count">
        {
          navigator.activity.filter((entry) => entry.meta?.hydratedScrollback === true)
            .length
        }
      </output>
      <output data-testid="first-activity">
        {navigator.activity[0]?.summary ?? 'none'}
      </output>
      <output data-testid="last-activity">
        {navigator.activity[navigator.activity.length - 1]?.summary ?? 'none'}
      </output>
      <output data-testid="first-visible-activity">
        {navigator.activity.find((entry) => !entry.hidden)?.summary ?? 'none'}
      </output>
      <output data-testid="first-hidden-activity">
        {navigator.activity.find((entry) => entry.hidden)?.summary ?? 'none'}
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
    localStorage.clear()
    sessionStorage.clear()
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

  it('clears a stale admin token when starting a new game session', async () => {
    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /set admin/i }))
    })
    expect(screen.getByTestId('admin-token')).toHaveTextContent('admin-token')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    await screen.findByText('7')
    expect(screen.getByTestId('admin-token')).toHaveTextContent('none')
  })

  it('does not auto-reconnect when another tab replaces the game socket', async () => {
    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    const gameSocket = await waitFor(() => {
      const socket = MockWebSocket.instances.find(
        (entry) => entry.url === 'ws://ws.local/rooms/7?token=game-token'
      )
      expect(socket).toBeTruthy()
      return socket as MockWebSocket
    })

    await act(async () => {
      gameSocket.close(1013, 'Game session replaced by another connection')
      await new Promise((resolve) => window.setTimeout(resolve, 320))
    })

    expect(screen.getByTestId('connection-status')).toHaveTextContent('disconnected')
    expect(screen.getByTestId('game-session-replaced')).toHaveTextContent('true')
    expect(screen.getByTestId('error')).toHaveTextContent(
      'This game session is open in another tab or window.'
    )
    expect(
      MockWebSocket.instances.filter(
        (socket) => socket.url === 'ws://ws.local/rooms/7?token=game-token'
      )
    ).toHaveLength(1)
  })

  it('auto-reconnects when a 1013 game socket close is transient', async () => {
    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    const gameSocket = await waitFor(() => {
      const socket = MockWebSocket.instances.find(
        (entry) => entry.url === 'ws://ws.local/rooms/7?token=game-token'
      )
      expect(socket).toBeTruthy()
      return socket as MockWebSocket
    })

    await act(async () => {
      gameSocket.close(1013, 'Server overloaded')
      await new Promise((resolve) => window.setTimeout(resolve, 320))
    })

    expect(
      MockWebSocket.instances.filter(
        (socket) => socket.url === 'ws://ws.local/rooms/7?token=game-token'
      )
    ).toHaveLength(2)
    expect(screen.getByTestId('connection-status')).toHaveTextContent('connected')
    expect(screen.getByTestId('game-session-replaced')).toHaveTextContent('false')
  })

  it('clears level-up cues after the next tick', async () => {
    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    const gameSocket = await waitFor(() => {
      const socket = MockWebSocket.instances.find(
        (entry) => entry.url === 'ws://ws.local/rooms/7?token=game-token'
      )
      expect(socket).toBeTruthy()
      return socket as MockWebSocket
    })

    act(() => {
      gameSocket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          event: 'player_level_up',
          player: 'Opal',
          previous_level: 1,
          level: 2,
          location: 7,
        },
      })
    })

    expect(screen.getByTestId('latest-level-up-cue')).toHaveTextContent('1:2')

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 0))
    })

    expect(screen.getByTestId('latest-level-up-cue')).toHaveTextContent('none')
  })

  it('retains newest visible activity without hidden status entries consuming the budget', async () => {
    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    const gameSocket = await waitFor(() => {
      const socket = MockWebSocket.instances.find(
        (entry) => entry.url === 'ws://ws.local/rooms/7?token=game-token'
      )
      expect(socket).toBeTruthy()
      return socket as MockWebSocket
    })

    act(() => {
      for (let index = 0; index < 520; index += 1) {
        gameSocket.triggerMessage({
          type: 'command_response',
          room: 7,
          payload: {
            event: 'room_message',
            text: `Visible ${index}`,
          },
        })
      }
      for (let index = 0; index < 60; index += 1) {
        gameSocket.triggerMessage({
          type: 'command_response',
          room: 7,
          payload: {
            event: 'room_message',
            text: `Hidden ${index}`,
          },
          meta: { silent: true },
        })
      }
    })

    await waitFor(() =>
      expect(screen.getByTestId('visible-activity-count')).toHaveTextContent('500')
    )
    expect(screen.getByTestId('hidden-activity-count')).toHaveTextContent('50')
    expect(screen.getByTestId('activity-count')).toHaveTextContent('550')
    expect(screen.getByTestId('first-visible-activity')).toHaveTextContent('Visible 20')
    expect(screen.getByTestId('first-hidden-activity')).toHaveTextContent('Hidden 10')
    expect(screen.getByTestId('last-activity')).toHaveTextContent('Hidden 59')
  })

  it('restores capped hydrated scrollback for a remembered session', async () => {
    // Stored hidden entries are defensive read-path coverage; normal writes persist visible scrollback.
    const storedEntries = [
      ...Array.from({ length: 520 }, (_, index) => ({
        id: `stored-${index}`,
        type: 'command_response',
        summary: `Stored ${index}`,
        payload: null,
      })),
      ...Array.from({ length: 60 }, (_, index) => ({
        id: `stored-hidden-${index}`,
        type: 'command_response',
        summary: `Stored hidden ${index}`,
        payload: null,
        hidden: true,
      })),
    ]
    sessionStorage.setItem(
      'kyrgame.navigator.scrollback.v1:game:opal',
      JSON.stringify(storedEntries)
    )

    render(
      <NavigatorProvider>
        <TestHarness />
      </NavigatorProvider>
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /start game/i }))
    })

    await waitFor(() =>
      expect(screen.getByTestId('visible-activity-count')).toHaveTextContent('500')
    )
    expect(screen.getByTestId('hidden-activity-count')).toHaveTextContent('50')
    expect(screen.getByTestId('hydrated-activity-count')).toHaveTextContent('550')
    expect(screen.getByTestId('first-activity')).toHaveTextContent('Stored 20')
    expect(screen.getByTestId('first-hidden-activity')).toHaveTextContent('Stored hidden 10')
    expect(screen.getByTestId('last-activity')).toHaveTextContent('Stored hidden 59')
  })
})
