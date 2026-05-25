import { fireEvent, render, screen } from '@testing-library/react'
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

vi.mock('../context/NavigatorContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../context/NavigatorContext')>()
  return {
    ...actual,
    useNavigator: () => navigatorState,
  }
})

const getConsoleLine = (text: string) =>
  screen.getByText((_, element) =>
    Boolean(element?.classList.contains('crt-line') && element.textContent === text)
  )

const getConsoleLineContaining = (...textParts: string[]) =>
  screen.getByText((_, element) =>
    Boolean(
      element?.classList.contains('crt-line') &&
        textParts.every((part) => element.textContent?.includes(part))
    )
  )

describe('MudConsole', () => {
  beforeEach(() => {
    mockSendCommand.mockReset()
    mockSendMove.mockReset()
    navigatorState.session = { token: 'token', playerId: 'Hero', roomId: 0 }
    navigatorState.world = {
      locations: [{ id: 0, brfdes: 'A dark forest surrounds you in all directions.' }],
      objects: [],
      commands: [],
      messages: {},
    }
    navigatorState.currentRoom = 0
    navigatorState.occupants = []
    navigatorState.connectionStatus = 'connected'
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
      return Boolean(
        element?.classList.contains('crt-line') &&
          element.textContent === 'Welcome adventurer',
      )
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

  it('renders the legacy dryad presence line for the hidden dryad object', () => {
    navigatorState.world = {
      locations: [
        {
          id: 0,
          brfdes: 'A dark forest surrounds you in all directions.',
          objlds: 'among the roots',
          objects: [45],
        },
      ],
      objects: [{ id: 45, name: 'dryad', flags: [] }],
      commands: [],
      messages: {
        KUTM05: 'There is a dryad standing here.',
      },
    }
    navigatorState.activity = []

    render(<MudConsole />)

    expect(screen.getByText('There is nothing lying among the roots.')).toBeInTheDocument()
    const dryadLine = getConsoleLine('There is a 🌱 dryad standing here.')
    expect(dryadLine).toBeInTheDocument()
    expect(dryadLine.querySelector('.creature-dryad')).toHaveStyle({
      color: 'rgb(154, 205, 50)',
    })
  })

  it('renders status command output in the CRT without status sidebars or auto-refresh', () => {
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

    const { container } = render(<MudConsole />)

    expect(
      getConsoleLineContaining('You have a', 'ruby', 'emerald', 'pearl', 'sapphire')
    ).toBeInTheDocument()
    expect(getConsoleLine('"Fireball" and "Shield" memorized, and 42 spell points of energy.  You are at level 10, titled "Wizard".')).toBeInTheDocument()
    expect(container.querySelector('.hud-panel')).toBeNull()
    expect(screen.queryByText('Character readout')).toBeNull()
    expect(screen.queryByLabelText(/Enable auto-refresh/)).toBeNull()

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockSendCommand).toHaveBeenNthCalledWith(1, 'look')

    vi.advanceTimersByTime(5000)
    expect(mockSendCommand).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('does not refresh stale status sidebars after reconnecting', () => {
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

    expect(mockSendCommand).not.toHaveBeenCalled()
    vi.useRealTimers()
    navigatorState.connectionStatus = 'connected'
  })
})
