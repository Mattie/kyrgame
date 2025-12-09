import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { MudConsole } from './MudConsole'

const mockSendCommand = vi.fn()
const mockSendMove = vi.fn()

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => ({
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
    connectionStatus: 'connected',
    error: null,
    startSession: vi.fn(),
    sendMove: mockSendMove,
    sendCommand: mockSendCommand,
  }),
}))

describe('MudConsole', () => {
  it('does not render debug payload JSON in the MUD console', () => {
    render(<MudConsole />)

    expect(screen.getByText('sdfgs vs is here.')).toBeInTheDocument()
    expect(screen.queryByText(/"scope":"player"/)).toBeNull()
    expect(screen.queryByText(/room_occupants.*KUTM11/)).toBeNull()
  })
})
