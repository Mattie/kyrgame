import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { MudConsole } from './MudConsole'
import type { ActivityEntry } from '../context/NavigatorContext'

const sendCommand = vi.fn()
const sendMove = vi.fn()

const mockState = {
  apiBaseUrl: 'http://localhost',
  session: { token: 't', playerId: 'Zonk', roomId: 1 },
  world: null,
  currentRoom: 1,
  occupants: [],
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

  it('shows inventory details after issuing an inventory command', () => {
    const { rerender } = renderConsole()

    expect(screen.queryByText(/Inventory/i)).toBeNull()

    mockState.activity = [
      ...mockState.activity,
      {
        id: '2',
        type: 'command_response',
        summary: '...You have a ruby, your spellbook and 10 pieces of gold.',
        payload: {
          event: 'inventory',
          inventory: ['a ruby'],
        },
      },
    ]

    rerender(<MudConsole />)

    const hudPanel = screen.getByText(/Character readout/i).closest('aside')
    expect(hudPanel).not.toBeNull()
    const scoped = within(hudPanel as HTMLElement)

    expect(scoped.getByText(/Inventory:/i)).toBeInTheDocument()
    expect(scoped.getByText(/a ruby/i)).toBeInTheDocument()
  })
})
