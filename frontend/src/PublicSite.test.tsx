import { fireEvent, render, screen, within } from '@testing-library/react'
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

const failedJsonResponse = (payload: unknown, status = 503) =>
  ({
    ok: false,
    status,
    headers: { get: () => 'application/json' },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  }) as unknown as Response

const mockFetch = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  if (url.endsWith('/public/player-activity')) {
    return jsonResponse(publicActivity)
  }
  if (url.endsWith('/public/leaderboard')) {
    return jsonResponse(leaderboard)
  }
  if (url.endsWith('/public/player-id/Hero')) {
    return jsonResponse({
      player_id: 'Hero',
      canonical_player_id: 'hero',
      valid: true,
      exists: true,
      available: false,
      reserved: false,
      status: 'existing',
    })
  }
  if (url.endsWith('/public/player-id/Avalon')) {
    return jsonResponse({
      player_id: 'Avalon',
      canonical_player_id: 'Avalon',
      valid: true,
      exists: false,
      available: true,
      reserved: false,
      status: 'available',
    })
  }
  if (url.endsWith('/public/player-id/Glitch')) {
    return failedJsonResponse({ detail: 'lookup unavailable' })
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
    const { container } = render(<App />)

    expect(screen.getByRole('img', { name: /kyrandia online edition/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^home$/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: /^about$/i })).toHaveAttribute('href', '/about')
    expect(screen.getByRole('link', { name: /^leaderboard$/i })).toHaveAttribute(
      'href',
      '/leaderboard'
    )
    expect(screen.getByRole('link', { name: /^enter kyrandia/i })).toHaveAttribute(
      'href',
      '/enter'
    )
    expect(screen.queryByRole('link', { name: /^admin$/i })).not.toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: /legends pass and time goes by/i })
    ).toBeInTheDocument()
    expect(screen.getByText(/begin at the willow/i)).toBeInTheDocument()
    expect(screen.getByText(/no matter where you go/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /begin your journey/i })).toHaveAttribute(
      'href',
      '/enter'
    )
    expect(screen.getByRole('link', { name: /learn more/i })).toHaveAttribute('href', '/about')
    expect(await screen.findAllByText('Lyra Alt')).toHaveLength(2)
    expect(screen.getAllByText(/Arch-Mage of Legends/).length).toBeGreaterThan(0)
    expect(screen.getByText('Rook Alt')).toBeInTheDocument()
    expect(screen.getByText('Zed Alt')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Active Players' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Recently Active' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Leaderboard' })).toBeInTheDocument()
    expect(
      screen.getByText("If you don't believe in legends, you haven't seen Kyrandia...")
    ).toBeInTheDocument()
    expect(screen.getAllByText('Active Players')).toHaveLength(1)
    expect(screen.getAllByText('Recently Active')).toHaveLength(1)
    expect(screen.getAllByText('Leaderboard')).toHaveLength(2)
    expect(screen.queryByText(/\d+ spells?/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Admin controls')).not.toBeInTheDocument()
    const homeMarkup = container.querySelector('.landing-page')?.innerHTML ?? ''
    expect(homeMarkup).toContain('<!-- Slayer must die... -->')
    expect(homeMarkup.indexOf('<!-- Slayer must die... -->')).toBeLessThan(
      homeMarkup.indexOf('site-hero')
    )
  })

  it('renders the enter page as a welcoming player login interstitial', async () => {
    window.history.replaceState(null, '', '/enter')

    render(<App />)

    expect(screen.getByRole('heading', { name: /enter kyrandia/i })).toBeInTheDocument()
    expect(screen.getByText(/The willow is waiting/i)).toBeInTheDocument()
    expect(screen.getByText(/Google sign-in is coming soon/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Player ID')).toBeInTheDocument()
    expect(screen.queryByLabelText('Claim new Player-ID')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Player ID'), { target: { value: 'Hero' } })
    expect(await screen.findByText(/Hero is already known in Kyrandia/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Login as Hero' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Admin token')).not.toBeInTheDocument()
  })

  it('guides new player IDs toward character creation from the enter page', async () => {
    window.history.replaceState(null, '', '/enter')

    render(<App />)

    const playerId = screen.getByLabelText('Player ID')
    fireEvent.change(playerId, { target: { value: 'Avalon123456' } })

    expect(playerId).toHaveValue('Avalon')
    expect(await screen.findByText(/Avalon is yours to claim, if you wish!/i)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Lord' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Lady' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Character...' })).toBeInTheDocument()
  })

  it('keeps a login path available when the player ID lookup is unavailable', async () => {
    window.history.replaceState(null, '', '/enter')

    render(<App />)

    fireEvent.change(screen.getByLabelText('Player ID'), { target: { value: 'Glitch' } })

    expect(await screen.findByText(/can't check that name right now/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try Login' })).toBeEnabled()
  })

  it('renders a clean player console on play and keeps admin tools on admin', async () => {
    window.history.replaceState(null, '', '/play?modem=off')

    const { unmount } = render(<App />)
    const playActiveButton = await screen.findByRole('button', { name: /active players: 2/i })

    const homeLogo = screen.getByRole('link', { name: /return to kyrandia home/i })
    expect(homeLogo).toHaveAttribute('href', '/')
    const aboutFooterLink = screen.getByRole('link', { name: 'About' })
    expect(aboutFooterLink).toHaveAttribute('href', '/about')
    expect(aboutFooterLink).toHaveAttribute('target', '_blank')
    expect(aboutFooterLink).toHaveAttribute('rel', 'noreferrer')
    const leaderboardFooterLink = screen.getByRole('link', { name: 'Leaderboard' })
    expect(leaderboardFooterLink).toHaveAttribute('target', '_blank')
    expect(screen.queryByRole('link', { name: 'Enter Kyrandia' })).not.toBeInTheDocument()
    expect(screen.queryByText('Fantasy world console')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /play kyrandia/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/The realm opens through the same MUD console/i)).not.toBeInTheDocument()
    expect(screen.getByText(/rest for about 30 seconds/i)).toBeInTheDocument()
    expect(screen.getByTestId('game-panel-fire-border')).toBeInTheDocument()
    expect(screen.getByLabelText('Player ID')).toBeInTheDocument()
    expect(screen.queryByLabelText('Claim new Player-ID')).not.toBeInTheDocument()
    expect(screen.queryByText('Admin controls')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Admin token')).not.toBeInTheDocument()
    expect(screen.queryByText('Events')).not.toBeInTheDocument()
    fireEvent.click(playActiveButton)
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
    fireEvent.click(within(playRoster).getByRole('button', { name: /close active player list/i }))
    expect(screen.queryByRole('dialog', { name: /active players/i })).not.toBeInTheDocument()

    unmount()
    window.history.replaceState(null, '', '/admin?modem=off')
    render(<App />)
    const adminActiveButton = await screen.findByRole('button', { name: /active players: 2/i })

    expect(screen.getByRole('heading', { name: /kyrandia admin/i })).toBeInTheDocument()
    expect(screen.getByText('Admin controls')).toBeInTheDocument()
    expect(screen.getByText('Events')).toBeInTheDocument()
    expect(adminActiveButton).toBeInTheDocument()
  })

  it('renders about and leaderboard pages from the public route set', async () => {
    window.history.replaceState(null, '', '/about')
    const { container, unmount } = render(<App />)

    expect(screen.getByRole('heading', { name: /about kyrandia/i })).toBeInTheDocument()
    expect(screen.getByText(/MajorBBS\/Worldgroup/i)).toBeInTheDocument()
    expect(
      screen.getByText(
        /The objective remains: master the world, advance through the wizarding ranks, and become an Arch-Mage of Legends\. May Tashanna show you the way\.\.\./i
      )
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /source and credits/i })).toBeInTheDocument()
    expect(screen.getByText(/Copyright \(C\) 1988-2024 Rick Hadsall/i)).toBeInTheDocument()
    expect(screen.getByText(/Copyright \(C\) 1988-95 Galacticomm/i)).toBeInTheDocument()
    expect(screen.getByText(/Copyright \(C\) 2005-24 Elwynor Technologies/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Mattie/kyrgame' })).toHaveAttribute(
      'href',
      'https://github.com/Mattie/kyrgame'
    )
    expect(screen.getByRole('link', { name: 'elwynor/elwkyr' })).toHaveAttribute(
      'href',
      'https://github.com/elwynor/elwkyr'
    )
    expect(screen.getByText(/Ported and Modernized by Mattie Casper/i)).toBeInTheDocument()
    const aboutMarkup = container.querySelector('.about-page')?.innerHTML ?? ''
    expect(aboutMarkup).toContain('<!-- Slayer must die... -->')
    expect(aboutMarkup.indexOf('<!-- Slayer must die... -->')).toBeLessThan(
      aboutMarkup.indexOf('public-copy')
    )

    unmount()
    window.history.replaceState(null, '', '/leaderboard')
    render(<App />)

    expect(screen.getByRole('heading', { name: /leaderboard/i })).toBeInTheDocument()
    expect(await screen.findByText('Zed Alt')).toBeInTheDocument()
    expect(screen.getByText('19 spells')).toBeInTheDocument()
    expect(
      mockFetch.mock.calls.filter(([input]) => String(input).endsWith('/public/player-activity'))
    ).toHaveLength(0)
    expect(
      mockFetch.mock.calls.filter(([input]) => String(input).endsWith('/public/leaderboard'))
    ).toHaveLength(1)
  })

  it('normalizes trailing slash routes before rendering', async () => {
    window.history.replaceState(null, '', '/leaderboard/')

    render(<App />)

    expect(screen.getByRole('heading', { name: /leaderboard/i })).toBeInTheDocument()
    expect(await screen.findByText('Zed Alt')).toBeInTheDocument()
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
