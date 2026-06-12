import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import type {
  ActivityEntry,
  PlayerVisual,
  SessionRecord,
  WorldData,
} from '../context/NavigatorContext'
import { getGroundObjectVisual } from '../data/groundObjectVisuals'
import { MudConsole } from './MudConsole'

const mockSendCommand = vi.fn()
const mockSendMove = vi.fn()
const mockAdvanceLifecycle = vi.fn()
const highlightedGroundObjectNames = ['scroll', 'elixir', 'codex', 'pinecone'] as const
const completedStreamKeysStorageKey = 'kyrgame.mudConsole.completedStreamKeys'

type MockNavigatorState = {
  apiBaseUrl: string
  session: SessionRecord | null
  world: WorldData | null
  currentRoom: number | null
  occupants: string[]
  playerVisuals: Record<string, PlayerVisual>
  activity: ActivityEntry[]
  connectionStatus: 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'
  error: string | null
  scrySession: {
    targetPlayerId: string
    displayName: string
    status: 'connecting' | 'active' | 'closed' | 'error'
    eventCount: number
    roomId?: number | null
  } | null
  startSession: ReturnType<typeof vi.fn>
  adminToken: string | null
  setAdminToken: ReturnType<typeof vi.fn>
  applyAdminUpdate: ReturnType<typeof vi.fn>
  startScry: ReturnType<typeof vi.fn>
  stopScry: ReturnType<typeof vi.fn>
  advanceLifecycle: typeof mockAdvanceLifecycle
  sendMove: typeof mockSendMove
  sendCommand: typeof mockSendCommand
}

const navigatorState: MockNavigatorState = {
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
  scrySession: null,
  startSession: vi.fn(),
  adminToken: null,
  setAdminToken: vi.fn(),
  applyAdminUpdate: vi.fn(),
  startScry: vi.fn(),
  stopScry: vi.fn(),
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

const setDocumentVisibility = (visibilityState: DocumentVisibilityState) => {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => visibilityState,
  })
}

const setDocumentHasFocus = (hasFocus: boolean) => {
  Object.defineProperty(document, 'hasFocus', {
    configurable: true,
    value: () => hasFocus,
  })
}

const advanceModemTicks = (count: number) => {
  for (let index = 0; index < count; index += 1) {
    act(() => vi.advanceTimersByTime(100))
  }
}

const makeLifecycleText = (lineCount: number) =>
  Array.from({ length: lineCount }, (_, index) => `Line ${index + 1}`).join('\r\n')

const setFirstLoginLifecycleText = (lineCount: number) => {
  const text = makeLifecycleText(lineCount)
  navigatorState.session = {
    token: 'token',
    playerId: 'Hero',
    roomId: 0,
    lifecycle: { state: 'first_login_intro', step: 3 },
  }
  navigatorState.activity = [
    {
      id: `long-lifecycle-${lineCount}`,
      type: 'command_response',
      summary: text,
      payload: {
        scope: 'player',
        event: 'lifecycle_message',
        type: 'lifecycle_message',
        message_id: 'INTROA',
        text,
      },
    },
  ]
}

describe('MudConsole', () => {
  beforeEach(() => {
    mockSendCommand.mockReset()
    mockSendMove.mockReset()
    mockAdvanceLifecycle.mockReset()
    mockAdvanceLifecycle.mockImplementation(() => new Promise<void>(() => undefined))
    localStorage.clear()
    sessionStorage.clear()
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
    navigatorState.scrySession = null
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
    setDocumentVisibility('visible')
    setDocumentHasFocus(true)
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

  it('keeps admin sessions out of game command and movement input', () => {
    navigatorState.session = {
      token: 'admin-token',
      playerId: 'Opal',
      roomId: 7,
      sessionKind: 'admin',
    }
    navigatorState.connectionStatus = 'idle'
    navigatorState.activity = []

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    expect(input).toBeDisabled()
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
    expect(screen.getAllByText(/admin session/i).length).toBeGreaterThan(0)

    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)
    expect(mockSendCommand).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /toggle navigation mode/i }))
    fireEvent.keyDown(window, { key: 'w' })
    expect(mockSendMove).not.toHaveBeenCalled()
  })

  it('unlocks the game prompt after a SCRY session closes', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      sessionKind: 'game',
    }
    navigatorState.scrySession = {
      targetPlayerId: 'opal',
      displayName: 'Opal',
      status: 'closed',
      eventCount: 3,
      roomId: 8,
    }
    navigatorState.activity = []

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    expect(input).toBeEnabled()
    expect(screen.getByRole('button', { name: /send/i })).toBeEnabled()

    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(mockSendCommand).toHaveBeenCalledWith('look')
  })

  it('maps SCRY status text onto existing connection pill classes', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      sessionKind: 'game',
    }
    navigatorState.scrySession = {
      targetPlayerId: 'opal',
      displayName: 'Opal',
      status: 'active',
      eventCount: 1,
      roomId: 8,
    }
    navigatorState.activity = []

    const { container, rerender } = render(<MudConsole />)

    let pill = container.querySelector('.connection-pill')
    expect(pill).toHaveTextContent('active')
    expect(pill).toHaveClass('connected')

    navigatorState.scrySession = {
      targetPlayerId: 'opal',
      displayName: 'Opal',
      status: 'closed',
      eventCount: 1,
      roomId: 8,
    }
    rerender(<MudConsole />)

    pill = container.querySelector('.connection-pill')
    expect(pill).toHaveTextContent('closed')
    expect(pill).toHaveClass('disconnected')
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

  it('recalls normal commands with shell-style history and restores the typed draft', () => {
    render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    const form = input.closest('form') as HTMLFormElement

    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'inventory' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'say hello' } })

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('look')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('inventory')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('look')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.value).toBe('inventory')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.value).toBe('look')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.value).toBe('say hello')

    expect(mockSendCommand).toHaveBeenNthCalledWith(1, 'look')
    expect(mockSendCommand).toHaveBeenNthCalledWith(2, 'inventory')
    expect(mockSendCommand).toHaveBeenNthCalledWith(3, 'look')
  })

  it('uses manual edits as the current history draft', () => {
    render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    const form = input.closest('form') as HTMLFormElement

    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'inventory' } })
    fireEvent.submit(form)

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('inventory')

    fireEvent.change(input, { target: { value: 'say hello' } })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('inventory')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.value).toBe('say hello')
  })

  it('stores only one history entry for repeated identical commands', () => {
    render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    const form = input.closest('form') as HTMLFormElement

    fireEvent.change(input, { target: { value: 'grab pinecone' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'grab pinecone' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'grab pinecone' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'inventory' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'grab pinecone' } })
    fireEvent.submit(form)

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('grab pinecone')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('inventory')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('grab pinecone')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('grab pinecone')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.value).toBe('inventory')

    expect(mockSendCommand).toHaveBeenCalledTimes(5)
  })

  it('excludes typed cardinal movement commands from command history while still sending them', () => {
    render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    const form = input.closest('form') as HTMLFormElement

    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.submit(form)
    const movementCommands = [
      'n',
      'no',
      'north',
      'e',
      'eas',
      'east',
      'w',
      'we',
      'west',
      's',
      'sou',
      'south',
    ]
    for (const command of movementCommands) {
      fireEvent.change(input, { target: { value: command } })
      fireEvent.submit(form)
    }
    fireEvent.change(input, { target: { value: 'news' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'say news travels fast' } })
    fireEvent.submit(form)
    fireEvent.change(input, { target: { value: 'inventory' } })
    fireEvent.submit(form)

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('inventory')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('say news travels fast')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('news')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('look')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('look')

    expect(mockSendCommand).toHaveBeenCalledWith('n')
    expect(mockSendCommand).toHaveBeenCalledWith('north')
    expect(mockSendCommand).toHaveBeenCalledWith('e')
    expect(mockSendCommand).toHaveBeenCalledWith('east')
    expect(mockSendCommand).toHaveBeenCalledWith('w')
    expect(mockSendCommand).toHaveBeenCalledWith('west')
    expect(mockSendCommand).toHaveBeenCalledWith('s')
    expect(mockSendCommand).toHaveBeenCalledWith('south')
  })

  it('keeps only the newest 200 command history entries', () => {
    render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    const form = input.closest('form') as HTMLFormElement

    for (let index = 0; index < 201; index += 1) {
      fireEvent.change(input, { target: { value: `command-${index}` } })
      fireEvent.submit(form)
    }

    for (let index = 0; index < 200; index += 1) {
      fireEvent.keyDown(input, { key: 'ArrowUp' })
    }
    expect(input.value).toBe('command-1')

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('command-1')
  })

  it('focuses the command input when the connected game field is clicked', () => {
    const { container } = render(<MudConsole />)

    const gameField = container.querySelector<HTMLElement>('.crt')
    const navButton = screen.getByRole('button', { name: /toggle navigation mode/i })
    const input = screen.getByLabelText('command input')

    expect(gameField).toBeInTheDocument()
    navButton.focus()
    expect(navButton).toHaveFocus()

    fireEvent.mouseDown(gameField as HTMLElement)

    expect(input).toHaveFocus()
  })

  it('leaves focus alone when the disconnected game field is clicked', () => {
    navigatorState.connectionStatus = 'disconnected'
    const { container } = render(<MudConsole />)

    const gameField = container.querySelector<HTMLElement>('.crt')
    const navButton = screen.getByRole('button', { name: /toggle navigation mode/i })
    const input = screen.getByLabelText('command input')

    expect(gameField).toBeInTheDocument()
    navButton.focus()
    expect(navButton).toHaveFocus()

    fireEvent.mouseDown(gameField as HTMLElement)

    expect(navButton).toHaveFocus()
    expect(input).not.toHaveFocus()
  })

  it('focuses the command input when the session connects', () => {
    navigatorState.session = null
    navigatorState.connectionStatus = 'connecting'
    const { rerender } = render(<MudConsole />)

    const navButton = screen.getByRole('button', { name: /toggle navigation mode/i })
    const input = screen.getByLabelText('command input')

    navButton.focus()
    expect(navButton).toHaveFocus()

    navigatorState.session = { token: 'new-token', playerId: 'Hero', roomId: 0 }
    navigatorState.connectionStatus = 'connected'
    rerender(<MudConsole />)

    expect(input).toHaveFocus()
  })

  it('focuses the command input when the connected tab regains focus', () => {
    render(<MudConsole />)

    const navButton = screen.getByRole('button', { name: /toggle navigation mode/i })
    const input = screen.getByLabelText('command input')

    navButton.focus()
    expect(navButton).toHaveFocus()

    window.dispatchEvent(new Event('focus'))

    expect(input).toHaveFocus()
  })

  it('leaves focus alone when the disconnected tab regains focus', () => {
    navigatorState.connectionStatus = 'disconnected'
    render(<MudConsole />)

    const navButton = screen.getByRole('button', { name: /toggle navigation mode/i })
    const input = screen.getByLabelText('command input')

    navButton.focus()
    expect(navButton).toHaveFocus()

    window.dispatchEvent(new Event('focus'))

    expect(navButton).toHaveFocus()
    expect(input).not.toHaveFocus()
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

  it('renders hydrated scrollback immediately while new modem output still streams', () => {
    vi.useFakeTimers()
    window.history.replaceState(
      null,
      '',
      '/?modem=on&modemBaud=100000&modemCharsPerTick=1000'
    )
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }
    navigatorState.world = null
    navigatorState.currentRoom = null
    navigatorState.activity = [
      {
        id: 'hydrated-scrollback-entry',
        type: 'command_response',
        summary: 'Restored scrollback line.',
        payload: null,
        meta: { hydratedScrollback: true },
      },
      {
        id: 'fresh-after-hydration-entry',
        type: 'command_response',
        summary: 'Fresh post-reconnect line.',
        payload: null,
      },
    ]

    const { container } = render(<MudConsole />)
    const visibleConsoleText = () =>
      container.querySelector<HTMLElement>('.crt-lines')?.textContent ?? ''

    expect(screen.getAllByText('Restored scrollback line.').length).toBeGreaterThan(0)
    expect(screen.queryByText('Fresh post-reconnect line.')).toBeNull()

    act(() => vi.advanceTimersByTime(100))

    expect(screen.getAllByText('Fresh post-reconnect line.').length).toBeGreaterThan(0)
    expect(visibleConsoleText().indexOf('Restored scrollback line.')).toBeLessThan(
      visibleConsoleText().indexOf('Fresh post-reconnect line.')
    )

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

  it('keeps completed modem history visible after the console remounts', () => {
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
        id: 'remount-history-one',
        type: 'command_response',
        summary: 'First completed line.',
        payload: null,
      },
      {
        id: 'remount-history-two',
        type: 'command_response',
        summary: 'Second completed line.',
        payload: null,
      },
    ]

    const { unmount } = render(<MudConsole />)

    advanceModemTicks(5)
    expect(screen.getAllByText('First completed line.').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Second completed line.').length).toBeGreaterThan(0)

    unmount()
    render(<MudConsole />)

    expect(screen.getAllByText('First completed line.').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Second completed line.').length).toBeGreaterThan(0)

    vi.useRealTimers()
  })

  it('keeps completed modem history after a transient empty activity remount', () => {
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
        id: 'hydrated-history-line',
        type: 'command_response',
        summary: 'Hydrated line.',
        payload: null,
      },
    ]

    const { unmount } = render(<MudConsole />)

    advanceModemTicks(5)
    expect(screen.getAllByText('Hydrated line.').length).toBeGreaterThan(0)

    unmount()
    navigatorState.activity = []
    const view = render(<MudConsole />)

    navigatorState.activity = [
      {
        id: 'hydrated-history-line',
        type: 'command_response',
        summary: 'Hydrated line.',
        payload: null,
      },
    ]
    view.rerender(<MudConsole />)

    expect(screen.getAllByText('Hydrated line.').length).toBeGreaterThan(0)

    vi.useRealTimers()
  })

  it('renders modem output immediately when mounted in an unfocused visible window', () => {
    const originalHasFocus = document.hasFocus
    Object.defineProperty(document, 'hasFocus', {
      configurable: true,
      value: () => false,
    })
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
        id: 'blurred-mount-line',
        type: 'command_response',
        summary: 'Blurred mount line.',
        payload: null,
      },
    ]

    try {
      render(<MudConsole />)

      expect(screen.getAllByText('Blurred mount line.').length).toBeGreaterThan(0)
    } finally {
      Object.defineProperty(document, 'hasFocus', {
        configurable: true,
        value: originalHasFocus,
      })
      vi.useRealTimers()
    }
  })

  it('renders modem output when sessionStorage is unavailable during render', () => {
    const originalSessionStorage = window.sessionStorage
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get: () => {
        throw new Error('sessionStorage unavailable')
      },
    })
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
        id: 'storage-unavailable-line',
        type: 'command_response',
        summary: 'Storage unavailable line.',
        payload: null,
      },
    ]

    try {
      expect(() => render(<MudConsole />)).not.toThrow()
      advanceModemTicks(3)
      expect(screen.getAllByText('Storage unavailable line.').length).toBeGreaterThan(0)
    } finally {
      Object.defineProperty(window, 'sessionStorage', {
        configurable: true,
        value: originalSessionStorage,
      })
      vi.useRealTimers()
    }
  })

  it('limits completed stream keys restored from sessionStorage', () => {
    const storedKeys = Array.from({ length: 1105 }, (_, index) => `stored-key-${index}`)
    sessionStorage.setItem(completedStreamKeysStorageKey, JSON.stringify(storedKeys))
    navigatorState.session = null
    navigatorState.world = null
    navigatorState.currentRoom = null
    navigatorState.activity = []

    render(<MudConsole />)

    const restoredKeys = JSON.parse(
      sessionStorage.getItem(completedStreamKeysStorageKey) ?? '[]'
    )
    expect(restoredKeys).toHaveLength(1000)
    expect(restoredKeys[0]).toBe('stored-key-105')
  })

  it('renders output received while the tab is hidden without replaying it', () => {
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
        id: 'hidden-history-one',
        type: 'command_response',
        summary: 'Visible line.',
        payload: null,
      },
    ]

    const { rerender } = render(<MudConsole />)

    advanceModemTicks(4)
    expect(screen.getAllByText('Visible line.').length).toBeGreaterThan(0)

    act(() => {
      setDocumentVisibility('hidden')
      document.dispatchEvent(new Event('visibilitychange'))
    })
    navigatorState.activity = [
      ...navigatorState.activity,
      {
        id: 'hidden-history-two',
        type: 'command_response',
        summary: 'Background line.',
        payload: null,
      },
    ]
    rerender(<MudConsole />)

    expect(screen.getAllByText('Background line.').length).toBeGreaterThan(0)

    act(() => {
      setDocumentVisibility('visible')
      document.dispatchEvent(new Event('visibilitychange'))
    })
    advanceModemTicks(4)
    expect(screen.getAllByText('Background line.')).toHaveLength(1)
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

  it('keeps first-login lifecycle prompt input out of command history', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }

    const { rerender } = render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'look' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('look')
    expect(mockSendCommand).not.toHaveBeenCalled()

    navigatorState.session = { token: 'token', playerId: 'Hero', roomId: 0 }
    rerender(<MudConsole />)

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('')
  })

  it('pauses long first-login text with a MajorBBS pager prompt', () => {
    setFirstLoginLifecycleText(24)

    render(<MudConsole />)

    expect(screen.getByText(/Line 1/)).toBeInTheDocument()
    expect(screen.getByText(/Line 22/)).toBeInTheDocument()
    expect(screen.queryByText(/Line 23/)).toBeNull()
    expect(screen.getByText('(N)onstop, (Q)uit, or (C)ontinue?')).toBeInTheDocument()
  })

  it('sizes first-login pager pages to the visible terminal height', async () => {
    const originalClientHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientHeight'
    )
    const originalGetComputedStyle = window.getComputedStyle
    const getComputedStyleSpy = vi.spyOn(window, 'getComputedStyle').mockImplementation(
      (element) =>
        ({
          ...originalGetComputedStyle(element),
          fontSize: '16px',
          lineHeight: '16px',
        }) as CSSStyleDeclaration
    )
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this instanceof HTMLElement && this.classList.contains('crt') ? 176 : 0
      },
    })

    try {
      setFirstLoginLifecycleText(12)

      render(<MudConsole />)

      await waitFor(() => expect(screen.getByText(/Line 10/)).toBeInTheDocument())
      expect(screen.queryByText(/Line 11/)).toBeNull()
      expect(screen.getByText('(N)onstop, (Q)uit, or (C)ontinue?')).toBeInTheDocument()
    } finally {
      getComputedStyleSpy.mockRestore()
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight)
      } else {
        delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight
      }
    }
  })

  it('offers tappable first-login pager controls for mobile keyboards', () => {
    setFirstLoginLifecycleText(45)

    render(<MudConsole />)

    fireEvent.click(screen.getByRole('button', { name: /continue pager output/i }))

    expect(screen.getByText(/Line 44/)).toBeInTheDocument()
    expect(screen.queryByText(/Line 45/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /show all pager output/i }))

    expect(screen.getByText(/Line 45/)).toBeInTheDocument()
    expect(screen.queryByText('(N)onstop, (Q)uit, or (C)ontinue?')).toBeNull()
    expect(mockAdvanceLifecycle).not.toHaveBeenCalled()
  })

  it('labels the first-login submit control as Enter and advances by tap', () => {
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }
    navigatorState.activity = []

    render(<MudConsole />)

    fireEvent.click(screen.getByRole('button', { name: /^enter$/i }))

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('')
  })

  it('reenables the first-login submit control after a StrictMode lifecycle advance resolves', async () => {
    mockAdvanceLifecycle.mockResolvedValue(undefined)
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 3 },
    }
    navigatorState.activity = []

    const { container } = render(
      <StrictMode>
        <MudConsole />
      </StrictMode>
    )

    fireEvent.click(screen.getByRole('button', { name: /^enter$/i }))

    const sendButton = container.querySelector<HTMLButtonElement>('.send-button')
    expect(sendButton).toBeInTheDocument()
    await waitFor(() => expect(sendButton).not.toBeDisabled())
  })

  it('keeps the on-screen pager Continue control enabled after an intro advance renders a pager', () => {
    mockAdvanceLifecycle.mockImplementation(() => new Promise<void>(() => undefined))
    navigatorState.session = {
      token: 'token',
      playerId: 'Hero',
      roomId: 0,
      lifecycle: { state: 'first_login_intro', step: 2 },
    }
    navigatorState.activity = []

    const { container, rerender } = render(<MudConsole />)

    fireEvent.click(screen.getByRole('button', { name: /^enter$/i }))
    setFirstLoginLifecycleText(45)
    rerender(<MudConsole />)

    const sendButton = container.querySelector<HTMLButtonElement>('.send-button')
    expect(sendButton).toHaveTextContent('Continue')
    expect(sendButton).not.toBeDisabled()

    fireEvent.click(sendButton as HTMLButtonElement)

    expect(screen.getByText(/Line 44/)).toBeInTheDocument()
    expect(screen.queryByText(/Line 45/)).toBeNull()
  })

  it('renders pager action buttons above the normal command bar', () => {
    setFirstLoginLifecycleText(45)

    const { container } = render(<MudConsole />)

    const orderedControls = Array.from(
      container.querySelectorAll('.pager-actions, form.prompt-row')
    )
    expect(orderedControls).toHaveLength(2)
    expect(orderedControls[0]).toHaveClass('pager-actions')
    expect(orderedControls[1]).toHaveClass('prompt-row')
  })

  it('announces first-login pager text and prompt when modem streaming is enabled', async () => {
    window.history.replaceState(null, '', '/?modem=on')
    setFirstLoginLifecycleText(24)

    render(<MudConsole />)

    const streamAnnouncements = screen.getByTestId('console-stream-announcements')

    await waitFor(() => {
      expect(streamAnnouncements).toHaveTextContent('Line 1')
      expect(streamAnnouncements).toHaveTextContent('Line 22')
      expect(streamAnnouncements).toHaveTextContent('(N)onstop, (Q)uit, or (C)ontinue?')
    })
    expect(streamAnnouncements).not.toHaveTextContent('Line 23')
  })

  it('continues one first-login pager screen with C', () => {
    setFirstLoginLifecycleText(24)

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.keyDown(input, { key: 'c' })

    expect(screen.getByText(/Line 24/)).toBeInTheDocument()
    expect(screen.queryByText('(N)onstop, (Q)uit, or (C)ontinue?')).toBeNull()
    expect(mockAdvanceLifecycle).not.toHaveBeenCalled()
  })

  it('keeps first-login pager key commands out of command history', () => {
    setFirstLoginLifecycleText(24)

    const { rerender } = render(<MudConsole />)

    const input = screen.getByLabelText('command input') as HTMLInputElement
    fireEvent.keyDown(input, { key: 'c' })
    expect(mockAdvanceLifecycle).not.toHaveBeenCalled()

    navigatorState.session = { token: 'token', playerId: 'Hero', roomId: 0 }
    rerender(<MudConsole />)

    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input.value).toBe('')
  })

  it('announces first-login pager advances when modem streaming is enabled', async () => {
    window.history.replaceState(null, '', '/?modem=on')
    setFirstLoginLifecycleText(45)

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    const streamAnnouncements = screen.getByTestId('console-stream-announcements')
    const announcedLines = () =>
      Array.from(streamAnnouncements.querySelectorAll('p')).map((line) => line.textContent)

    await waitFor(() => expect(announcedLines().at(-1)).toContain('Line 22'))

    fireEvent.keyDown(input, { key: 'c' })

    await waitFor(() => {
      const latest = announcedLines().at(-1)
      expect(latest).toContain('Line 44')
      expect(latest).toContain('(N)onstop, (Q)uit, or (C)ontinue?')
    })

    fireEvent.keyDown(input, { key: 'n' })

    await waitFor(() => {
      const latest = announcedLines().at(-1)
      expect(latest).toContain('Line 45')
      expect(latest).not.toContain('(N)onstop, (Q)uit, or (C)ontinue?')
    })
  })

  it('reveals the rest of a first-login pager output with N', () => {
    setFirstLoginLifecycleText(45)

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.keyDown(input, { key: 'n' })

    expect(screen.getByText(/Line 45/)).toBeInTheDocument()
    expect(screen.queryByText('(N)onstop, (Q)uit, or (C)ontinue?')).toBeNull()
    expect(mockAdvanceLifecycle).not.toHaveBeenCalled()
  })

  it('quits the current first-login pager output with Q and keeps lifecycle input available', () => {
    setFirstLoginLifecycleText(45)

    render(<MudConsole />)

    const input = screen.getByLabelText('command input')
    fireEvent.keyDown(input, { key: 'q' })

    expect(screen.queryByText(/Line 45/)).toBeNull()
    expect(screen.queryByText('(N)onstop, (Q)uit, or (C)ontinue?')).toBeNull()
    expect(mockAdvanceLifecycle).not.toHaveBeenCalled()

    fireEvent.keyDown(input, { key: 'Enter' })

    expect(mockAdvanceLifecycle).toHaveBeenCalledWith('')
  })

  it('keeps pager-handled intro output visible when first-login lifecycle completes', () => {
    window.history.replaceState(null, '', '/?modem=on&modemBaud=100000&modemCharsPerTick=1000')
    setFirstLoginLifecycleText(45)

    const { container, rerender } = render(<MudConsole />)
    const visibleConsoleText = () =>
      container.querySelector<HTMLElement>('.crt-lines')?.textContent ?? ''

    const input = screen.getByLabelText('command input')
    fireEvent.keyDown(input, { key: 'n' })
    expect(visibleConsoleText()).toContain('Line 45')

    navigatorState.session = { token: 'token', playerId: 'Hero', roomId: 0 }
    rerender(<MudConsole />)

    expect(visibleConsoleText()).toContain('Line 45')
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

  it('renders one occupant line when room state and occupant activity overlap', () => {
    navigatorState.occupants = ['Venjax']
    navigatorState.activity = [
      {
        id: 'occupants-entry',
        type: 'command_response',
        summary: 'Venjax is here.',
        payload: {
          scope: 'player',
          event: 'room_occupants',
          type: 'room_occupants',
          location: 0,
          occupants: ['Venjax'],
          text: 'Venjax is here.',
          message_id: 'KUTM11',
        },
      },
    ]

    render(<MudConsole />)

    expect(screen.getAllByText('Venjax is here.')).toHaveLength(1)
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

  it('renders scroll, elixir, codex, and pinecone visuals in console ground object lines', () => {
    navigatorState.world = {
      locations: [
        {
          id: 0,
          brfdes: 'A dark forest surrounds you in all directions.',
          objlds: 'on the ground',
          objects: [12, 32, 35, 36],
        },
      ],
      objects: [
        { id: 12, name: 'elixir', flags: ['VISIBL', 'NEEDAN'] },
        { id: 32, name: 'pinecone', flags: ['VISIBL'] },
        { id: 35, name: 'scroll', flags: ['VISIBL'] },
        { id: 36, name: 'codex', flags: ['VISIBL'] },
      ],
      commands: [],
      messages: {},
    }
    navigatorState.activity = []

    render(<MudConsole />)

    const line = getConsoleLine(
      'There is an 🧪 elixir, a 🌰 pinecone, a 📜 scroll, and a 📖 codex lying on the ground.'
    )
    highlightedGroundObjectNames.forEach((name) => {
      const visual = getGroundObjectVisual(name)!
      const inlineObject = line.querySelector(`.${visual.className}`)

      expect(inlineObject).toBeInTheDocument()
      expect(inlineObject).toHaveTextContent(`${visual.emoji} ${name}`)
      expect(inlineObject).toHaveStyle({ color: visual.color })
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
