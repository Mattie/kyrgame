import { act, render, screen, waitFor } from '@testing-library/react'
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
  onclose: (() => void) | null = null

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

  close() {
    this.onclose?.()
  }

  triggerMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
})

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
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    MockWebSocket.instances.length = 0
    localStorage.clear()
  })

  it('creates a session, caches world data, and streams room activity', async () => {
    let responses = [
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

    vi.spyOn(global, 'fetch').mockImplementation(() => {
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
      expect(
        screen.getAllByText(/Edge of the forest/i).length
      ).toBeGreaterThan(0)
    )

    // RoomPanel components are no longer rendered (room-commands, room-look-description)
    // The room information is now only shown in MudConsole

    expect(screen.getAllByText(/seer is here/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/appeared from the west/i).length).toBeGreaterThan(0)
    // ruby appears in MudConsole (initial room description with GemstoneText styling)
    expect(screen.getAllByText(/ruby/i).length).toBeGreaterThan(0)

    // message_id fallback is resolved via cached world messages
    expect(
      screen.getAllByText(/praying to the Goddess Tashanna/i).length
    ).toBeGreaterThan(0)
  })

  it('renders command_response room_message text for look-style replies', async () => {
    let responses = [
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

    vi.spyOn(global, 'fetch').mockImplementation(() => {
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
    let responses = [
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

    vi.spyOn(global, 'fetch').mockImplementation(() => {
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
    })

    await waitFor(() =>
      expect(screen.queryByText(/concentrating with sincere determination/i)).toBeNull()
    )
  })

  it('renders spoiler command responses with a whisper prompt', async () => {
    let responses = [
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

    vi.spyOn(global, 'fetch').mockImplementation(() => {
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
        screen.getAllByText(/mysterious voice whispers words of secret wisdom/i).length
      ).toBeGreaterThan(0)
    )
  })

  it('collapses dev helper panels to reclaim space', async () => {
    render(<App />)
    const user = userEvent.setup()

    const sessionToggle = screen.getByRole('button', {
      name: /collapse session panel/i,
    })
    await user.click(sessionToggle)
    expect(screen.queryByLabelText(/^player id$/i)).not.toBeInTheDocument()

    // RoomPanel has been deprecated/disabled
    // const roomToggle = screen.getByRole('button', {
    //   name: /collapse room panel/i,
    // })
    // await user.click(roomToggle)
    // expect(screen.queryByTestId('room-panel-body')).not.toBeInTheDocument()

    const activityToggle = screen.getByRole('button', {
      name: /collapse room activity panel/i,
    })
    await user.click(activityToggle)
    expect(screen.queryByTestId('activity-log-body')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /expand session panel/i }))
    expect(screen.getByLabelText(/^player id$/i)).toBeInTheDocument()
  })

  it('stores an admin token and calls admin update endpoints', async () => {
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

    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/admin/players/hero') && (!init?.method || init?.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ player: adminPlayer }),
        } as unknown as Response)
      }
      if (url.includes('/admin/players/hero')) {
        expect(init?.headers).toMatchObject({ Authorization: 'Bearer dev-admin' })
        const payload = JSON.parse(init?.body as string)
        expect(payload).toMatchObject({
          flags: [],
          gpobjs: [0, 1, null, null, null, null],
          npobjs: 2,
          gemidx: 2,
          stones: [0, 1, 2, 3],
          stumpi: 5,
          charms: [0, 0, 0, 0, 7, 0],
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
      await user.type(screen.getByLabelText(/admin token/i), 'dev-admin')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])
    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
    })

    await screen.findByText(/admin controls/i)

    await act(async () => {
      await user.clear(screen.getByLabelText(/^alternate name$/i))
      await user.type(screen.getByLabelText(/^alternate name$/i), 'Admin Hero')
      await user.clear(screen.getByLabelText(/level/i))
      await user.type(screen.getByLabelText(/level/i), '5')
      await user.clear(screen.getByLabelText(/gold cap/i))
      await user.type(screen.getByLabelText(/gold cap/i), '200')
      await user.clear(screen.getByLabelText(/inventory count/i))
      await user.type(screen.getByLabelText(/inventory count/i), '2')
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
      await user.click(screen.getByRole('button', { name: /apply admin changes/i }))
    })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/admin/players/hero'), expect.anything()))
    await screen.findByText(/Admin update saved/i)
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

    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/admin/players/hero') && (!init?.method || init?.method === 'GET')) {
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
      await user.type(screen.getByLabelText(/admin token/i), 'dev-admin')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])
    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
    })

    await screen.findByText(/admin controls/i)
    expect(await screen.findByLabelText(/^alternate name$/i)).toHaveValue('Hero')
    expect(screen.getByLabelText(/attire name/i)).toHaveValue('Heroic Attire')
    expect(screen.getByLabelText(/level/i)).toHaveValue(8)
    expect(screen.getByLabelText(/hit points/i)).toHaveValue(30)
    expect(screen.getByLabelText(/spell points/i)).toHaveValue(15)
    expect(screen.getByLabelText(/^gold$/i)).toHaveValue(250)
    expect(screen.getByLabelText(/inventory count/i)).toHaveValue(2)
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
      await user.click(screen.getByRole('button', { name: /refresh admin data/i }))
    })

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/admin/players/hero'), expect.anything())
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

    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/admin/players/hero') && (!init?.method || init?.method === 'GET')) {
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
      await user.type(screen.getByLabelText(/admin token/i), 'dev-admin')
      await user.click(screen.getByRole('button', { name: /start session/i }))
    })

    const socket = await waitFor(() => MockWebSocket.instances[0])
    act(() => {
      socket.triggerMessage({ type: 'room_welcome', room: 7 })
    })

    await screen.findByText(/admin controls/i)
    const femaleFlag = await screen.findByRole('checkbox', { name: /female/i })
    expect(femaleFlag).toBeChecked()

    await act(async () => {
      await user.click(femaleFlag)
      await user.click(screen.getByRole('button', { name: /apply admin changes/i }))
    })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/admin/players/hero'), expect.anything()))
  })

  it('restores session form fields from browser storage', () => {
    localStorage.setItem('kyrgame.navigator.playerId', 'hero')
    localStorage.setItem('kyrgame.navigator.roomId', '12')
    localStorage.setItem('kyrgame.navigator.adminSession', 'true')
    localStorage.setItem('kyrgame.navigator.adminToken', 'stored-token')

    render(<App />)

    expect(screen.getByLabelText(/^player id$/i)).toHaveValue('hero')
    expect(screen.getByLabelText(/room id/i)).toHaveValue('12')
    expect(screen.getByRole('checkbox', { name: /admin session/i })).toBeChecked()
    expect(screen.getByLabelText(/admin token/i)).toHaveValue('stored-token')
  })

  it('persists session form changes and clears stored admin token when disabled', async () => {
    render(<App />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/^player id$/i), 'hero')
    expect(localStorage.getItem('kyrgame.navigator.playerId')).toBe('hero')

    await user.type(screen.getByLabelText(/room id/i), '34')
    expect(localStorage.getItem('kyrgame.navigator.roomId')).toBe('34')

    const adminToggle = screen.getByRole('checkbox', { name: /admin session/i })
    await user.click(adminToggle)
    expect(localStorage.getItem('kyrgame.navigator.adminSession')).toBe('true')

    await user.type(screen.getByLabelText(/admin token/i), 'secret-token')
    expect(localStorage.getItem('kyrgame.navigator.adminToken')).toBe('secret-token')

    await user.click(adminToggle)
    expect(localStorage.getItem('kyrgame.navigator.adminSession')).toBe('false')
    expect(localStorage.getItem('kyrgame.navigator.adminToken')).toBeNull()
  })

  it('remembers admin panel and section collapse state', async () => {
    localStorage.setItem('kyrgame.navigator.adminPanelCollapsed', 'true')
    localStorage.setItem('kyrgame.navigator.adminSection.identity', 'true')

    render(<App />)

    expect(screen.queryByTestId('admin-panel-body')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /expand admin panel/i }))
    expect(await screen.findByTestId('admin-panel-body')).toBeInTheDocument()

    expect(screen.queryByTestId('admin-section-body-identity')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /expand identity section/i }))
    expect(await screen.findByTestId('admin-section-body-identity')).toBeInTheDocument()
    expect(localStorage.getItem('kyrgame.navigator.adminSection.identity')).toBe('false')
  })

  it('dispatches move commands and updates room details on location change', async () => {
    let responses = [
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

    vi.spyOn(global, 'fetch').mockImplementation(() => {
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
