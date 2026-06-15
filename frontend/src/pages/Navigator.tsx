import { useEffect, useState } from 'react'

import { ActivityLog } from '../components/ActivityLog'
import { AdminControls } from '../components/AdminControls'
import { AdminDropItemPanel } from '../components/AdminDropItemPanel'
import { AdminMobPanel } from '../components/AdminMobPanel'
import { ActivePlayerIndicator } from '../components/ActivePlayerIndicator'
import { AmbientMusicPlayer } from '../components/AmbientMusicPlayer'
import { MudConsole } from '../components/MudConsole'
// import { RoomPanel } from '../components/RoomPanel' // Deprecated - not needed anymore
import { SessionForm } from '../components/SessionForm'
import kyrandiaLogo from '../assets/home/KyrandiaLogo_trans_trimmed.png'
import { isDevEnvironment } from '../config/devMode'
import { useNavigator } from '../context/NavigatorContext'

type NavigatorProps = {
  mode?: 'admin' | 'player'
}

const NavigatorContent = ({ mode = 'admin' }: NavigatorProps) => {
  const { session } = useNavigator()
  const [controlsOpen, setControlsOpen] = useState(true)
  const sessionToken = session?.token ?? null
  const controlsId = 'navigator-controls'
  const isAdmin = mode === 'admin'

  useEffect(() => {
    setControlsOpen(isAdmin && !sessionToken)
  }, [isAdmin, sessionToken])

  const controlsStateClass = controlsOpen ? 'controls-open' : 'controls-closed'

  return (
    <main
      className={`navigator ${isDevEnvironment ? 'dev-layout' : ''} ${controlsStateClass} ${
        isAdmin ? 'admin-console' : 'player-console'
      }`}
    >
      {!isAdmin && (
        <a className="play-logo-link" href="/" aria-label="Return to Kyrandia home">
          <img src={kyrandiaLogo} alt="" />
        </a>
      )}
      <div className="navigator-top-controls">
        {!isAdmin && <AmbientMusicPlayer />}
        <ActivePlayerIndicator />
      </div>
      {isAdmin && (
        <header className="masthead">
          <p className="eyebrow">Operator console</p>
          <h1>Kyrandia Admin</h1>
          <p className="muted">Session, runtime, and player-editing tools for local development.</p>
        </header>
      )}
      {isAdmin && (
        <button
          type="button"
          className="mobile-controls-toggle"
          aria-controls={controlsId}
          aria-expanded={controlsOpen}
          onClick={() => setControlsOpen((current) => !current)}
        >
          {controlsOpen ? 'Hide controls' : 'Show controls'}
        </button>
      )}
      <div className="layout">
        <div className="primary">
          {!isAdmin && !sessionToken && (
            <section className="player-console-entry" aria-label="Player entry">
              <SessionForm
                title="Player-ID"
                eyebrow="Login"
                showAdminFields={false}
                showRoomField={false}
                showEndpoint={false}
              />
            </section>
          )}
          <MudConsole />
        </div>
        {isAdmin && (
          <aside
            id={controlsId}
            className="secondary"
            aria-label="Session and admin controls"
            data-mobile-state={controlsOpen ? 'open' : 'closed'}
          >
            <SessionForm />
            <AdminMobPanel />
            <AdminDropItemPanel />
            <AdminControls />
            {/* <RoomPanel /> */}
            <ActivityLog />
          </aside>
        )}
      </div>
      {!isAdmin && (
        <footer className="play-footer" aria-label="Kyrandia site links">
          <a href="/" target="_blank" rel="noreferrer">
            Home
          </a>
          <a href="/about" target="_blank" rel="noreferrer">
            About
          </a>
          <a href="/leaderboard" target="_blank" rel="noreferrer">
            Leaderboard
          </a>
        </footer>
      )}
    </main>
  )
}

export const Navigator = ({ mode = 'admin' }: NavigatorProps) => <NavigatorContent mode={mode} />
