import { MouseEvent, ReactNode, useEffect, useMemo, useState } from 'react'

import { SessionForm } from '../components/SessionForm'
import { getApiBaseUrl } from '../config/endpoints'
import activePlayersIcon from '../assets/home/kyrandia-active-players-icon.png'
import leaderboardIcon from '../assets/home/kyrandia-leaderboard-icon.png'
import recentlyActiveIcon from '../assets/home/kyrandia-recently-active-icon.png'
import kyrandiaLogo from '../assets/home/KyrandiaLogo_trans_trimmed.png'

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

const EasterEggComment = () => (
  <span
    aria-hidden="true"
    hidden
    dangerouslySetInnerHTML={{ __html: '<!-- Slayer must die... -->' }}
  />
)

const SiteNav = ({ navigate }: PublicPageProps) => (
  <nav className="site-nav" aria-label="Primary">
    <a className="site-logo-link" href="/" onClick={handleRouteClick(navigate, '/')}>
      <img src={kyrandiaLogo} alt="Kyrandia Online Edition" />
    </a>
    <div className="site-nav-links">
      <a href="/" onClick={handleRouteClick(navigate, '/')}>
        Home
      </a>
      <a href="/about" onClick={handleRouteClick(navigate, '/about')}>
        About
      </a>
      <a href="/leaderboard" onClick={handleRouteClick(navigate, '/leaderboard')}>
        Leaderboard
      </a>
      <a className="site-nav-cta" href="/enter" onClick={handleRouteClick(navigate, '/enter')}>
        Enter Kyrandia
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

const PlayerRow = ({
  player,
  rank,
  showSpellCount = true,
}: {
  player: PublicPlayerSummary
  rank?: number
  showSpellCount?: boolean
}) => (
  <article className="public-player-row">
    <div className="player-rank">{rank ? `#${rank}` : player.active ? 'Live' : 'Recent'}</div>
    <div>
      <h3>{player.display_name || player.player_id}</h3>
      <p>
        Level {player.level} - {player.rank_title}
      </p>
    </div>
    {showSpellCount && <span>{spellText(player.spellbook_count)}</span>}
  </article>
)

const PlayerList = ({
  title,
  icon,
  players,
  emptyText,
  footer,
  showSpellCount = true,
}: {
  title: string
  icon: string
  players: PublicPlayerSummary[]
  emptyText: string
  footer?: ReactNode
  showSpellCount?: boolean
}) => (
  <section className="public-panel">
    <header className="public-panel-header">
      <img className="public-panel-icon" src={icon} alt="" aria-hidden="true" />
      <div>
        <h2>{title}</h2>
      </div>
    </header>
    <div className="public-player-list">
      {players.length === 0 ? (
        <p className="muted">{emptyText}</p>
      ) : (
        players.map((player) => (
          <PlayerRow
            key={player.player_id}
            player={player}
            showSpellCount={showSpellCount}
          />
        ))
      )}
    </div>
    {footer && <div className="public-panel-footer">{footer}</div>}
  </section>
)

export const HomePage = ({ navigate }: PublicPageProps) => {
  const { activity, leaderboard, loading, error } = usePublicSiteData()
  const recentPlayers = activity.recent.slice(0, 2)
  const leaders = leaderboard.slice(0, 2)

  return (
    <SiteFrame navigate={navigate} className="landing-page">
      <EasterEggComment />
      <section className="site-hero" aria-labelledby="home-hero-title">
        <div className="site-hero-copy">
          <h1 id="home-hero-title">Legends pass and time goes by...</h1>
          <div className="site-ornament" aria-hidden="true" />
          <p>
            Begin at the willow. Search the dark forest. Read the old inscriptions. Kyrandia
            wizards seek every spell, ponder every puzzle, and learn from every mistake.
          </p>
          <div className="site-actions">
            <a
              className="site-primary-link"
              href="/enter"
              onClick={handleRouteClick(navigate, '/enter')}
            >
              Begin Your Journey
            </a>
            <a href="/about" onClick={handleRouteClick(navigate, '/about')}>
              Learn More
            </a>
          </div>
          <blockquote className="site-quote">
            <p>"No matter where you go, I will be with you..."</p>
            <cite>- Tashanna</cite>
          </blockquote>
        </div>
      </section>

      {error && <p className="status error">{error}</p>}
      {loading && <p className="status">Loading player activity...</p>}

      <section className="public-dashboard">
        <PlayerList
          title="Active Players"
          icon={activePlayersIcon}
          players={activity.active}
          emptyText="No players are active right now."
          showSpellCount={false}
        />
        <PlayerList
          title="Recently Active"
          icon={recentlyActiveIcon}
          players={recentPlayers}
          emptyText="No recent players in the last seven days."
          showSpellCount={false}
          footer={
            <a href="/leaderboard" onClick={handleRouteClick(navigate, '/leaderboard')}>
              See all recent activity {'->'}
            </a>
          }
        />
        <section className="public-panel leaderboard-preview">
          <header className="public-panel-header">
            <img className="public-panel-icon" src={leaderboardIcon} alt="" aria-hidden="true" />
            <div>
              <h2>Leaderboard</h2>
            </div>
          </header>
          <div className="public-player-list">
            {leaders.length === 0 ? (
              <p className="muted">No ranked players yet.</p>
            ) : (
              leaders.map((player, index) => (
                <PlayerRow
                  key={player.player_id}
                  player={player}
                  rank={index + 1}
                  showSpellCount={false}
                />
              ))
            )}
          </div>
          <div className="public-panel-footer">
            <a href="/leaderboard" onClick={handleRouteClick(navigate, '/leaderboard')}>
              View full leaderboard {'->'}
            </a>
          </div>
        </section>
      </section>
      <p className="site-welcome-line">
        If you don't believe in legends, you haven't seen Kyrandia...
      </p>
    </SiteFrame>
  )
}

export const LandingPage = HomePage

export const EntryPage = ({ navigate }: PublicPageProps) => (
  <SiteFrame navigate={navigate} className="entry-page">
    <section className="entry-layout">
      <div>
        <p className="eyebrow">The willow is waiting</p>
        <h1>Enter Kyrandia</h1>
        <p>Provide your character name and password to begin your journey.</p>
      </div>
      <SessionForm
        title="Who enters the realm?"
        eyebrow="Welcome"
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
    <EasterEggComment />
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
        This modern web port keeps the original C sources and message catalogs close while moving
        the play experience to a browser, FastAPI backend, and WebSocket command console.
      </p>
      <p>
        The objective remains: master the world, advance through the wizarding ranks, and become an
        Arch-Mage of Legends. May Tashanna show you the way...
      </p>
      <section className="public-credits" aria-labelledby="source-credits-title">
        <h2 id="source-credits-title">Source, License, and Credits</h2>
        <p>Original source copyright notices include:</p>
        <ul className="public-credit-list">
          <li>Copyright (C) 1988-2024 Rick Hadsall. All Rights Reserved.</li>
          <li>Copyright (C) 1988-95 Galacticomm</li>
          <li>Copyright (C) 2005-24 Elwynor Technologies</li>
        </ul>
        <p>
          This modern port is available at{' '}
          <a href="https://github.com/Mattie/kyrgame">Mattie/kyrgame</a>. It is based on the
          original MajorBBS/Worldgroup source distribution published by{' '}
          <a href="https://github.com/elwynor/elwkyr">Elwynor Technologies</a>.
        </p>
        <p>
          The project is licensed under the GNU Affero General Public License version 3. Source code
          for the running version is available at no charge through the repository above.
        </p>
        <p>
          This independent modern port has no affiliation with Westwood Studios, Electronic Arts, or
          the Legend of Kyrandia adventure-game series.
        </p>
        <p className="public-port-credit">Ported and Modernized by Mattie Casper</p>
      </section>
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
        <p>
          The most powerful wizards in all of Kyrandia are known to everyone. May you one day
          achieve such glory!
        </p>
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
