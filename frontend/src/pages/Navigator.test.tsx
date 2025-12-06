import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import App from '../App'

vi.mock('../config/endpoints', () => ({
  getApiBaseUrl: () => 'http://api.local',
  getWebSocketUrl: () => 'ws://ws.local',
}))

class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  sent: string[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.onopen?.()
    }, 0)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.onclose?.()
  }

  triggerMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
})

describe('Navigator flow', () => {
  const locations = [
    {
      id: 7,
      brfdes: 'Edge of the forest',
      objlds: 'on the ground',
      objects: [0],
      gi_north: 8,
      gi_south: -1,
      gi_east: -1,
      gi_west: -1,
    },
    {
      id: 8,
      brfdes: 'Deep forest clearing',
      objlds: 'among the trees',
      objects: [],
      gi_north: -1,
      gi_south: 7,
      gi_east: -1,
      gi_west: -1,
    },
  ]

  const objects = [{ id: 0, name: 'ruby' }]

  const commands = [
    { id: 1, command: 'move' },
    { id: 2, command: 'look' },
  ]

  const messages = {
    WELCOME: 'Welcome to Kyrandia!',
    KRD007: 'A long description of the temple.',
    KRD008: 'A long description of the clearing.',
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    MockWebSocket.instances.length = 0
  })

  it('creates a session, caches world data, and streams room activity', async () => {
    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ] as const

    vi.spyOn(global, 'fetch').mockImplementation(() => {
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/player id/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])
    expect(socket.url).toContain('/rooms/7?token=abc123')

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: { event: 'player_enter', player: 'seer' },
      })
    })

    await waitFor(() =>
      expect(screen.getByText(/Edge of the forest/)).toBeInTheDocument()
    )

    const commandList = within(screen.getByTestId('room-commands'))
    expect(commandList.getByText(/move/i)).toBeInTheDocument()
    expect(commandList.getByText(/look/i)).toBeInTheDocument()
    expect(screen.getByTestId('room-look-description')).toHaveTextContent(
      /temple/i
    )

    expect(screen.getAllByText(/player_enter/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/seer/).length).toBeGreaterThan(0)
    expect(screen.getByText(/ruby/)).toBeInTheDocument()
  })

  it('dispatches move commands and updates room details on location change', async () => {
    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ] as const

    vi.spyOn(global, 'fetch').mockImplementation(() => {
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)
    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/player id/i), 'hero')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          event: 'location_update',
          location: 8,
          description: 'Deep forest clearing',
        },
      })
    })

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /Deep forest clearing/i })
      ).toBeInTheDocument()
    )

    await waitFor(() =>
      expect(screen.getByTestId('room-look-description')).toHaveTextContent(
        /clearing/i
      )
    )

    const exits = within(screen.getByTestId('room-exits'))
    await user.click(exits.getByRole('button', { name: /south/i }))

    expect(JSON.parse(socket.sent.at(-1) ?? '{}')).toMatchObject({
      type: 'command',
      command: 'move',
      args: { direction: 'south' },
    })
  })
})
