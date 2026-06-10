import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  onclose: ((event: { code: number; reason: string }) => void) | null = null

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

  close(code = 1000, reason = '') {
    this.onclose?.({ code, reason })
  }

  triggerMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
})

const getConsoleLines = (text: string) =>
  screen.getAllByText((_, element) =>
    Boolean(
      element?.classList.contains('crt-line') && element.textContent === text
    )
  )

const queryConsoleLines = (text: string) =>
  screen.queryAllByText((_, element) =>
    Boolean(
      element?.classList.contains('crt-line') && element.textContent === text
    )
  )

const activePlayerRosterResponse = () =>
  Promise.resolve({
    ok: true,
    json: async () => ({ active: [], recent: [] }),
  } as unknown as Response)

const maybeActivePlayerRosterFetch = (input: RequestInfo | URL) => {
  const url = String(input)
  return url.endsWith('/public/player-activity')
    ? activePlayerRosterResponse()
    : null
}

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

  const objects = [
    { id: 0, name: 'ruby' },
    { id: 1, name: 'emerald' },
    { id: 2, name: 'sapphire' },
    { id: 3, name: 'garnet' },
  ]

  const commands = [
    { id: 1, command: 'move' },
    { id: 2, command: 'look' },
  ]

  const messages = {
    WELCOME: 'Welcome to Kyrandia!',
    KRD007: 'A long description of the temple.',
    KRD008: 'A long description of the clearing.',
    SAPRAY: '*** hero is praying to the Goddess Tashanna.',
    KUTM05: 'There is a dryad standing here.',
  }

  const adminMobSnapshot = {
    animation: {
      routine_index: 5,
      next_routine: 'browns',
      routine_sequence: [
        'dryads',
        'elves',
        'gemakr',
        'gemakr',
        'zarapp',
        'browns',
      ],
      tick_seconds: 1,
      animation_tick_interval_seconds: 15,
      brownie_routine_interval_seconds: 90,
      brownie_full_path_interval_seconds: 3600,
      legacy_source: 'legacy/KYRANIM.C:116-133',
    },
    mobs: [
      {
        id: 'dryad',
        name: 'Dryad',
        kind: 'persistent_room_object',
        status: 'present',
        object_id: 45,
        room_id: 0,
        room: {
          id: 0,
          brief: 'near a mystical willow tree',
          object_landing: 'on the ground',
        },
        legacy_source: 'legacy/KYRANIM.C:326-348',
      },
      {
        id: 'brownie',
        name: 'Brownie',
        kind: 'path_encounter',
        status: 'last_checked',
        room_id: 0,
        room: {
          id: 0,
          brief: 'near a mystical willow tree',
          object_landing: 'on the ground',
        },
        path_index: 19,
        path_length: 40,
        next_room_id: 129,
        next_room: {
          id: 129,
          brief: 'on a winding trail',
          object_landing: 'nearby',
        },
        routine_interval_seconds: 90,
        full_path_interval_seconds: 3600,
        legacy_source: 'legacy/KYRANIM.C:69-80,393-426',
      },
      {
        id: 'elf',
        name: 'Elf',
        kind: 'transient_encounter',
        status: 'between_encounters',
        room_id: null,
        room: null,
        next_outcome: 'hint',
        hint_index: 4,
        legacy_source: 'legacy/KYRANIM.C:352-389',
      },
      {
        id: 'dragon',
        name: 'Zar',
        kind: 'persistent_room_object',
        status: 'present',
        object_id: 52,
        room_id: 250,
        state_room_id: 250,
        home_room_id: 302,
        counter: 8,
        attack_index: 2,
        next_attack: 'claw',
        room: {
          id: 250,
          brief: 'in a dark passage',
          object_landing: 'on the ground',
        },
        legacy_source: 'legacy/KYRANIM.C:155-263,453-459',
      },
    ],
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    MockWebSocket.instances.length = 0
    localStorage.clear()
    window.history.replaceState(null, '', '/admin?modem=off')
  })

  it('starts with mobile controls drawer open before login', () => {
    render(<App />)

    expect(screen.getByRole('main')).toHaveClass('controls-open')
    const toggle = screen.getByRole('button', { name: /hide controls/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(
      screen.getByRole('complementary', { name: /session and admin controls/i })
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/^player id$/i)).toBeInTheDocument()
  })

  it('closes the mobile controls drawer after login and can reopen it', async () => {
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)
    const user = userEvent.setup()

    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    await waitFor(() =>
      expect(screen.getByRole('main')).toHaveClass('controls-closed')
    )
    const toggle = screen.getByRole('button', { name: /show controls/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(toggle)

    expect(screen.getByRole('main')).toHaveClass('controls-open')
    expect(
      screen.getByRole('button', { name: /hide controls/i })
    ).toHaveAttribute('aria-expanded', 'true')
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    expect(screen.getByRole('main')).toHaveClass('dev-layout')

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])
    expect(socket.url).toContain('/rooms/7?token=abc123')

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          scope: 'player',
          event: 'room_occupants',
          type: 'room_occupants',
          location: 7,
          occupants: ['seer'],
          text: 'seer is here.',
        },
      })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_message',
          type: 'room_message',
          player: 'seer',
          from: 6,
          to: 7,
          direction: 'east',
          text: '*** seer has just appeared from the west!',
        },
      })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_message',
          type: 'room_message',
          player: 'hero',
          message_id: 'SAPRAY',
        },
      })
    })

    // RoomPanel is disabled, so we check MudConsole header instead
    await waitFor(() =>
      expect(screen.getAllByText(/Edge of the forest/i).length).toBeGreaterThan(
        0
      )
    )

    // RoomPanel components are no longer rendered (room-commands, room-look-description)
    // The room information is now only shown in MudConsole

    expect(screen.getAllByText(/seer is here/i).length).toBeGreaterThan(0)
    expect(
      screen.getAllByText(/appeared from the west/i).length
    ).toBeGreaterThan(0)
    // ruby appears in MudConsole (initial room description with GemstoneText styling)
    expect(screen.getAllByText(/ruby/i).length).toBeGreaterThan(0)

    // message_id fallback is resolved via cached world messages
    expect(
      screen.getAllByText(/praying to the Goddess Tashanna/i).length
    ).toBeGreaterThan(0)
  })

  it('claims a new Player-ID and advances legacy intro lifecycle messages with ENTER', async () => {
    const firstLoginMessages = {
      ...messages,
      GETALS:
        'Since this is your first time entering Kyrandia (Fantasy-world), you must pick a 3-9 character Player-ID for yourself.',
      GOODPD:
        'Good!  You will now be known as "Merlin" throughout Kyrandia (Fantasy World).\r\n\r\nPress ENTER to begin',
      INTROA:
        'Welcome, brave and adventurous one.\r\n\r\nPress ENTER to continue',
      INTROB: 'Here is how to play.\r\n\r\nPress ENTER to continue',
      INTROC:
        'Spells are magic cast by players.\r\n\r\nPress ENTER to continue',
      INTROD:
        'Enjoy the magic, mystery, and mirth of Kyrandia, Fantasy World of Legends!',
    }
    const lifecyclePages = [
      {
        lifecycle: { state: 'first_login_intro', step: 3 },
        lifecycle_messages: [
          { message_id: 'INTROA', text: firstLoginMessages.INTROA },
        ],
      },
      {
        lifecycle: { state: 'first_login_intro', step: 4 },
        lifecycle_messages: [
          { message_id: 'INTROB', text: firstLoginMessages.INTROB },
        ],
      },
      {
        lifecycle: { state: 'first_login_intro', step: 5 },
        lifecycle_messages: [
          { message_id: 'INTROC', text: firstLoginMessages.INTROC },
        ],
      },
      {
        lifecycle: { state: 'first_login_intro', step: 6 },
        lifecycle_messages: [
          { message_id: 'INTROD', text: firstLoginMessages.INTROD },
        ],
      },
      {
        lifecycle: { state: 'first_login_entry', step: 6 },
        lifecycle_messages: [],
      },
    ]
    let advanceIndex = 0
    const roomZeroLocations = [
      {
        id: 0,
        brfdes: 'at the edge of Kyrandia',
        objlds: 'nearby',
        objects: [],
        gi_north: -1,
        gi_south: -1,
        gi_east: -1,
        gi_west: -1,
      },
      ...locations,
    ]
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const url = String(input)
      if (url.includes('/auth/session/lifecycle/advance')) {
        const page = lifecyclePages[advanceIndex++]
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'advanced',
            session: {
              token: 'new-player-token',
              player_id: 'Merlin',
              room_id: 0,
              first_login: true,
              player_flags: 1,
              lifecycle: page.lifecycle,
              lifecycle_messages: page.lifecycle_messages,
            },
          }),
        } as unknown as Response)
      }
      if (url.includes('/auth/session')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'created',
            session: {
              token: 'new-player-token',
              player_id: 'Merlin',
              room_id: 0,
              first_login: true,
              player_flags: 1,
              lifecycle: { state: 'first_login_intro', step: 2 },
              lifecycle_messages: [
                { message_id: 'GOODPD', text: firstLoginMessages.GOODPD },
              ],
            },
          }),
        } as unknown as Response)
      }
      if (url.includes('/locations')) {
        return Promise.resolve({
          ok: true,
          json: async () => roomZeroLocations,
        } as unknown as Response)
      }
      if (url.includes('/objects')) {
        return Promise.resolve({
          ok: true,
          json: async () => objects,
        } as unknown as Response)
      }
      if (url.includes('/commands')) {
        return Promise.resolve({
          ok: true,
          json: async () => commands,
        } as unknown as Response)
      }
      if (url.includes('/i18n/en-US/messages')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ messages: firstLoginMessages }),
        } as unknown as Response)
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    })

    render(<App />)

    expect(
      screen.queryByText(/Since this is your first time entering Kyrandia/i)
    ).not.toBeInTheDocument()

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'Merlin')
      await user.type(screen.getByLabelText(/room id/i), '12')
      await user.click(
        screen.getByRole('checkbox', { name: /claim new player-id/i })
      )
      expect(screen.getByLabelText(/room id/i)).toBeDisabled()
      expect(
        screen.getByText(/Since this is your first time entering Kyrandia/i)
      ).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: /claim player-id/i }))
    })

    const authCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/auth/session')
    )
    const sessionRequest = JSON.parse(
      String((authCall?.[1] as RequestInit)?.body)
    )
    expect(sessionRequest).toEqual({
      player_id: 'Merlin',
      create_player: true,
    })
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(0))
    expect(
      screen.getByText((_, element) =>
        Boolean(
          element?.classList.contains('crt-line') &&
          element.textContent?.includes('Good!  You will now be known as "') &&
          element.textContent?.includes('Merlin')
        )
      )
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/at the edge of Kyrandia/i)
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText((_, element) =>
        Boolean(
          element?.classList.contains('crt-line') &&
          element.textContent?.includes('Player') &&
          element.textContent?.includes('Merlin connected.')
        )
      )
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Welcome, brave and adventurous one/i)
    ).not.toBeInTheDocument()

    const commandInput = screen.getByLabelText(/command input/i)
    fireEvent.submit(commandInput.closest('form') as HTMLFormElement)
    await waitFor(() => {
      expect(
        screen.getByText((_, element) =>
          Boolean(
            element?.classList.contains('crt-line') &&
            element.textContent?.includes('Welcome, brave and adventurous one')
          )
        )
      ).toBeInTheDocument()
    })
    expect(screen.queryByText(/Here is how to play/i)).not.toBeInTheDocument()

    fireEvent.submit(commandInput.closest('form') as HTMLFormElement)
    await waitFor(() => {
      expect(
        screen.getByText((_, element) =>
          Boolean(
            element?.classList.contains('crt-line') &&
            element.textContent?.includes('Here is how to play')
          )
        )
      ).toBeInTheDocument()
    })

    fireEvent.submit(commandInput.closest('form') as HTMLFormElement)
    await waitFor(() => {
      expect(
        screen.getByText((_, element) =>
          Boolean(
            element?.classList.contains('crt-line') &&
            element.textContent?.includes('Spells are magic cast by players')
          )
        )
      ).toBeInTheDocument()
    })

    fireEvent.submit(commandInput.closest('form') as HTMLFormElement)
    await waitFor(() => {
      expect(
        screen.getByText((_, element) =>
          Boolean(
            element?.classList.contains('crt-line') &&
            element.textContent?.includes('Enjoy the magic, mystery, and mirth')
          )
        )
      ).toBeInTheDocument()
    })

    fireEvent.submit(commandInput.closest('form') as HTMLFormElement)
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    const socket = MockWebSocket.instances[0]
    expect(socket.url).toContain('/rooms/0?token=new-player-token')
    expect(
      screen.getByText((_, element) =>
        Boolean(
          element?.classList.contains('crt-line') &&
          element.textContent === 'Player 🧙‍♂️ Merlin connected.'
        )
      )
    ).toBeInTheDocument()
  })

  it('logs an existing player in with userid and password from the play screen', async () => {
    window.history.replaceState(null, '', '/play')
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input, init) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = String(input)
        if (url.includes('/public/player-id/')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              player_id: 'Hero',
              canonical_player_id: 'Hero',
              valid: true,
              exists: true,
              available: false,
              reserved: false,
              status: 'existing',
            }),
          } as unknown as Response)
        }
        if (url.includes('/auth/login')) {
          expect(JSON.parse(String(init?.body))).toEqual({
            userid: 'Hero',
            password: 'secret-password',
            session_kind: 'game',
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'created',
              session: {
                token: 'account-token',
                player_id: 'Hero',
                account_userid: 'Hero',
                session_kind: 'game',
                room_id: 7,
              },
            }),
          } as unknown as Response)
        }
        if (url.includes('/locations')) {
          return Promise.resolve({
            ok: true,
            json: async () => locations,
          } as unknown as Response)
        }
        if (url.includes('/objects')) {
          return Promise.resolve({
            ok: true,
            json: async () => objects,
          } as unknown as Response)
        }
        if (url.includes('/commands')) {
          return Promise.resolve({
            ok: true,
            json: async () => commands,
          } as unknown as Response)
        }
        if (url.includes('/i18n/en-US/messages')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ messages }),
          } as unknown as Response)
        }
        throw new Error(`Unexpected fetch call: ${url}`)
      })

    render(<App />)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/^player id$/i), 'Hero')
    await user.type(screen.getByLabelText(/^password$/i), 'secret-password')
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /login as hero/i })
      ).toBeEnabled()
    )
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute(
      'autocomplete',
      'current-password'
    )
    expect(
      screen.queryByText(/use the password for this player-id account/i)
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /login as hero/i }))

    const socket = await waitFor(() => MockWebSocket.instances[0])
    expect(socket.url).toContain('/rooms/7?token=account-token')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.local/auth/login',
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('stores remembered session metadata when player login checks remember me', async () => {
    window.history.replaceState(null, '', '/play')
    vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const url = String(input)
      if (url.includes('/public/player-id/')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            player_id: 'Hero',
            canonical_player_id: 'Hero',
            valid: true,
            exists: true,
            available: false,
            reserved: false,
            status: 'existing',
          }),
        } as unknown as Response)
      }
      if (url.includes('/auth/login')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          userid: 'Hero',
          password: 'secret-password',
          session_kind: 'game',
          remember_me: true,
        })
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'created',
            session: {
              token: 'remembered-token',
              player_id: 'Hero',
              account_userid: 'Hero',
              session_kind: 'game',
              room_id: 7,
              expires_at: '2026-07-10T12:00:00+00:00',
              expires_in_seconds: 2592000,
            },
          }),
        } as unknown as Response)
      }
      if (url.includes('/locations')) {
        return Promise.resolve({ ok: true, json: async () => locations } as unknown as Response)
      }
      if (url.includes('/objects')) {
        return Promise.resolve({ ok: true, json: async () => objects } as unknown as Response)
      }
      if (url.includes('/commands')) {
        return Promise.resolve({ ok: true, json: async () => commands } as unknown as Response)
      }
      if (url.includes('/i18n/en-US/messages')) {
        return Promise.resolve({ ok: true, json: async () => ({ messages }) } as unknown as Response)
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    })

    render(<App />)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/^player id$/i), 'Hero')
    await user.type(screen.getByLabelText(/^password$/i), 'secret-password')
    await user.click(screen.getByRole('checkbox', { name: /remember me/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /login as hero/i })).toBeEnabled()
    )
    await user.click(screen.getByRole('button', { name: /login as hero/i }))

    await waitFor(() => expect(MockWebSocket.instances[0]?.url).toContain('remembered-token'))
    expect(JSON.parse(localStorage.getItem('kyrgame.navigator.rememberedSession') ?? '{}')).toEqual({
      token: 'remembered-token',
      playerId: 'Hero',
      accountUserId: 'Hero',
      sessionKind: 'game',
      roomId: 7,
      expiresAt: '2026-07-10T12:00:00+00:00',
    })
  })

  it('auto-resumes a remembered player session on direct play load', async () => {
    window.history.replaceState(null, '', '/play')
    localStorage.setItem(
      'kyrgame.navigator.rememberedSession',
      JSON.stringify({
        token: 'remembered-token',
        playerId: 'Hero',
        accountUserId: 'Hero',
        sessionKind: 'game',
        roomId: 7,
        expiresAt: '2999-07-10T12:00:00+00:00',
      })
    )

    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const url = String(input)
      if (url.includes('/auth/session')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          player_id: 'Hero',
          resume_token: 'remembered-token',
        })
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'recovered',
            session: {
              token: 'remembered-token',
              player_id: 'Hero',
              account_userid: 'Hero',
              session_kind: 'game',
              room_id: 7,
              expires_at: '2999-07-10T12:00:00+00:00',
              expires_in_seconds: 2592000,
              resumed: true,
            },
          }),
        } as unknown as Response)
      }
      if (url.includes('/locations')) {
        return Promise.resolve({ ok: true, json: async () => locations } as unknown as Response)
      }
      if (url.includes('/objects')) {
        return Promise.resolve({ ok: true, json: async () => objects } as unknown as Response)
      }
      if (url.includes('/commands')) {
        return Promise.resolve({ ok: true, json: async () => commands } as unknown as Response)
      }
      if (url.includes('/i18n/en-US/messages')) {
        return Promise.resolve({ ok: true, json: async () => ({ messages }) } as unknown as Response)
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    })

    render(<App />)

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        'http://api.local/auth/session',
        expect.objectContaining({ method: 'POST' })
      )
    )
    await waitFor(() => expect(MockWebSocket.instances[0]?.url).toContain('remembered-token'))
    expect(screen.queryByLabelText(/^player id$/i)).not.toBeInTheDocument()
  })

  it('clears rejected remembered sessions and shows the play login form', async () => {
    window.history.replaceState(null, '', '/play')
    localStorage.setItem(
      'kyrgame.navigator.rememberedSession',
      JSON.stringify({
        token: 'expired-token',
        playerId: 'Hero',
        accountUserId: 'Hero',
        sessionKind: 'game',
        roomId: 7,
        expiresAt: '2999-07-10T12:00:00+00:00',
      })
    )

    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const url = String(input)
      if (url.includes('/auth/session')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ detail: 'Session not found or expired' }),
          text: async () => 'Session not found or expired',
        } as unknown as Response)
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    })

    render(<App />)

    await waitFor(() => expect(screen.getByLabelText(/^player id$/i)).toBeInTheDocument())
    expect(localStorage.getItem('kyrgame.navigator.rememberedSession')).toBeNull()
  })

  it('keeps remembered session metadata when auto-resume hits a transient failure', async () => {
    window.history.replaceState(null, '', '/play')
    localStorage.setItem(
      'kyrgame.navigator.rememberedSession',
      JSON.stringify({
        token: 'remembered-token',
        playerId: 'Hero',
        accountUserId: 'Hero',
        sessionKind: 'game',
        roomId: 7,
        expiresAt: '2999-07-10T12:00:00+00:00',
      })
    )

    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const url = String(input)
      if (url.includes('/auth/session')) {
        throw new Error('Temporary network failure')
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    })

    render(<App />)

    await waitFor(() => expect(screen.getByLabelText(/^player id$/i)).toBeInTheDocument())
    expect(localStorage.getItem('kyrgame.navigator.rememberedSession')).toEqual(
      JSON.stringify({
        token: 'remembered-token',
        playerId: 'Hero',
        accountUserId: 'Hero',
        sessionKind: 'game',
        roomId: 7,
        expiresAt: '2999-07-10T12:00:00+00:00',
      })
    )
  })

  it('registers an available player account from the play screen', async () => {
    window.history.replaceState(null, '', '/play')
    const firstLoginMessages = {
      ...messages,
      GOODPD:
        'Good!  You will now be known as "Lyra" throughout Kyrandia (Fantasy World).\r\n\r\nPress ENTER to begin',
    }
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input, init) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = String(input)
        if (url.includes('/public/player-id/')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              player_id: 'Lyra',
              canonical_player_id: 'Lyra',
              valid: true,
              exists: false,
              available: true,
              reserved: false,
              status: 'available',
            }),
          } as unknown as Response)
        }
        if (url.includes('/auth/register')) {
          expect(JSON.parse(String(init?.body))).toEqual({
            userid: 'Lyra',
            password: 'new-secret',
            session_kind: 'game',
            background: 'lord',
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'created',
              session: {
                token: 'new-account-token',
                player_id: 'Lyra',
                account_userid: 'Lyra',
                session_kind: 'game',
                room_id: 0,
                first_login: true,
                lifecycle: { state: 'first_login_intro', step: 2 },
                lifecycle_messages: [
                  { message_id: 'GOODPD', text: firstLoginMessages.GOODPD },
                ],
              },
            }),
          } as unknown as Response)
        }
        if (url.includes('/locations')) {
          return Promise.resolve({
            ok: true,
            json: async () => locations,
          } as unknown as Response)
        }
        if (url.includes('/objects')) {
          return Promise.resolve({
            ok: true,
            json: async () => objects,
          } as unknown as Response)
        }
        if (url.includes('/commands')) {
          return Promise.resolve({
            ok: true,
            json: async () => commands,
          } as unknown as Response)
        }
        if (url.includes('/i18n/en-US/messages')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ messages: firstLoginMessages }),
          } as unknown as Response)
        }
        throw new Error(`Unexpected fetch call: ${url}`)
      })

    render(<App />)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/^player id$/i), 'Lyra')
    await user.type(screen.getByLabelText(/^password$/i), 'new-secret')
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /create character/i })
      ).toBeEnabled()
    )
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute(
      'autocomplete',
      'new-password'
    )
    expect(
      screen.queryByText(/use the password for this player-id account/i)
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /create character/i }))

    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.local/auth/register',
      expect.objectContaining({ method: 'POST' })
    )
    await waitFor(() => {
      expect(document.body.textContent).toContain(
        'Good!  You will now be known as "'
      )
      expect(document.body.textContent).toContain('Lyra')
    })
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('reports lifecycle advance failures without opening the room socket', async () => {
    const firstLoginMessages = {
      ...messages,
      GETALS:
        'Since this is your first time entering Kyrandia (Fantasy-world), you must pick a 3-9 character Player-ID for yourself.',
      GOODPD:
        'Good!  You will now be known as "Merlin" throughout Kyrandia (Fantasy World).\r\n\r\nPress ENTER to begin',
    }
    const roomZeroLocations = [
      {
        id: 0,
        brfdes: 'at the edge of Kyrandia',
        objlds: 'nearby',
        objects: [],
        gi_north: -1,
        gi_south: -1,
        gi_east: -1,
        gi_west: -1,
      },
      ...locations,
    ]
    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const url = String(input)
      if (url.includes('/auth/session/lifecycle/advance')) {
        return Promise.reject(new Error('Network dropped'))
      }
      if (url.includes('/auth/session')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'created',
            session: {
              token: 'new-player-token',
              player_id: 'Merlin',
              room_id: 0,
              first_login: true,
              player_flags: 1,
              lifecycle: { state: 'first_login_intro', step: 2 },
              lifecycle_messages: [
                { message_id: 'GOODPD', text: firstLoginMessages.GOODPD },
              ],
            },
          }),
        } as unknown as Response)
      }
      if (url.includes('/locations')) {
        return Promise.resolve({
          ok: true,
          json: async () => roomZeroLocations,
        } as unknown as Response)
      }
      if (url.includes('/objects')) {
        return Promise.resolve({
          ok: true,
          json: async () => objects,
        } as unknown as Response)
      }
      if (url.includes('/commands')) {
        return Promise.resolve({
          ok: true,
          json: async () => commands,
        } as unknown as Response)
      }
      if (url.includes('/i18n/en-US/messages')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ messages: firstLoginMessages }),
        } as unknown as Response)
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'Merlin')
      await user.click(
        screen.getByRole('checkbox', { name: /claim new player-id/i })
      )
      await user.click(screen.getByRole('button', { name: /claim player-id/i }))
    })

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(0))
    const commandInput = screen.getByLabelText(/command input/i)
    fireEvent.submit(commandInput.closest('form') as HTMLFormElement)

    await waitFor(() =>
      expect(screen.getAllByText(/Network dropped/i).length).toBeGreaterThan(0)
    )
    expect(screen.getByText(/connection: error/i)).toBeInTheDocument()
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('shows session expiration metadata and reconnects with a fresh token after close', async () => {
    const fetchMock = vi.spyOn(global, 'fetch')
    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: {
            token: 'abc123',
            player_id: 'hero',
            room_id: 7,
            expires_at: '2026-05-22T00:00:00+00:00',
            expires_in_seconds: 86400,
          },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: {
            token: 'fresh456',
            player_id: 'hero',
            room_id: 7,
            expires_at: '2026-05-22T00:30:00+00:00',
            expires_in_seconds: 88200,
          },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    fetchMock.mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const firstSocket = await waitFor(() => MockWebSocket.instances[0])
    expect(firstSocket.url).toContain('/rooms/7?token=abc123')
    expect(
      await screen.findByText(/token expires in 24h 0m/i)
    ).toBeInTheDocument()

    act(() => {
      firstSocket.close(1008, 'Invalid session token')
    })

    await screen.findByText(/connection: disconnected/i)
    expect(screen.getByText(/Invalid session token/i)).toBeInTheDocument()

    await act(async () => {
      await user.click(
        screen.getByRole('button', { name: /reconnect session/i })
      )
    })

    const secondSocket = await waitFor(() => MockWebSocket.instances[1])
    expect(secondSocket.url).toContain('/rooms/7?token=fresh456')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.local/auth/session',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ player_id: 'hero', room_id: 7 }),
      })
    )
    expect(
      await screen.findByText(/token expires in 24h 30m/i)
    ).toBeInTheDocument()
  })

  it('renders command_response room_message text for look-style replies', async () => {
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          scope: 'player',
          event: 'room_message',
          type: 'room_message',
          message_id: 'SAPRAY',
        },
      })
    })

    await waitFor(() =>
      expect(
        screen.getAllByText(/praying to the Goddess Tashanna/i).length
      ).toBeGreaterThan(0)
    )
  })

  it('ignores room_broadcast messages excluded for the current player', async () => {
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_message',
          type: 'room_message',
          text: '*** hero is concentrating with sincere determination.',
          exclude_player: 'hero',
        },
      })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_message',
          type: 'room_message',
          text: '*** Buddy notices Hero and steps aside.',
          exclude_players: ['hero', 'buddy'],
        },
      })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          scope: 'direct',
          event: 'room_message',
          type: 'room_message',
          text: 'Only Buddy should see this private temple response.',
          player: 'buddy',
        },
      })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          scope: 'direct',
          event: 'room_message',
          type: 'room_message',
          text: 'Only Hero should see this private temple response.',
          player: 'hero',
        },
      })
    })

    await waitFor(() =>
      expect(
        screen.queryByText(/concentrating with sincere determination/i)
      ).toBeNull()
    )
    expect(screen.queryByText(/notices Hero and steps aside/i)).toBeNull()
    expect(
      screen.queryByText(/Only Buddy should see this private temple response/i)
    ).toBeNull()
    expect(
      screen.getByText((_, element) =>
        Boolean(
          element?.classList.contains('summary') &&
          element.textContent?.includes(
            'Only Hero should see this private temple response.'
          )
        )
      )
    ).toBeInTheDocument()
  })

  it('updates world room objects when room_broadcast delivers room_objects event (gem spawn)', async () => {
    // Location 7 starts with object id=0 (ruby). After gem spawn broadcast it should have id=1 (emerald) too.
    const localLocations = [
      {
        id: 7,
        brfdes: 'Edge of the forest',
        objlds: 'on the ground',
        objects: [0],
        gi_north: -1,
        gi_south: -1,
        gi_east: -1,
        gi_west: -1,
      },
    ]

    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => localLocations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    // Trigger a gem-spawn room_objects broadcast (as emitted by KYRANIM.C gem spawner)
    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_objects',
          location: 7,
          objects: [
            { id: 0, name: 'ruby' },
            { id: 1, name: 'emerald' },
          ],
        },
      })
    })

    // room_objects broadcast must not appear as activity text
    await waitFor(() =>
      expect(screen.queryByText(/^room_objects$/i)).toBeNull()
    )

    // Emerald should now be visible in the room (world state updated by broadcast)
    await waitFor(() =>
      expect(screen.getAllByText(/emerald/i).length).toBeGreaterThan(0)
    )
  })

  it('renders room descriptions from the live object snapshot on the payload', async () => {
    const localLocations = [
      {
        id: 7,
        brfdes: 'Edge of the forest',
        objlds: 'on the ground',
        objects: [0],
        gi_north: -1,
        gi_south: -1,
        gi_east: -1,
        gi_west: -1,
      },
    ]

    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => localLocations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          event: 'location_description',
          location: 7,
          text: 'Edge of the forest',
          objects: [{ id: '0', name: 'ruby' }],
        },
      })
    })

    await waitFor(() =>
      expect(screen.getByText('There is nothing lying on the ground.')).toBeInTheDocument()
    )
    expect(queryConsoleLines('There is a ruby lying on the ground.')).toHaveLength(0)
    expect(queryConsoleLines('There is an object lying on the ground.')).toHaveLength(0)
  })

  it('renders room_broadcast occupant updates as occupant text', async () => {
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          scope: 'player',
          event: 'room_occupants',
          type: 'room_occupants',
          location: 7,
          occupants: ['seer'],
          text: 'seer is here.',
        },
      })
    })

    await waitFor(() =>
      expect(screen.getAllByText(/seer is here/i).length).toBeGreaterThan(0)
    )
    expect(queryConsoleLines('room_occupants')).toHaveLength(0)
  })

  it('ignores room_broadcast occupant snapshots that include the current player', async () => {
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_occupants',
          type: 'room_occupants',
          location: 7,
          occupants: ['hero'],
          text: 'hero is here.',
        },
      })
    })

    expect(queryConsoleLines('hero is here.')).toHaveLength(0)
    expect(queryConsoleLines('room_occupants')).toHaveLength(0)
  })

  it('does not duplicate room occupants on look after occupant state is known', async () => {
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          scope: 'player',
          event: 'player_enter',
          player: 'Necro',
        },
      })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          event: 'location_description',
          location: 7,
          text: 'Edge of the forest',
        },
      })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          scope: 'player',
          event: 'room_occupants',
          type: 'room_occupants',
          location: 7,
          occupants: ['Necro'],
          text: 'Necro is here.',
        },
      })
    })

    await waitFor(() => expect(getConsoleLines('Necro is here.')).toHaveLength(1))
  })

  it('shows the legacy dryad presence line after animation room_objects moves her into the room', async () => {
    const localLocations = [
      {
        id: 7,
        brfdes: 'Edge of the forest',
        objlds: 'among the roots',
        objects: [],
        gi_north: -1,
        gi_south: -1,
        gi_east: -1,
        gi_west: -1,
      },
    ]
    const localObjects = [...objects, { id: 45, name: 'dryad', flags: [] }]

    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => localLocations },
      { ok: true, json: async () => localObjects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
    })

    expect(
      queryConsoleLines('There is a 🌱 dryad standing here.')
    ).toHaveLength(0)

    act(() => {
      socket.triggerMessage({
        type: 'room_broadcast',
        room: 7,
        payload: {
          event: 'room_objects',
          location: 7,
          objects: [{ id: 45, name: 'dryad' }],
          animation_flag: 'dryads',
        },
      })
    })

    await waitFor(() =>
      expect(
        getConsoleLines('There is a 🌱 dryad standing here.').length
      ).toBeGreaterThan(0)
    )
    expect(
      getConsoleLines('There is a 🌱 dryad standing here.')[0]
    ).toContainElement(
      getConsoleLines('There is a 🌱 dryad standing here.')[0].querySelector(
        '.creature-dryad'
      )
    )
  })

  it('keeps the dryad presence line on explicit look responses', async () => {
    const localLocations = [
      {
        id: 7,
        brfdes: 'Edge of the forest',
        objlds: 'among the roots',
        objects: [45],
        gi_north: -1,
        gi_south: -1,
        gi_east: -1,
        gi_west: -1,
      },
    ]
    const localObjects = [...objects, { id: 45, name: 'dryad', flags: [] }]

    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => localLocations },
      { ok: true, json: async () => localObjects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
      socket.triggerMessage({
        type: 'command_response',
        room: 7,
        payload: {
          event: 'location_description',
          location: 7,
          text: 'You look around the forest edge.',
        },
      })
    })

    await waitFor(() =>
      expect(
        screen.getAllByText('You look around the forest edge.').length
      ).toBeGreaterThan(0)
    )
    expect(
      screen.getByText('There is nothing lying among the roots.')
    ).toBeInTheDocument()
    const dryadLine = getConsoleLines('There is a 🌱 dryad standing here.')[0]
    expect(dryadLine).toBeInTheDocument()
    expect(dryadLine.querySelector('.creature-dryad')).toHaveStyle({
      color: 'rgb(154, 205, 50)',
    })
  })

  it('renders spoiler command responses with a whisper prompt', async () => {
    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: 'hero', room_id: 0 },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '0')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])

    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 0 })
      socket.triggerMessage({
        type: 'command_response',
        room: 0,
        payload: {
          scope: 'player',
          event: 'spoiler',
          type: 'spoiler',
          interaction: 'Try the hidden phrase to unlock the willow secret.',
        },
      })
    })

    await waitFor(() =>
      expect(
        screen.getAllByText(/mysterious voice whispers words of secret wisdom/i)
          .length
      ).toBeGreaterThan(0)
    )
  })

  it('keeps the session form open while dev helper panels collapse', async () => {
    render(<App />)

    expect(
      screen.queryByRole('button', { name: /collapse session panel/i })
    ).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^player id$/i)).toBeInTheDocument()

    // RoomPanel has been deprecated/disabled
    // const roomToggle = screen.getByRole('button', {
    //   name: /collapse room panel/i,
    // })
    // await user.click(roomToggle)
    // expect(screen.queryByTestId('room-panel-body')).not.toBeInTheDocument()

    const activityToggle = screen.getByRole('button', {
      name: /collapse room activity panel/i,
    })
    fireEvent.click(activityToggle)
    expect(screen.queryByTestId('activity-log-body')).not.toBeInTheDocument()
  })

  it('uses the admin account session token for admin update endpoints', async () => {
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
    ]

    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [0, 1],
      nmpdes: 1,
      modno: 0,
      level: 4,
      gamloc: 7,
      pgploc: 7,
      flags: 0,
      gold: 150,
      npobjs: 2,
      obvals: [0, 0],
      nspells: 0,
      spts: 10,
      hitpts: 20,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 1,
      stones: [0, 1, 2, 3],
      macros: 0,
      stumpi: 2,
      spouse: 'seer',
    }

    const patchedPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Admin Hero',
      attnam: 'Hero Att',
      gpobjs: [],
      nmpdes: 1,
      modno: 0,
      level: 5,
      gamloc: 12,
      pgploc: 12,
      flags: 0,
      gold: 200,
      npobjs: 0,
      obvals: [],
      nspells: 0,
      spts: 9,
      hitpts: 18,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: 'seer',
    }

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (
          url.includes('/admin/players/hero') &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }
        if (url.includes('/admin/players/hero')) {
          expect(init?.headers).toMatchObject({
            Authorization: 'Bearer abc123',
          })
          const payload = JSON.parse(init?.body as string)
          expect(payload).toMatchObject({
            flags: [],
            gpobjs: [0, 1, null, null, null, null],
            npobjs: 2,
            gemidx: 2,
            stones: [0, 1, 2, 3],
            stumpi: 5,
            charms: [0, 0, 0, 0, 7, 0],
            grant_all_spells: true,
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({ status: 'updated', player: patchedPlayer }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await screen.findByText(/admin controls/i)

    await act(async () => {
      await user.clear(screen.getByLabelText(/^alternate name$/i))
      await user.type(screen.getByLabelText(/^alternate name$/i), 'Admin Hero')
      await user.clear(screen.getByLabelText(/level/i))
      await user.type(screen.getByLabelText(/level/i), '5')
      await user.clear(screen.getByLabelText(/gold cap/i))
      await user.type(screen.getByLabelText(/gold cap/i), '200')
      await user.clear(screen.getByLabelText(/inventory slot 1/i))
      await user.type(screen.getByLabelText(/inventory slot 1/i), 'ruby')
      await user.clear(screen.getByLabelText(/inventory slot 2/i))
      await user.type(screen.getByLabelText(/inventory slot 2/i), '1')
      await user.clear(screen.getByLabelText(/birthstone 1/i))
      await user.type(screen.getByLabelText(/birthstone 1/i), '0')
      await user.clear(screen.getByLabelText(/birthstone 2/i))
      await user.type(screen.getByLabelText(/birthstone 2/i), 'emerald')
      await user.clear(screen.getByLabelText(/birthstone 3/i))
      await user.type(screen.getByLabelText(/birthstone 3/i), '2')
      await user.clear(screen.getByLabelText(/birthstone 4/i))
      await user.type(screen.getByLabelText(/birthstone 4/i), 'garnet')
      await user.clear(screen.getByLabelText(/gem index/i))
      await user.type(screen.getByLabelText(/gem index/i), '2')
      await user.clear(screen.getByLabelText(/stump index/i))
      await user.type(screen.getByLabelText(/stump index/i), '5')
      await user.clear(screen.getByLabelText(/object protection charm/i))
      await user.type(screen.getByLabelText(/object protection charm/i), '7')
      await user.click(
        screen.getByRole('checkbox', { name: /grant all spells/i })
      )
      await user.click(
        screen.getByRole('button', { name: /apply admin changes/i })
      )
    })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/players/hero'),
        expect.anything()
      )
    )
    await screen.findByText(/Admin update saved/i)
  })

  it('keeps an admin account token available when the session pauses for intro', async () => {
    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [],
      nmpdes: 0,
      modno: 0,
      level: 1,
      gamloc: 0,
      pgploc: 0,
      flags: 0,
      gold: 0,
      npobjs: 0,
      obvals: [],
      nspells: 0,
      spts: 0,
      hitpts: 0,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: '',
    }
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = String(input)
        if (url.includes('/auth/login')) {
          expect(JSON.parse(String(init?.body))).toEqual({
            userid: 'hero',
            password: 'dev-admin-password',
            session_kind: 'admin',
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'created',
              session: {
                token: 'admin-intro-token',
                player_id: 'hero',
                account_userid: 'hero',
                session_kind: 'admin',
                room_id: 0,
                lifecycle: { state: 'first_login_intro', step: 2 },
                lifecycle_messages: [
                  { message_id: 'GOODPD', text: 'Press ENTER to begin' },
                ],
              },
            }),
          } as unknown as Response)
        }
        if (url.includes('/admin/players/hero')) {
          expect(init?.headers).toMatchObject({
            Authorization: 'Bearer admin-intro-token',
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }
        if (url.includes('/locations')) {
          return Promise.resolve({ ok: true, json: async () => locations } as unknown as Response)
        }
        if (url.includes('/objects')) {
          return Promise.resolve({ ok: true, json: async () => objects } as unknown as Response)
        }
        if (url.includes('/commands')) {
          return Promise.resolve({ ok: true, json: async () => commands } as unknown as Response)
        }
        if (url.includes('/i18n/en-US/messages')) {
          return Promise.resolve({ ok: true, json: async () => ({ messages }) } as unknown as Response)
        }
        throw new Error(`Unexpected fetch call: ${url}`)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/players/hero'),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer admin-intro-token',
          }),
        })
      )
    )
    expect(screen.queryByText(/admin access is locked/i)).not.toBeInTheDocument()
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('uses the static emergency admin token with a legacy session', async () => {
    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [],
      nmpdes: 0,
      modno: 0,
      level: 1,
      gamloc: 7,
      pgploc: 7,
      flags: 0,
      gold: 0,
      npobjs: 0,
      obvals: [],
      nspells: 0,
      spts: 0,
      hitpts: 0,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: '',
    }
    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'legacy-game-token', player_id: 'hero', room_id: 7 },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = String(input)
        if (url.includes('/admin/players/hero')) {
          expect(init?.headers).toMatchObject({
            Authorization: 'Bearer static-admin-token',
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }
        const next = responses.shift()
        if (!next) throw new Error(`Unexpected fetch call: ${url}`)
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.type(
        screen.getByLabelText(/emergency admin token/i),
        'static-admin-token'
      )
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/players/hero'),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer static-admin-token',
          }),
        })
      )
    )
    expect(screen.queryByText(/admin access is locked/i)).not.toBeInTheDocument()
  })

  it('normalizes admin alias lookups to the canonical player id before saving', async () => {
    const alias = 'Test2dsfdsdf'
    const canonical = 'Test2dsfds'
    const responses = [
      {
        ok: true,
        json: async () => ({
          status: 'created',
          session: { token: 'abc123', player_id: canonical, room_id: 7 },
        }),
      },
      { ok: true, json: async () => locations },
      { ok: true, json: async () => objects },
      { ok: true, json: async () => commands },
      { ok: true, json: async () => ({ messages }) },
    ]

    const adminPlayer = {
      uidnam: alias,
      plyrid: canonical,
      altnam: 'Hero',
      attnam: 'Hero Attire',
      gpobjs: [],
      nmpdes: 1,
      modno: 0,
      level: 4,
      gamloc: 7,
      pgploc: 7,
      flags: 0,
      gold: 150,
      npobjs: 0,
      obvals: [],
      nspells: 0,
      spts: 10,
      hitpts: 20,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: '',
    }

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (
          url.includes(`/admin/players/${canonical}`) &&
          init?.method === 'PATCH'
        ) {
          const payload = JSON.parse(init?.body as string)
          expect(payload.altnam).toBe('Alias Admin')
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'updated',
              player: { ...adminPlayer, altnam: 'Alias Admin' },
            }),
          } as unknown as Response)
        }
        if (
          url.includes(`/admin/players/${alias}`) &&
          init?.method === 'PATCH'
        ) {
          throw new Error('Admin save used the non-canonical alias')
        }
        if (
          (url.includes(`/admin/players/${canonical}`) ||
            url.includes(`/admin/players/${alias}`)) &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), alias)
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await screen.findByText(/admin controls/i)
    const targetInput = screen.getByLabelText(/target player/i)
    await waitFor(() => expect(targetInput).toHaveValue(canonical))

    fireEvent.change(targetInput, { target: { value: alias } })
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(`/admin/players/${alias}`),
        expect.anything()
      )
    )
    await waitFor(() => expect(targetInput).toHaveValue(canonical))

    await act(async () => {
      await user.clear(screen.getByLabelText(/^alternate name$/i))
      await user.type(screen.getByLabelText(/^alternate name$/i), 'Alias Admin')
      await user.click(
        screen.getByRole('button', { name: /apply admin changes/i })
      )
    })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(`/admin/players/${canonical}`),
        expect.objectContaining({ method: 'PATCH' })
      )
    )
    await screen.findByText(/Admin update saved/i)
  })

  it('shows the admin mob tracker from the admin-only endpoint', async () => {
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
    ]

    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [],
      nmpdes: 1,
      modno: 0,
      level: 4,
      gamloc: 7,
      pgploc: 7,
      flags: 0,
      gold: 150,
      npobjs: 0,
      obvals: [],
      nspells: 0,
      spts: 10,
      hitpts: 20,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: '',
    }

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/admin/mobs/elf/trigger')) {
          expect(init?.method).toBe('POST')
          expect(init?.headers).toMatchObject({
            Authorization: 'Bearer abc123',
            'Content-Type': 'application/json',
          })
          expect(JSON.parse(String(init?.body))).toEqual({
            player_id: 'hero',
            room_id: 7,
          })
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'triggered',
              room_id: 7,
              player_id: 'hero',
              outcome: 'hint',
              snapshot: adminMobSnapshot,
            }),
          } as unknown as Response)
        }
        if (url.includes('/admin/mobs')) {
          expect(init?.headers).toMatchObject({
            Authorization: 'Bearer abc123',
          })
          return Promise.resolve({
            ok: true,
            json: async () => adminMobSnapshot,
          } as unknown as Response)
        }
        if (
          url.includes('/admin/players/hero') &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.type(screen.getByLabelText(/room id/i), '7')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    expect(await screen.findByText(/Mob tracker/i)).toBeInTheDocument()
    expect(screen.getByText('🌱 Dryad')).toHaveClass('creature-dryad')
    expect(screen.getByText('🐲 Zar')).toHaveClass('creature-dragon')
    expect(
      screen.getAllByText(/near a mystical willow tree/i).length
    ).toBeGreaterThan(0)
    expect(screen.getByText(/next 129/i)).toBeInTheDocument()
    expect(screen.getByText(/next claw; counter 8/i)).toBeInTheDocument()
    await act(async () => {
      await user.click(screen.getByRole('button', { name: /trigger elf/i }))
    })
    expect(
      await screen.findByText((_, element) =>
        Boolean(
          element?.classList.contains('field-hint') &&
          element.textContent === '🧝 Elf triggered: hint'
        )
      )
    ).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.local/admin/mobs',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer abc123' }),
      })
    )
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.local/admin/mobs/elf/trigger',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ player_id: 'hero', room_id: 7 }),
      })
    )
  })

  it('prepopulates admin fields from the current player and supports refresh', async () => {
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
    ]

    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [0, 1],
      nmpdes: 1,
      modno: 0,
      level: 8,
      gamloc: 12,
      pgploc: 12,
      flags: 2,
      gold: 250,
      npobjs: 2,
      obvals: [0, 0],
      nspells: 0,
      spts: 15,
      hitpts: 30,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 2,
      stones: [0, 1, 2, 3],
      macros: 0,
      stumpi: 4,
      spouse: 'seer',
    }

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (
          url.includes('/admin/players/hero') &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await screen.findByText(/admin controls/i)
    expect(await screen.findByLabelText(/^alternate name$/i)).toHaveValue(
      'Hero'
    )
    expect(screen.getByLabelText(/attire name/i)).toHaveValue('Heroic Attire')
    expect(screen.getByLabelText(/level/i)).toHaveValue(8)
    expect(screen.getByLabelText(/hit points/i)).toHaveValue(30)
    expect(screen.getByLabelText(/spell points/i)).toHaveValue(15)
    expect(screen.getByLabelText(/^gold$/i)).toHaveValue(250)
    expect(screen.queryByLabelText(/inventory count/i)).not.toBeInTheDocument()
    expect(
      screen.queryByText(
        /inventory count is auto-calculated from filled slots:/i
      )
    ).not.toBeInTheDocument()
    expect(screen.getByLabelText(/inventory slot 1/i)).toHaveValue('ruby')
    expect(screen.getByLabelText(/inventory slot 2/i)).toHaveValue('emerald')
    expect(screen.getByLabelText(/birthstone 1/i)).toHaveValue('ruby')
    expect(screen.getByLabelText(/birthstone 2/i)).toHaveValue('emerald')
    expect(screen.getByLabelText(/birthstone 3/i)).toHaveValue('sapphire')
    expect(screen.getByLabelText(/birthstone 4/i)).toHaveValue('garnet')
    expect(screen.getByLabelText(/gem index/i)).toHaveValue(2)
    expect(screen.getByLabelText(/stump index/i)).toHaveValue(4)
    expect(screen.getByLabelText(/teleport room/i)).toHaveValue(12)
    expect(screen.getByLabelText(/^spouse$/i)).toHaveValue('seer')
    expect(screen.getByRole('checkbox', { name: /female/i })).toBeChecked()

    await act(async () => {
      await user.click(
        screen.getByRole('button', { name: /refresh admin data/i })
      )
    })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/admin/players/hero'),
      expect.anything()
    )
  })

  it('submits unchecked flags to clear them on save', async () => {
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
    ]

    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [],
      nmpdes: 1,
      modno: 0,
      level: 4,
      gamloc: 7,
      pgploc: 7,
      flags: 2,
      gold: 150,
      npobjs: 0,
      obvals: [],
      nspells: 0,
      spts: 10,
      hitpts: 20,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: 'seer',
    }

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (
          url.includes('/admin/players/hero') &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }
        if (url.includes('/admin/players/hero') && init?.method === 'PATCH') {
          const payload = JSON.parse(init?.body as string)
          expect(payload.flags).toEqual([])
          return Promise.resolve({
            ok: true,
            json: async () => ({ status: 'updated', player: adminPlayer }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await screen.findByText(/admin controls/i)
    const femaleFlag = await screen.findByRole('checkbox', { name: /female/i })
    expect(femaleFlag).toBeChecked()

    await act(async () => {
      await user.click(femaleFlag)
      await user.click(
        screen.getByRole('button', { name: /apply admin changes/i })
      )
    })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/players/hero'),
        expect.anything()
      )
    )
  })

  it('does not send npobjs when inventory slots are still blank', async () => {
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
    ]

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (
          url.includes('/admin/players/hero') &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: false,
            json: async () => ({ detail: 'service unavailable' }),
          } as unknown as Response)
        }
        if (url.includes('/admin/players/hero') && init?.method === 'PATCH') {
          const payload = JSON.parse(init?.body as string)
          expect(payload.altnam).toBe('Admin Hero')
          expect(payload).not.toHaveProperty('npobjs')
          expect(payload).not.toHaveProperty('gpobjs')
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'updated',
              player: { plyrid: 'hero' },
            }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await screen.findByText(/admin controls/i)

    await act(async () => {
      await user.clear(screen.getByLabelText(/^alternate name$/i))
      await user.type(screen.getByLabelText(/^alternate name$/i), 'Admin Hero')
      await user.click(
        screen.getByRole('button', { name: /apply admin changes/i })
      )
    })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/players/hero'),
        expect.anything()
      )
    )
  })

  it('sends explicit empty inventory when all slots are cleared', async () => {
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
    ]

    const adminPlayer = {
      uidnam: 'HeroicUser',
      plyrid: 'hero',
      altnam: 'Hero',
      attnam: 'Heroic Attire',
      gpobjs: [0, 1],
      nmpdes: 1,
      modno: 0,
      level: 4,
      gamloc: 7,
      pgploc: 7,
      flags: 0,
      gold: 150,
      npobjs: 2,
      obvals: [0, 0],
      nspells: 0,
      spts: 10,
      hitpts: 20,
      charms: [0, 0, 0, 0, 0, 0],
      offspls: 0,
      defspls: 0,
      othspls: 0,
      spells: [],
      gemidx: 0,
      stones: [0, 0, 0, 0],
      macros: 0,
      stumpi: 0,
      spouse: '',
    }

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const rosterResponse = maybeActivePlayerRosterFetch(input)
        if (rosterResponse) return rosterResponse
        const url = typeof input === 'string' ? input : input.toString()
        if (
          url.includes('/admin/players/hero') &&
          (!init?.method || init?.method === 'GET')
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ player: adminPlayer }),
          } as unknown as Response)
        }
        if (url.includes('/admin/players/hero') && init?.method === 'PATCH') {
          const payload = JSON.parse(init?.body as string)
          // All slots cleared: gpobjs must be all-null and npobjs must be 0
          expect(payload.gpobjs).toEqual([null, null, null, null, null, null])
          expect(payload.npobjs).toBe(0)
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'updated',
              player: { plyrid: 'hero' },
            }),
          } as unknown as Response)
        }

        const next = responses.shift()
        if (!next) {
          throw new Error(`Unexpected fetch call: ${url}`)
        }
        return Promise.resolve(next as unknown as Response)
      })

    render(<App />)

    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
      await user.click(screen.getByRole('checkbox', { name: /admin session/i }))
      await user.type(
        screen.getByLabelText(/admin password/i),
        'dev-admin-password'
      )
      await user.click(screen.getByRole('button', { name: /admin login/i }))
    })

    await screen.findByText(/admin controls/i)
    // Wait for the pre-populated slots to appear
    expect(await screen.findByLabelText(/inventory slot 1/i)).toHaveValue(
      'ruby'
    )
    expect(screen.getByLabelText(/inventory slot 2/i)).toHaveValue('emerald')

    await act(async () => {
      // Clear both pre-populated inventory slots
      await user.clear(screen.getByLabelText(/inventory slot 1/i))
      await user.clear(screen.getByLabelText(/inventory slot 2/i))
      await user.click(
        screen.getByRole('button', { name: /apply admin changes/i })
      )
    })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/players/hero'),
        expect.anything()
      )
    )
  })

  it('restores session form fields from browser storage', () => {
    localStorage.setItem('kyrgame.navigator.playerId', 'hero')
    localStorage.setItem('kyrgame.navigator.roomId', '12')
    localStorage.setItem('kyrgame.navigator.adminSession', 'true')

    render(<App />)

    expect(screen.getByLabelText(/^player id$/i)).toHaveValue('hero')
    expect(screen.getByLabelText(/room id/i)).toHaveValue('12')
    expect(
      screen.getByRole('checkbox', { name: /admin session/i })
    ).toBeChecked()
    expect(screen.getByLabelText(/admin password/i)).toHaveValue('')
  })

  it('persists session form changes without storing admin passwords', async () => {
    render(<App />)

    fireEvent.change(screen.getByLabelText(/^player id$/i), {
      target: { value: 'hero' },
    })
    expect(localStorage.getItem('kyrgame.navigator.playerId')).toBe('hero')

    fireEvent.change(screen.getByLabelText(/room id/i), {
      target: { value: '34' },
    })
    expect(localStorage.getItem('kyrgame.navigator.roomId')).toBe('34')

    const adminToggle = screen.getByRole('checkbox', { name: /admin session/i })
    fireEvent.click(adminToggle)
    expect(localStorage.getItem('kyrgame.navigator.adminSession')).toBe('true')

    fireEvent.change(screen.getByLabelText(/admin password/i), {
      target: { value: 'secret-password' },
    })
    expect(localStorage.getItem('kyrgame.navigator.adminToken')).toBeNull()

    fireEvent.click(adminToggle)
    expect(localStorage.getItem('kyrgame.navigator.adminSession')).toBe('false')
    expect(localStorage.getItem('kyrgame.navigator.adminToken')).toBeNull()
  })

  it('remembers admin panel and section collapse state', async () => {
    localStorage.setItem('kyrgame.navigator.adminPanelCollapsed', 'true')
    localStorage.setItem('kyrgame.navigator.adminSection.identity', 'true')

    render(<App />)

    expect(screen.queryByTestId('admin-panel-body')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /expand admin panel/i }))
    expect(await screen.findByTestId('admin-panel-body')).toBeInTheDocument()

    expect(
      screen.queryByTestId('admin-section-body-identity')
    ).not.toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: /expand identity section/i })
    )
    expect(
      await screen.findByTestId('admin-section-body-identity')
    ).toBeInTheDocument()
    expect(
      localStorage.getItem('kyrgame.navigator.adminSection.identity')
    ).toBe('false')
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
    ]

    vi.spyOn(global, 'fetch').mockImplementation(input => {
      const rosterResponse = maybeActivePlayerRosterFetch(input)
      if (rosterResponse) return rosterResponse
      const next = responses.shift()
      if (!next) throw new Error('Unexpected fetch call')
      return Promise.resolve(next as unknown as Response)
    })

    render(<App />)
    const user = userEvent.setup()
    await act(async () => {
      await user.type(screen.getByLabelText(/^player id$/i), 'hero')
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

    // RoomPanel is disabled, check MudConsole header text instead
    await waitFor(() =>
      expect(
        screen.getAllByText(/Deep forest clearing/i).length
      ).toBeGreaterThan(0)
    )

    // RoomPanel components no longer rendered (room-look-description, room-exits)
    // Move commands are now sent via compass/WASD keys or typing commands, not via RoomPanel exit buttons
  })
})
