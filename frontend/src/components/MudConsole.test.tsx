import { fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'

import { MudConsole } from './MudConsole'

const mockSendCommand = vi.fn()
const mockSendMove = vi.fn()
const navigatorState: any = {
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
  adminToken: null,
  setAdminToken: vi.fn(),
  applyAdminUpdate: vi.fn(),
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

  it('renders ANSI color spans without escape codes', () => {
    navigatorState.activity = [
      {
        id: 'ansi-entry',
        type: 'command_response',
        summary: '\u001b[1;32mWelcome\u001b[0m adventurer',
        payload: null,
      },
    ]

    const { container } = render(<MudConsole />)

    const line = screen.getByText((_, element) => {
      return element?.classList.contains('crt-line') && element.textContent === 'Welcome adventurer'
    }) as HTMLElement
    expect(line).toBeInTheDocument()
    expect(line.textContent).not.toContain('\u001b[')

    const greenSpan = line.querySelector('.ansi-fg-green')
    expect(greenSpan).toBeInTheDocument()
    expect(greenSpan).toHaveTextContent('Welcome')

    const tokens = Array.from(line.querySelectorAll('.ansi-token'))
    const resetToken = tokens.find((token) => token.textContent?.includes('adventurer'))
    expect(resetToken).toBeDefined()
    expect(resetToken).not.toHaveClass('ansi-fg-green')
    expect(container.textContent).not.toContain('\u001b[0m')
  })

  it('activates an inventory status card with auto-refresh toggled on by default', () => {
    vi.useFakeTimers()
    navigatorState.activity = [
      ...navigatorState.activity,
      {
        id: 'inventory-entry',
        type: 'command_response',
        summary:
          'You have a ruby, an emerald, a pearl, a sapphire, your spellbook and 25 pieces of gold.',
        payload: { event: 'inventory', inventory: ['ruby', 'emerald', 'pearl', 'sapphire'] },
      },
    ]

    render(<MudConsole />)

    const autoRefreshCheckbox = screen.getByLabelText(
      'Enable auto-refresh for inventory'
    ) as HTMLInputElement
    expect(autoRefreshCheckbox).toBeInTheDocument()
    expect(autoRefreshCheckbox.checked).toBe(true)

    expect(screen.getByText('inventory')).toBeInTheDocument()
    const inventoryCard = screen.getByText('inventory').closest('.hud-card') as HTMLElement
    expect(within(inventoryCard).getByText(/You have a/)).toBeInTheDocument()

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockSendCommand).toHaveBeenNthCalledWith(1, 'look')
    expect(mockSendCommand).toHaveBeenNthCalledWith(2, 'inv', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'inventory' },
    })

    vi.advanceTimersByTime(5000)
    expect(mockSendCommand).toHaveBeenLastCalledWith('inv', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'inventory' },
    })
    vi.useRealTimers()
  })

  it('refreshes active status cards after reconnecting', () => {
    vi.useFakeTimers()
    navigatorState.connectionStatus = 'disconnected'
    navigatorState.activity = [
      {
        id: 'inventory-entry',
        type: 'command_response',
        summary: 'You have a ruby.',
        payload: { event: 'inventory', inventory: ['ruby'] },
      },
    ]

    const { rerender } = render(<MudConsole />)
    expect(mockSendCommand).not.toHaveBeenCalled()

    navigatorState.connectionStatus = 'connected'
    rerender(<MudConsole />)

    expect(mockSendCommand).toHaveBeenCalledWith('inv', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'inventory' },
    })
    vi.useRealTimers()
    navigatorState.connectionStatus = 'connected'
  })

  it('pins self-look output and refreshes it with the same look command', () => {
    vi.useFakeTimers()
    navigatorState.activity = []

    const { rerender } = render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look hero' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    navigatorState.activity = [
      {
        id: 'self-look-entry',
        type: 'command_response',
        summary: 'Hero stands before you, carrying a ruby.',
        payload: { message_id: 'MDES' },
      },
    ]
    rerender(<MudConsole />)

    expect(screen.getByText('Self look')).toBeInTheDocument()
    const selfLookCard = screen.getByText('Self look').closest('.hud-card') as HTMLElement
    expect(within(selfLookCard).getByText(/ruby/)).toBeInTheDocument()
    expect(mockSendCommand).toHaveBeenNthCalledWith(1, 'look hero')

    vi.advanceTimersByTime(5000)
    expect(mockSendCommand).toHaveBeenLastCalledWith('look hero', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'selfLook' },
    })
    vi.useRealTimers()
  })



  it('pins self-look card for look-at commands even when name differs from session id', () => {
    vi.useFakeTimers()
    navigatorState.activity = []

    const { rerender } = render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look at Mattie4' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    navigatorState.activity = [
      {
        id: 'self-look-entry-alt-name',
        type: 'command_response',
        summary: 'Mattie4 stands before you, carrying a ruby.',
        payload: { message_id: 'MDES' },
      },
    ]
    rerender(<MudConsole />)

    expect(screen.getByText('Self look')).toBeInTheDocument()

    vi.advanceTimersByTime(5000)
    expect(mockSendCommand).toHaveBeenLastCalledWith('look at Mattie4', {
      silent: true,
      skipLog: true,
      meta: { status_card: 'selfLook' },
    })
    vi.useRealTimers()
  })

  it('does not activate or refresh a hitpoints card from spells payloads', () => {
    vi.useFakeTimers()
    navigatorState.activity = [
      {
        id: 'spells-entry-no-hitpoints',
        type: 'command_response',
        summary: '"Fireball" memorized, and 21 spell points of energy.',
        payload: {
          memorized_spell_names: ['Fireball'],
          spts: 21,
          level: 8,
          title: 'Sorcerer',
        },
      },
    ]

    render(<MudConsole />)
    expect(screen.queryByText('Hitpoints')).not.toBeInTheDocument()

    vi.advanceTimersByTime(5000)
    const sentCommands = mockSendCommand.mock.calls.map((args) => args[0])
    expect(sentCommands).not.toContain('hitpoints')
    vi.useRealTimers()
  })

  it('renders a spells status card with memorized spells and spell points', () => {
    navigatorState.activity = [
      {
        id: 'spells-entry',
        type: 'command_response',
        summary:
          '"Fireball" and "Shield" memorized, and 42 spell points of energy.  You are at level 10, titled "Wizard".',
        payload: {
          memorized_spell_names: ['Fireball', 'Shield'],
          spts: 42,
          level: 10,
          title: 'Wizard',
        },
      },
    ]

    render(<MudConsole />)

    expect(screen.getByText('Spells')).toBeInTheDocument()
    expect(screen.getByText('Memorized: Fireball, Shield')).toBeInTheDocument()
    expect(screen.getByText('Spell points: 42')).toBeInTheDocument()
  })
})
