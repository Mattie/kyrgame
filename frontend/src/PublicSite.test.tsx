import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('./config/endpoints', () => ({
  getApiBaseUrl: () => 'http://api.local',
  getWebSocketUrl: () => 'ws://ws.local',
}))

class MockWebSocket {
  onopen: (() => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null

  constructor() {
    setTimeout(() => this.onopen?.(), 0)
  }

  send() {}

  close(code = 1000, reason = '') {
    this.onclose?.({ code, reason })
  }
}

const publicActivity = {
  active: [
    {
      player_id: 'Nyx',
      display_name: 'Nyx Alt',
      level: 11,
      rank_title: 'Blue Wizard',
      wizard_symbol: '🧙‍♀️',
      spellbook_count: 8,
      active: true,
      last_seen: '2026-06-05T12:00:50+00:00',
      connected_at: '2026-06-05T12:00:45+00:00',
      connection_duration_seconds: 15,
    },
    {
      player_id: 'Lyra',
      display_name: 'Lyra Alt',
      level: 25,
      rank_title: 'Arch-Mage of Legends',
      wizard_symbol: '🧙‍♂️',
      spellbook_count: 18,
      active: true,
      last_seen: '2026-06-05T12:00:00+00:00',
      connected_at: '2026-06-05T11:57:45+00:00',
      connection_duration_seconds: 135,
    },
  ],
  recent: [
    {
      player_id: 'Rook',
      display_name: 'Rook Alt',
      level: 9,
      rank_title: 'Sorcerer',
      wizard_symbol: '🧙‍♂️',
      spellbook_count: 7,
      active: false,
      last_seen: '2026-06-04T12:00:00+00:00',
      connected_at: null,
      connection_duration_seconds: null,
    },
  ],
}

const leaderboard = {
  players: [
    {
      player_id: 'Zed',
      display_name: 'Zed Alt',
      level: 25,
      rank_title: 'Arch-Mage of Legends',
      wizard_symbol: '🧙‍♂️',
      spellbook_count: 19,
      active: false,
      last_seen: '2026-06-04T12:00:00+00:00',
      connected_at: null,
      connection_duration_seconds: null,
    },
    {
      player_id: 'Lyra',
      display_name: 'Lyra Alt',
      level: 25,
      rank_title: 'Arch-Mage of Legends',
      wizard_symbol: '🧙‍♂️',
      spellbook_count: 18,
      active: true,
      last_seen: '2026-06-05T12:00:00+00:00',
      connected_at: '2026-06-05T11:57:45+00:00',
      connection_duration_seconds: 135,
    },
  ],
}

const jsonResponse = (payload: unknown) =>
  ({
    ok: true,
    headers: { get: () => 'application/json' },
    json: async () => payload,
  }) as unknown as Response

const mockFetch = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  if (url.endsWith('/public/player-activity')) {
    return jsonResponse(publicActivity)
  }
  if (url.endsWith('/public/leaderboard')) {
    return jsonResponse(leaderboard)
  }
  return jsonResponse({})
})

describe('public site routes', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    Object.defineProperty(global, 'WebSocket', {
      writable: true,
      value: MockWebSocket,
    })
    Object.defineProperty(global, 'fetch', {
      writable: true,
      value: mockFetch,
    })
    mockFetch.mockClear()
    localStorage.clear()
    window.history.replaceState(null, '', '/')
  })

  it('renders the landing page with public activity and a leaderboard preview', async () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'Kyrandia' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /start playing/i })).toHaveAttribute('href', '/enter')
    expect(await screen.findAllByText('Lyra Alt')).toHaveLength(2)
    expect(screen.getAllByText(/Arch-Mage of Legends/).length).toBeGreaterThan(0)
    expect(screen.getByText('Rook Alt')).toBeInTheDocument()
    expect(screen.getByText('Zed Alt')).toBeInTheDocument()
    expect(screen.queryByText('Admin controls')).not.toBeInTheDocument()
  })

  it('renders the enter page as a player login interstitial', () => {
    window.history.replaceState(null, '', '/enter')

    render(<App />)

    expect(screen.getByRole('heading', { name: /enter kyrandia/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Player ID')).toBeInTheDocument()
    expect(screen.getByLabelText('Claim new Player-ID')).toBeInTheDocument()
    expect(screen.queryByLabelText('Admin token')).not.toBeInTheDocument()
  })

  it('renders a clean player console on play and keeps admin tools on admin', async () => {
    window.history.replaceState(null, '', '/play')
    const user = userEvent.setup()

    const { unmount } = render(<App />)

    expect(screen.getByRole('heading', { name: /play kyrandia/i })).toBeInTheDocument()
    expect(screen.getByTestId('game-panel-fire-border')).toBeInTheDocument()
    expect(screen.getByLabelText('Player ID')).toBeInTheDocument()
    expect(screen.getByLabelText('Claim new Player-ID')).toBeInTheDocument()
    expect(screen.queryByText('Admin controls')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Admin token')).not.toBeInTheDocument()
    expect(screen.queryByText('Events')).not.toBeInTheDocument()
    const playActiveButton = await screen.findByRole('button', { name: /active players: 2/i })
    await user.click(playActiveButton)
    const playRoster = screen.getByRole('dialog', { name: /active players/i })
    expect(within(playRoster).getByText('Nyx Alt')).toBeInTheDocument()
    expect(within(playRoster).getByText('Blue Wizard')).toBeInTheDocument()
    expect(within(playRoster).getByText('Lyra Alt')).toBeInTheDocument()
    expect(within(playRoster).getByText('2m 15s')).toBeInTheDocument()
    const firstRosterRow = within(playRoster).getAllByTestId('active-player-row')[0]
    expect(firstRosterRow).toHaveTextContent(/🧙‍♀️\s*Nyx Alt/)
    expect(firstRosterRow).toHaveTextContent('Blue Wizard')
    expect(firstRosterRow).toHaveTextContent('15s')
    const playRosterNames = within(playRoster)
      .getAllByTestId('active-player-name')
      .map((entry) => entry.textContent)
    expect(playRosterNames).toEqual(['Nyx Alt', 'Lyra Alt'])
    await user.click(within(playRoster).getByRole('button', { name: /close active player list/i }))
    expect(screen.queryByRole('dialog', { name: /active players/i })).not.toBeInTheDocument()

    unmount()
    window.history.replaceState(null, '', '/admin')
    render(<App />)

    expect(screen.getByRole('heading', { name: /kyrandia admin/i })).toBeInTheDocument()
    expect(screen.getByText('Admin controls')).toBeInTheDocument()
    expect(screen.getByText('Events')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /active players: 2/i })).toBeInTheDocument()
  })

  it('renders about and leaderboard pages from the public route set', async () => {
    window.history.replaceState(null, '', '/about')
    const { unmount } = render(<App />)

    expect(screen.getByRole('heading', { name: /about kyrandia/i })).toBeInTheDocument()
    expect(screen.getByText(/MajorBBS\/Worldgroup/i)).toBeInTheDocument()

    unmount()
    window.history.replaceState(null, '', '/leaderboard')
    render(<App />)

    expect(screen.getByRole('heading', { name: /leaderboard/i })).toBeInTheDocument()
    expect(await screen.findByText('Zed Alt')).toBeInTheDocument()
    expect(screen.getByText('19 spells')).toBeInTheDocument()
  })

  it('shows a clean public-data error when the API returns HTML', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      headers: { get: () => 'text/html' },
      json: async () => {
        throw new Error('Unexpected token <')
      },
    } as unknown as Response)

    render(<App />)

    expect(await screen.findByText('Unable to load public game data')).toBeInTheDocument()
    expect(screen.queryByText(/Unexpected token/)).not.toBeInTheDocument()
  })
})
