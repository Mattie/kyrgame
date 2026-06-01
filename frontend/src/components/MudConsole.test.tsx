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
    window.history.replaceState(null, '', '/')
  })

  it('does not render debug payload JSON in the MUD console', () => {
    render(<MudConsole />)

    expect(screen.getAllByText('sdfgs vs is here.').length).toBeGreaterThan(0)
    expect(screen.queryByText(/"scope":"player"/)).toBeNull()
    expect(screen.queryByText(/room_occupants.*KUTM11/)).toBeNull()
  })

  it('wraps the outer game shell with a decorative fire border canvas', () => {
    const { container } = render(<MudConsole />)

    const frame = container.querySelector<HTMLElement>('.mud-shell')
    const crt = container.querySelector<HTMLElement>('.crt')
    const border = screen.getByTestId('game-panel-fire-border')

    expect(frame).toContainElement(crt)
    expect(frame).toContainElement(border)
    expect(border).toHaveAttribute('aria-hidden', 'true')
    expect(border.tagName.toLowerCase()).toBe('canvas')
  })

  it('hides temporary VFX tuning controls by default', () => {
    render(<MudConsole />)

    expect(screen.queryByLabelText(/temporary vfx tuning controls/i)).toBeNull()
    expect(screen.queryByLabelText(/pulse speed/i)).toBeNull()
  })

  it('renders temporary VFX tuning controls with live values when enabled by query', () => {
    window.history.replaceState(null, '', '/?vfxtune=anything')

    render(<MudConsole />)

    const style = screen.getByLabelText(/burn style/i) as HTMLSelectElement
    const detail = screen.getByLabelText(/detail/i) as HTMLInputElement
    const edgeFrequency = screen.getByLabelText(/edge frequency/i) as HTMLInputElement
    const edgeAmplitude = screen.getByLabelText(/edge amplitude/i) as HTMLInputElement
    const flickerAmount = screen.getByLabelText(/flicker amount/i) as HTMLInputElement
    const flickerSpeed = screen.getByLabelText(/flicker speed/i) as HTMLInputElement
    const driftSpeed = screen.getByLabelText(/drift speed/i) as HTMLInputElement
    const charDepth = screen.getByLabelText(/char depth/i) as HTMLInputElement
    const glowBleed = screen.getByLabelText(/glow bleed/i) as HTMLInputElement
    const outerGlow = screen.getByLabelText(/outer glow/i) as HTMLInputElement
    const glowRadius = screen.getByLabelText(/glow radius/i) as HTMLInputElement
    const softness = screen.getByLabelText(/softness/i) as HTMLInputElement
    const pulseSpeed = screen.getByLabelText(/pulse speed/i) as HTMLInputElement
    const pulseDepth = screen.getByLabelText(/pulse depth/i) as HTMLInputElement
    const embers = screen.getByLabelText(/embers/i) as HTMLInputElement

    expect(style.value).toBe('path')
    expect(Array.from(style.options).map((option) => option.value)).toEqual([
      'path',
      'thresholdMask',
      'paperMask',
    ])
    expect(Number(detail.value)).toBe(0.66)
    expect(Number(edgeFrequency.value)).toBe(0.02)
    expect(Number(edgeAmplitude.value)).toBe(31)
    expect(Number(flickerAmount.value)).toBe(3.5)
    expect(Number(flickerSpeed.value)).toBe(3)
    expect(Number(driftSpeed.value)).toBe(1.8)
    expect(Number(charDepth.value)).toBe(6)
    expect(Number(glowBleed.value)).toBe(7.5)
    expect(Number(outerGlow.value)).toBe(0.14)
    expect(Number(glowRadius.value)).toBe(7)
    expect(Number(softness.value)).toBe(2.6)
    expect(Number(pulseSpeed.value)).toBe(3.2)
    expect(Number(pulseDepth.value)).toBe(0.2)
    expect(Number(embers.value)).toBe(0.5)

    fireEvent.change(style, { target: { value: 'thresholdMask' } })
    expect(screen.getByTestId('game-panel-fire-border')).toHaveAttribute(
      'data-render-style',
      'thresholdMask'
    )

    fireEvent.change(style, { target: { value: 'paperMask' } })
    expect(screen.getByTestId('game-panel-fire-border')).toHaveAttribute(
      'data-render-style',
      'paperMask'
    )

    fireEvent.change(pulseSpeed, { target: { value: '4.1' } })
    expect(pulseSpeed.value).toBe('4.1')
    expect(screen.getByText('4.10')).toBeInTheDocument()

    fireEvent.change(detail, { target: { value: '0.72' } })
    expect(detail.value).toBe('0.72')
    expect(screen.getByText('0.720')).toBeInTheDocument()
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
