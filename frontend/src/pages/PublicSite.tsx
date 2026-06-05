import { MouseEvent, ReactNode, useEffect, useMemo, useState } from 'react'

import { SessionForm } from '../components/SessionForm'
import { getApiBaseUrl } from '../config/endpoints'

export type PublicPlayerSummary = {
  player_id: string
  display_name: string
  level: number
  rank_title: string
  spellbook_count: number
  active: boolean
  last_seen: string | null
}

type PlayerActivityPayload = {
  active: PublicPlayerSummary[]
  recent: PublicPlayerSummary[]
}

type LeaderboardPayload = {
  players: PublicPlayerSummary[]
}

type PublicSiteData = {
  activity: PlayerActivityPayload
  leaderboard: PublicPlayerSummary[]
  loading: boolean
  error: string | null
}

type PublicSiteDataOptions = {
  loadActivity?: boolean
  loadLeaderboard?: boolean
}

type PublicPageProps = {
  navigate: (path: string) => void
}

const emptyActivity: PlayerActivityPayload = {
  active: [],
  recent: [],
}

const readPublicJson = async <T,>(response: Response): Promise<T> => {
  const contentType = response.headers.get('content-type') ?? ''
  if (!response.ok || !contentType.includes('application/json')) {
    throw new Error('Unable to load public game data')
  }
  return (await response.json()) as T
}

const usePublicSiteData = ({
  loadActivity = true,
  loadLeaderboard = true,
}: PublicSiteDataOptions = {}): PublicSiteData => {
  const apiBaseUrl = useMemo(() => getApiBaseUrl(), [])
  const [activity, setActivity] = useState<PlayerActivityPayload>(emptyActivity)
  const [leaderboard, setLeaderboard] = useState<PublicPlayerSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const [activityPayload, leaderboardPayload] = await Promise.all([
          loadActivity
            ? fetch(`${apiBaseUrl}/public/player-activity`).then(readPublicJson<PlayerActivityPayload>)
            : Promise.resolve<PlayerActivityPayload | null>(null),
          loadLeaderboard
            ? fetch(`${apiBaseUrl}/public/leaderboard`).then(readPublicJson<LeaderboardPayload>)
            : Promise.resolve<LeaderboardPayload | null>(null),
        ])
        if (cancelled) return
        setActivity(
          activityPayload
            ? {
                active: activityPayload.active ?? [],
                recent: activityPayload.recent ?? [],
              }
            : emptyActivity
        )
        setLeaderboard(leaderboardPayload?.players ?? [])
      } catch (err) {
        if (cancelled) return
        setError('Unable to load public game data')
        setActivity(emptyActivity)
        setLeaderboard([])
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [apiBaseUrl, loadActivity, loadLeaderboard])

  return { activity, leaderboard, loading, error }
}

const handleRouteClick =
  (navigate: (path: string) => void, path: string) =>
  (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(path)
  }

const SiteNav = ({ navigate }: PublicPageProps) => (
  <nav className="site-nav" aria-label="Primary">
    <a href="/" onClick={handleRouteClick(navigate, '/')}>
      Kyrandia
    </a>
    <div>
      <a href="/about" onClick={handleRouteClick(navigate, '/about')}>
        About
      </a>
      <a href="/leaderboard" onClick={handleRouteClick(navigate, '/leaderboard')}>
        Leaderboard
      </a>
      <a href="/enter" onClick={handleRouteClick(navigate, '/enter')}>
        Enter
      </a>
      <a href="/admin" onClick={handleRouteClick(navigate, '/admin')}>
        Admin
      </a>
    </div>
  </nav>
)

const SiteFrame = ({
  children,
  navigate,
  className = '',
}: PublicPageProps & { children: ReactNode; className?: string }) => (
  <main className={`site-page ${className}`}>
    <SiteNav navigate={navigate} />
    {children}
  </main>
)

const spellText = (count: number) => `${count} ${count === 1 ? 'spell' : 'spells'}`

const PlayerRow = ({ player, rank }: { player: PublicPlayerSummary; rank?: number }) => (
  <article className="public-player-row">
    <div className="player-rank">{rank ? `#${rank}` : player.active ? 'Live' : 'Recent'}</div>
    <div>
      <h3>{player.display_name || player.player_id}</h3>
      <p>
        Level {player.level} - {player.rank_title}
      </p>
    </div>
    <span>{spellText(player.spellbook_count)}</span>
  </article>
)

const PlayerList = ({
  title,
  players,
  emptyText,
}: {
  title: string
  players: PublicPlayerSummary[]
  emptyText: string
}) => (
  <section className="public-panel">
    <header className="public-panel-header">
      <p className="eyebrow">{title}</p>
      <h2>{title}</h2>
    </header>
    <div className="public-player-list">
      {players.length === 0 ? (
        <p className="muted">{emptyText}</p>
      ) : (
        players.map((player) => <PlayerRow key={player.player_id} player={player} />)
      )}
    </div>
  </section>
)

export const LandingPage = ({ navigate }: PublicPageProps) => {
  const { activity, leaderboard, loading, error } = usePublicSiteData()
  const leaders = leaderboard.slice(0, 5)

  return (
    <SiteFrame navigate={navigate} className="landing-page">
      <section className="site-hero">
        <div className="site-hero-copy">
          <p className="eyebrow">Fantasy World of Legends</p>
          <h1>Kyrandia</h1>
          <p>
            Cross a living text realm of spells, rival mages, puzzles, and old BBS magic.
          </p>
          <div className="site-actions">
            <a className="site-primary-link" href="/enter" onClick={handleRouteClick(navigate, '/enter')}>
              Start Playing
            </a>
            <a href="/leaderboard" onClick={handleRouteClick(navigate, '/leaderboard')}>
              View Leaderboard
            </a>
          </div>
        </div>
        <div
          className="kyrandia-hero-art"
          role="img"
          aria-label="Kyrandia magic forest with a glowing console portal"
        >
          <div className="moon" />
          <div className="tower tower-left" />
          <div className="tower tower-right" />
          <div className="console-portal">
            <span>Kyrandia</span>
            <span>&gt; cast whereami</span>
          </div>
        </div>
      </section>

      {error && <p className="status error">{error}</p>}
      {loading && <p className="status">Loading player activity...</p>}

      <section className="public-dashboard">
        <PlayerList
          title="Active Players"
          players={activity.active}
          emptyText="No players are active right now."
        />
        <PlayerList
          title="Recently Active"
          players={activity.recent}
          emptyText="No recent players in the last seven days."
        />
        <section className="public-panel leaderboard-preview">
          <header className="public-panel-header">
            <p className="eyebrow">Leaderboard</p>
            <h2>Current Leaders</h2>
          </header>
          <div className="public-player-list">
            {leaders.length === 0 ? (
              <p className="muted">No ranked players yet.</p>
            ) : (
              leaders.map((player, index) => (
                <PlayerRow key={player.player_id} player={player} rank={index + 1} />
              ))
            )}
          </div>
        </section>
      </section>
    </SiteFrame>
  )
}

export const EntryPage = ({ navigate }: PublicPageProps) => (
  <SiteFrame navigate={navigate} className="entry-page">
    <section className="entry-layout">
      <div>
        <p className="eyebrow">Player entry</p>
        <h1>Enter Kyrandia</h1>
        <p>
          Sign in with a Player-ID for now. This page is the account handoff point when we add
          Google sign-in later.
        </p>
      </div>
      <SessionForm
        title="Player-ID"
        eyebrow="Login"
        showAdminFields={false}
        showRoomField={false}
        showEndpoint={false}
        onSessionStarted={() => navigate('/play')}
      />
    </section>
  </SiteFrame>
)

export const AboutPage = ({ navigate }: PublicPageProps) => (
  <SiteFrame navigate={navigate} className="about-page">
    <section className="public-copy">
      <p className="eyebrow">History</p>
      <h1>About Kyrandia</h1>
      <p>
        Kyrandia began as a MajorBBS/Worldgroup multiplayer text adventure where apprentices
        chased the title of Arch-Mage of Legends.
      </p>
      <p>
        The realm centers on Tashanna, the Lady of Legends. Players begin as young apprentices,
        then cross lands of magic and mystery while gathering spells, solving puzzles, trading
        knowledge, and facing rival mages.
      </p>
      <p>
        Scott Brinker and Richard Skurnick designed and programmed the original game in 1988.
        The modern project keeps the original C sources and message catalogs close while moving
        the play experience to a browser, FastAPI backend, and WebSocket command console.
      </p>
      <p>
        The objective remains simple and severe: master the world, advance through the ranks,
        and become an Arch-Mage of Legends.
      </p>
    </section>
  </SiteFrame>
)

export const LeaderboardPage = ({ navigate }: PublicPageProps) => {
  const { leaderboard, loading, error } = usePublicSiteData({ loadActivity: false })

  return (
    <SiteFrame navigate={navigate} className="leaderboard-page">
      <section className="public-copy leaderboard-heading">
        <p className="eyebrow">Ranks</p>
        <h1>Leaderboard</h1>
        <p>Level breaks the first tie; spellbook mastery breaks the next.</p>
      </section>
      {error && <p className="status error">{error}</p>}
      {loading && <p className="status">Loading leaderboard...</p>}
      <section className="leaderboard-table" aria-label="Kyrandia leaderboard">
        {leaderboard.length === 0 ? (
          <p className="muted">No ranked players yet.</p>
        ) : (
          leaderboard.map((player, index) => (
            <PlayerRow key={player.player_id} player={player} rank={index + 1} />
          ))
        )}
      </section>
    </SiteFrame>
  )
}
