import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { MudConsole } from './MudConsole'

const mockSendCommand = vi.fn()
const mockSendMove = vi.fn()
const navigatorState = {
  apiBaseUrl: 'http://example.test',
  session: { token: 'token', playerId: 'Hero', roomId: 0 },
  world: {
    locations: [{ id: 0, brfdes: 'A dark forest surrounds you in all directions.' }],
    objects: [],
    commands: [],
    messages: {},
  },
  currentRoom: 0,
  occupants: [],
  activity: [
    {
      id: 'test-entry',
      type: 'room_broadcast',
      summary: 'sdfgs vs is here.',
      payload: {
        scope: 'player',
        event: 'room_occupants',
        type: 'room_occupants',
        location: 0,
        occupants: ['sdfgs vs'],
        text: 'sdfgs vs is here.',
        message_id: 'KUTM11',
      },
    },
  ],
  connectionStatus: 'connected' as const,
  error: null,
  startSession: vi.fn(),
  sendMove: mockSendMove,
  sendCommand: mockSendCommand,
}

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => navigatorState,
}))

describe('MudConsole', () => {
  beforeEach(() => {
    mockSendCommand.mockReset()
    mockSendMove.mockReset()
    navigatorState.activity = [
      {
        id: 'test-entry',
        type: 'room_broadcast',
        summary: 'sdfgs vs is here.',
        payload: {
          scope: 'player',
          event: 'room_occupants',
          type: 'room_occupants',
          location: 0,
          occupants: ['sdfgs vs'],
          text: 'sdfgs vs is here.',
          message_id: 'KUTM11',
        },
      },
    ]
  })

  it('does not render debug payload JSON in the MUD console', () => {
    render(<MudConsole />)

    expect(screen.getAllByText('sdfgs vs is here.').length).toBeGreaterThan(0)
    expect(screen.queryByText(/"scope":"player"/)).toBeNull()
    expect(screen.queryByText(/room_occupants.*KUTM11/)).toBeNull()
  })

  it('activates an inventory status card with auto-refresh toggled on by default', () => {
    vi.useFakeTimers()
    navigatorState.activity = [
      ...navigatorState.activity,
      {
        id: 'inventory-entry',
        type: 'command_response',
        summary: 'You are carrying some things.',
        payload: { event: 'inventory', inventory: ['Gemstone', 'Torch'] },
      },
    ]

    render(<MudConsole />)

    const autoRefreshCheckbox = screen.getByLabelText('Enable auto-refresh for Inventory') as HTMLInputElement
    expect(autoRefreshCheckbox).toBeInTheDocument()
    expect(autoRefreshCheckbox.checked).toBe(true)

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockSendCommand).toHaveBeenNthCalledWith(1, 'look')
    expect(mockSendCommand).toHaveBeenNthCalledWith(2, 'inv', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'inventory' },
    })

    vi.advanceTimersByTime(2000)
    expect(mockSendCommand).toHaveBeenLastCalledWith('inv', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'inventory' },
    })
    vi.useRealTimers()
  })
})
