import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { MudConsole } from './MudConsole'
import type { ActivityEntry } from '../context/NavigatorContext'

const sendCommand = vi.fn()
const sendMove = vi.fn()

const mockState = {
  apiBaseUrl: 'http://localhost',
  session: { token: 't', playerId: 'Zonk', roomId: 1 },
  world: null as any,
  currentRoom: 1,
  occupants: [] as string[],
  activity: [] as ActivityEntry[],
  connectionStatus: 'connected' as const,
  error: null,
  startSession: vi.fn(),
  sendMove,
  sendCommand,
}

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => mockState,
}))

const renderConsole = () => render(<MudConsole />)

describe('MudConsole', () => {
  beforeEach(() => {
    sendCommand.mockClear()
    sendMove.mockClear()
    mockState.activity = []
    mockState.world = null
    mockState.occupants = []
  })

  it('sends typed commands through the prompt', async () => {
    await act(async () => {
      renderConsole()
    })
    const input = screen.getByLabelText(/command input/i)
    await userEvent.type(input, 'look around')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(sendCommand).toHaveBeenCalledWith('look around')
  })

  it('enables navigation mode and routes WASD to movement until the prompt is focused again', async () => {
    await act(async () => {
      renderConsole()
    })
    const compass = screen.getByLabelText(/toggle navigation mode/i)
    await userEvent.click(compass)

    await act(async () => {
      fireEvent.keyDown(document, { key: 'w' })
      fireEvent.keyDown(document, { key: 'a' })
    })

    expect(sendMove).toHaveBeenCalledWith('north')
    expect(sendMove).toHaveBeenCalledWith('west')

    const input = screen.getByLabelText(/command input/i)
    await userEvent.click(input)

    await act(async () => {
      fireEvent.keyDown(document, { key: 'w' })
    })

    expect(sendMove).toHaveBeenCalledTimes(2)
  })

  it('reveals side cards after stat outputs arrive', () => {
    const { rerender } = renderConsole()
    expect(screen.queryByText(/Hitpoints/i)).toBeNull()

    mockState.activity = [
      ...mockState.activity,
      {
        id: '1',
        type: 'command_response',
        summary: 'Hitpoints: 10/12',
        payload: { hitpoints: { current: 10, max: 12 } },
      },
    ]

    rerender(<MudConsole />)

    expect(screen.getAllByText(/Hitpoints: 10\/12/i).length).toBeGreaterThan(0)
  })

  it('renders legacy-style room objects and occupants for location descriptions', () => {
    mockState.world = {
      locations: [
        {
          id: 1,
          brfdes: 'on a north/south path',
          objlds: 'on the path',
          objects: [1, 2],
          gi_north: -1,
          gi_south: -1,
          gi_east: -1,
          gi_west: -1,
        },
      ],
      objects: [
        { id: 1, name: 'emerald', flags: ['VISIBL', 'NEEDAN'] },
        { id: 2, name: 'ruby', flags: ['VISIBL'] },
      ],
      commands: [],
      messages: {},
    }

    mockState.occupants = ['Zonk', 'seer']
    mockState.activity = [
      {
        id: 'loc-1',
        type: 'command_response',
        summary: '...A long temple description',
        payload: { event: 'location_description', location: 1 },
      },
    ]

    renderConsole()

    expect(screen.getByText('There is an emerald and a ruby lying on the path.')).toBeInTheDocument()
    expect(screen.getByText('seer is here.')).toBeInTheDocument()
  })
})
