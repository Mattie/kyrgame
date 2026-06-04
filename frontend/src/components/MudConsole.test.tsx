import { act, fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { MudConsole } from './MudConsole'

const mockSendCommand = vi.fn()
const mockSendMove = vi.fn()
const mockAdvanceLifecycle = vi.fn()
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
  playerVisuals: {},
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
  advanceLifecycle: mockAdvanceLifecycle,
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

const setConsoleScrollMetrics = (
  element: HTMLElement,
  metrics: { clientHeight: number; scrollHeight: number; scrollTop: number }
) => {
  Object.defineProperty(element, 'clientHeight', {
    configurable: true,
    value: metrics.clientHeight,
  })
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    value: metrics.scrollHeight,
  })
  Object.defineProperty(element, 'scrollTop', {
    configurable: true,
    writable: true,
    value: metrics.scrollTop,
  })
}

const installConsoleScrollTo = (element: HTMLElement) => {
  const scrollTo = vi.fn((options?: ScrollToOptions) => {
    if (!options || typeof options !== 'object') return
    Object.defineProperty(element, 'scrollTop', {
      configurable: true,
      writable: true,
      value: Number(options.top ?? 0),
    })
  })
  Object.defineProperty(element, 'scrollTo', {
    configurable: true,
    writable: true,
    value: scrollTo,
  })
  return scrollTo
}

describe('MudConsole', () => {
  beforeEach(() => {
    mockSendCommand.mockReset()
    mockSendMove.mockReset()
    mockAdvanceLifecycle.mockReset()
    mockAdvanceLifecycle.mockImplementation(() => new Promise<void>(() => undefined))
    localStorage.clear()
    navigatorState.session = { token: 'token', playerId: 'Hero', roomId: 0 }
    navigatorState.world = {
      locations: [{ id: 0, brfdes: 'A dark forest surrounds you in all directions.' }],
      objects: [],
      commands: [],
      messages: {},
    }
    navigatorState.currentRoom = 0
    navigatorState.occupants = []
    navigatorState.playerVisuals = {}
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
    window.history.replaceState(null, '', '/?modem=off')
  })

  it('keeps the MUD header compact for terminal rows', () => {
    const { container } = render(<MudConsole />)

    const header = container.querySelector<HTMLElement>('.mud-header')
    expect(header).toBeInTheDocument()
    expect(header?.querySelector('.eyebrow')).toBeNull()
    expect(header?.querySelector('h2')).toBeNull()
    expect(screen.queryByText('Kyrandia Line Interface')).toBeNull()
    expect(header).toHaveTextContent('Player Hero')
    expect(header).toHaveTextContent('connected')
  })

  it('renders text instantly when modem stream is disabled', () => {
    window.history.replaceState(null, '', '/?modem=off')
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 2 },
    }
    navigatorState.activity = [
      {
        id: 'stream-off-entry',
        type: 'command_response',
        summary: 'This line should appear immediately.',
        payload: null,
      },
    ]

    render(<MudConsole />)

    expect(screen.getByText('This line should appear immediately.')).toBeInTheDocument()
  })

  it('streams one console line at a time when modem mode is enabled', () => {
    vi.useFakeTimers()
    window.history.replaceState(
      null,
      '',
      '/?modem=on&modemBaud=100000&modemCharsPerTick=1000'
    )
    navigatorState.session = null
    navigatorState.world = null
    navigatorState.currentRoom = null
    navigatorState.activity = [
      {
        id: 'stream-entry-one',
        type: 'command_response',
        summary: '\u001b[32mABCD\u001b[0m',
        payload: null,
      },
      {
        id: 'stream-entry-two',
        type: 'command_response',
        summary: 'WXYZ',
        payload: null,
      },
    ]

    const { container } = render(<MudConsole />)
    const streamAnnouncements = screen.getByTestId('console-stream-announcements')
    const announcedLines = () =>
      Array.from(streamAnnouncements.querySelectorAll('p')).map((line) => line.textContent)

    expect(container.querySelector('.crt')).toHaveAttribute('aria-live', 'off')
    expect(streamAnnouncements).toHaveAttribute('aria-live', 'polite')
    expect(announcedLines()).toEqual([])
    expect(screen.queryByText('Connect to begin exploring the world of Kyrandia.')).toBeNull()
    expect(screen.queryByText('ABCD')).toBeNull()
    expect(screen.queryByText('WXYZ')).toBeNull()

    act(() => vi.advanceTimersByTime(100))
    expect(
      screen.getAllByText('Connect to begin exploring the world of Kyrandia.').length
    ).toBeGreaterThan(0)
    expect(announcedLines()).toEqual(['Connect to begin exploring the world of Kyrandia.'])
    expect(screen.queryByText('ABCD')).toBeNull()

    act(() => vi.advanceTimersByTime(100))
    expect(screen.getAllByText('ABCD').length).toBeGreaterThan(0)
    expect(announcedLines()).toEqual([
      'Connect to begin exploring the world of Kyrandia.',
      'ABCD',
    ])
    expect(screen.queryByText('WXYZ')).toBeNull()

    act(() => vi.advanceTimersByTime(100))
    expect(screen.getAllByText('WXYZ').length).toBeGreaterThan(0)
    expect(announcedLines()).toEqual([
      'Connect to begin exploring the world of Kyrandia.',
      'ABCD',
      'WXYZ',
    ])

    vi.useRealTimers()
  })

  it('continues the active stream line when new prefix lines appear', () => {
    vi.useFakeTimers()
    window.history.replaceState(
      null,
      '',
      '/?modem=on&modemBaud=100000&modemCharsPerTick=1000'
    )
    navigatorState.session = null
    navigatorState.world = null
    navigatorState.currentRoom = null
    navigatorState.activity = [
      {
        id: 'stream-entry-one',
        type: 'command_response',
        summary: 'ABCD',
        payload: null,
      },
    ]

    const { rerender } = render(<MudConsole />)

    act(() => vi.advanceTimersByTime(100))
    expect(
      screen.getAllByText('Connect to begin exploring the world of Kyrandia.').length
    ).toBeGreaterThan(0)
    expect(screen.queryByText('ABCD')).toBeNull()

    navigatorState.session = { token: 'token', playerId: 'Hero', roomId: 0 }
    navigatorState.world = {
      locations: [{ id: 0, brfdes: 'A dark forest surrounds you in all directions.' }],
      objects: [],
      commands: [],
      messages: {},
    }
    navigatorState.currentRoom = 0
    rerender(<MudConsole />)

    act(() => vi.advanceTimersByTime(100))

    expect(screen.getAllByText('ABCD').length).toBeGreaterThan(0)
    expect(() => getConsoleLine('A dark forest surrounds you in all directions.')).toThrow()

    vi.useRealTimers()
  })

  it('keeps the console pinned to the bottom while modem text streams', () => {
    vi.useFakeTimers()
    window.history.replaceState(
      null,
      '',
      '/?modem=on&modemBaud=100000&modemCharsPerTick=1000'
    )
    navigatorState.session = null
    navigatorState.world = null
    navigatorState.currentRoom = null
    navigatorState.activity = [
      {
        id: 'stream-scroll-entry',
        type: 'command_response',
        summary: 'ABCD',
        payload: null,
      },
    ]

    const { container } = render(<MudConsole />)
    const consoleElement = container.querySelector<HTMLElement>('.crt') as HTMLElement
    const scrollTo = installConsoleScrollTo(consoleElement)
    setConsoleScrollMetrics(consoleElement, {
      clientHeight: 100,
      scrollHeight: 300,
      scrollTop: 200,
    })
    fireEvent.scroll(consoleElement)

    setConsoleScrollMetrics(consoleElement, {
      clientHeight: 100,
      scrollHeight: 340,
      scrollTop: 200,
    })
    act(() => vi.advanceTimersByTime(100))

    expect(scrollTo).toHaveBeenCalledWith({ top: 340 })
    expect(screen.queryByRole('button', { name: /scroll to latest console output/i })).toBeNull()

    vi.useRealTimers()
  })

  it('shows a latest-output control instead of scrolling when reading older output', () => {
    navigatorState.activity = [
      {
        id: 'scroll-lock-entry-one',
        type: 'command_response',
        summary: 'Earlier line.',
        payload: null,
      },
    ]

    const { container, rerender } = render(<MudConsole />)
    const consoleElement = container.querySelector<HTMLElement>('.crt') as HTMLElement
    const scrollTo = installConsoleScrollTo(consoleElement)
    setConsoleScrollMetrics(consoleElement, {
      clientHeight: 100,
      scrollHeight: 300,
      scrollTop: 80,
    })
    fireEvent.scroll(consoleElement)

    navigatorState.activity = [
      ...navigatorState.activity,
      {
        id: 'scroll-lock-entry-two',
        type: 'command_response',
        summary: 'Newer line.',
        payload: null,
      },
    ]
    setConsoleScrollMetrics(consoleElement, {
      clientHeight: 100,
      scrollHeight: 420,
      scrollTop: 80,
    })
    rerender(<MudConsole />)

    expect(scrollTo).not.toHaveBeenCalled()
    const latestOutput = screen.getByRole('button', { name: /scroll to latest console output/i })
    expect(latestOutput).toBeInTheDocument()

    fireEvent.click(latestOutput)

    expect(scrollTo).toHaveBeenCalledWith({ top: 420 })
    expect(screen.queryByRole('button', { name: /scroll to latest console output/i })).toBeNull()
  })

  it('uses blank ENTER to advance first-login lifecycle pages', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 2 },
    }

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('')
    expect(mockSendCommand).not.toHaveBeenCalled()
    expect(screen.queryByText('A dark forest surrounds you in all directions.')).toBeNull()
    expect(screen.queryByText('Player Hero connected.')).toBeNull()
  })

  it('uses standalone ENTER to advance first-login lifecycle pages', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 2 },
    }

    render(<MudConsole />)

    fireEvent.keyDown(window, { key: 'Enter' })

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('')
    expect(mockSendCommand).not.toHaveBeenCalled()
  })

  it('consumes typed commands as lifecycle advancement before room entry', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('look')
    expect(mockSendCommand).not.toHaveBeenCalled()
  })

  it('uses prompt ENTER to submit typed lifecycle input without a normal command', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('look')
    expect(mockSendCommand).not.toHaveBeenCalled()
  })

  it('ignores repeated lifecycle ENTER submissions while an advance is pending', async () => {
    let resolveLifecycle!: () => void
    const lifecycleRequest = new Promise<void>((resolve) => {
      resolveLifecycle = resolve
    })
    mockAdvanceLifecycle.mockReturnValueOnce(lifecycleRequest)
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockAdvanceLifecycle).toHaveBeenCalledTimes(1)
    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('look')
    expect(mockSendCommand).not.toHaveBeenCalled()

    await act(async () => {
      resolveLifecycle()
      await lifecycleRequest
    })

    fireEvent.keyDown(input, { key: 'Enter' })

    expect(mockAdvanceLifecycle).toHaveBeenCalledTimes(2)
  })

  it('leaves interactive control ENTER activation alone during first-login lifecycle', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }

    render(<MudConsole />)

    const navButton = screen.getByRole('button', { name: /toggle navigation mode/i })
    navButton.focus()
    fireEvent.keyDown(navButton, { key: 'Enter' })

    expect(mockAdvanceLifecycle).not.toHaveBeenCalled()
    expect(mockSendCommand).not.toHaveBeenCalled()
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
    expect(screen.queryByLabelText(/temporary vfx palette controls/i)).toBeNull()
    expect(screen.queryByLabelText(/pulse speed/i)).toBeNull()
  })

  it('renders temporary VFX tuning controls with live values when enabled by query', () => {
    window.history.replaceState(null, '', '/?vfxtune=anything')

    render(<MudConsole />)

    const preset = screen.getByLabelText(/^burn preset$/i) as HTMLSelectElement
    const style = screen.getByLabelText(/burn style/i) as HTMLSelectElement
    const inverted = screen.getByLabelText(/invert burn edge/i) as HTMLInputElement
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
    const output = screen.getByLabelText(/burn preset output/i) as HTMLTextAreaElement

    expect(preset.value).toBe('burningPaperTuned')
    expect(style.value).toBe('paperMask')
    expect(inverted.checked).toBe(false)
    expect(Array.from(style.options).map((option) => option.value)).toEqual([
      'path',
      'thresholdMask',
      'paperMask',
    ])
    expect(Number(detail.value)).toBe(0.64)
    expect(Number(edgeFrequency.value)).toBe(0.012)
    expect(Number(edgeAmplitude.value)).toBe(7)
    expect(Number(flickerAmount.value)).toBe(4.5)
    expect(Number(flickerSpeed.value)).toBe(1)
    expect(Number(driftSpeed.value)).toBe(0.06)
    expect(Number(charDepth.value)).toBe(8)
    expect(Number(glowBleed.value)).toBe(3)
    expect(Number(outerGlow.value)).toBe(0.14)
    expect(Number(glowRadius.value)).toBe(2)
    expect(Number(softness.value)).toBe(1.2)
    expect(Number(pulseSpeed.value)).toBe(0.7)
    expect(Number(pulseDepth.value)).toBe(0.1)
    expect(Number(embers.value)).toBe(1.45)
    expect(detail.min).toBe('0.3')
    expect(flickerSpeed.step).toBe('0.05')
    expect(driftSpeed.step).toBe('0.02')
    expect(screen.getByText('1.00')).toBeInTheDocument()
    expect(output.value).toContain('"renderStyle": "paperMask"')
    expect(output.value).toContain('"inverted": false')
    expect(output.value).toContain('"flickerAmount": 4.5')

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

    fireEvent.click(inverted)
    expect(inverted.checked).toBe(true)
    expect(screen.getByTestId('game-panel-fire-border')).toHaveAttribute(
      'data-inverted',
      'true'
    )
    expect(output.value).toContain('"inverted": true')
  })

  it('renders a temporary palette creator with editable preset output when enabled', () => {
    window.history.replaceState(null, '', '/?vfxtune=anything')

    render(<MudConsole />)

    const preset = screen.getByLabelText(/^palette preset$/i) as HTMLSelectElement
    const flame = screen.getByLabelText(/palette flame core hex/i) as HTMLInputElement
    const output = screen.getByLabelText(/palette preset output/i) as HTMLTextAreaElement

    expect(screen.getByLabelText(/temporary vfx palette controls/i)).toBeInTheDocument()
    expect(preset.value).toBe('myPalette')
    expect(flame.value).toBe('#dfb801')
    expect(output.value).toContain('"flame": "#dfb801"')
    expect(output.value).toContain('"lip": "#e3e2de"')

    fireEvent.change(preset, { target: { value: 'violetGreen' } })

    expect(preset.value).toBe('violetGreen')
    expect(flame.value).toBe('#edb407')
    expect(output.value).toContain('"deep": "#16ac34"')

    fireEvent.change(flame, { target: { value: '#ffcc33' } })

    expect(flame.value).toBe('#ffcc33')
    expect(preset.value).toBe('custom')
    expect(screen.getByText('#ffcc33')).toBeInTheDocument()
    expect(output.value).toContain('"flame": "#ffcc33"')
  })

  it('collapses and expands the temporary VFX tuning panel when enabled', () => {
    window.history.replaceState(null, '', '/?vfxtune=anything')

    render(<MudConsole />)

    const minimize = screen.getByRole('button', { name: /minimize burn controls/i })
    const body = document.getElementById('vfx-tuning-body')
    expect(minimize).toHaveAttribute('aria-expanded', 'true')
    expect(body).not.toHaveAttribute('hidden')
    expect(screen.getByLabelText(/pulse speed/i)).toBeInTheDocument()

    fireEvent.click(minimize)

    const expand = screen.getByRole('button', { name: /expand burn controls/i })
    expect(expand).toHaveAttribute('aria-expanded', 'false')
    expect(body).toHaveAttribute('hidden')

    fireEvent.click(expand)

    expect(screen.getByRole('button', { name: /minimize burn controls/i })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
    expect(body).not.toHaveAttribute('hidden')
    expect(screen.getByLabelText(/pulse speed/i)).toBeInTheDocument()
  })

  it('collapses and expands the temporary VFX palette panel when enabled', () => {
    window.history.replaceState(null, '', '/?vfxtune=anything')

    render(<MudConsole />)

    const minimize = screen.getByRole('button', { name: /minimize palette controls/i })
    const body = document.getElementById('vfx-palette-body')
    expect(minimize).toHaveAttribute('aria-expanded', 'true')
    expect(body).not.toHaveAttribute('hidden')
    expect(screen.getByLabelText(/palette flame core hex/i)).toBeInTheDocument()

    fireEvent.click(minimize)

    const expand = screen.getByRole('button', { name: /expand palette controls/i })
    expect(expand).toHaveAttribute('aria-expanded', 'false')
    expect(body).toHaveAttribute('hidden')

    fireEvent.click(expand)

    expect(screen.getByRole('button', { name: /minimize palette controls/i })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
    expect(body).not.toHaveAttribute('hidden')
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

  it('renders known player names with wizard styling in console text', () => {
    navigatorState.playerVisuals = {
      Merlin: {
        emoji: '🧙‍♂️',
        className: 'player-wizard',
        color: '#a78bfa',
      },
      Morgana: {
        emoji: '🧙‍♀️',
        className: 'player-wizard',
        color: '#a78bfa',
      },
    }
    navigatorState.activity = [
      {
        id: 'players-entry',
        type: 'command_response',
        summary: 'Merlin and Morgana are here.',
        payload: {
          scope: 'player',
          event: 'room_occupants',
          type: 'room_occupants',
          location: 0,
          occupants: ['Merlin', 'Morgana'],
        },
      },
    ]

    render(<MudConsole />)

    const line = getConsoleLine('🧙‍♂️ Merlin and 🧙‍♀️ Morgana are here.')
    expect(line.querySelectorAll('.player-wizard')).toHaveLength(2)
    expect(line.querySelector('.player-wizard')).toHaveStyle({ color: '#a78bfa' })
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
