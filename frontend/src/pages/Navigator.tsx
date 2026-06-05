import { useEffect, useState } from 'react'

import { ActivityLog } from '../components/ActivityLog'
import { AdminControls } from '../components/AdminControls'
import { AdminMobPanel } from '../components/AdminMobPanel'
import { ActivePlayerIndicator } from '../components/ActivePlayerIndicator'
import { MudConsole } from '../components/MudConsole'
// import { RoomPanel } from '../components/RoomPanel' // Deprecated - not needed anymore
import { SessionForm } from '../components/SessionForm'
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
      <ActivePlayerIndicator />
      <header className="masthead">
        <p className="eyebrow">{isAdmin ? 'Operator console' : 'Fantasy world console'}</p>
        <h1>{isAdmin ? 'Kyrandia Admin' : 'Play Kyrandia'}</h1>
        <p className="muted">
          {isAdmin
            ? 'Session, runtime, and player-editing tools for local development.'
            : 'The realm opens through the same MUD console, with the tooling kept out of the play surface.'}
        </p>
      </header>
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
            <AdminControls />
            {/* <RoomPanel /> */}
            <ActivityLog />
          </aside>
        )}
      </div>
    </main>
  )
}

export const Navigator = ({ mode = 'admin' }: NavigatorProps) => <NavigatorContent mode={mode} />
