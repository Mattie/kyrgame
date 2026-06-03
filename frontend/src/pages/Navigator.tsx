import { useEffect, useState } from 'react'

import { ActivityLog } from '../components/ActivityLog'
import { AdminControls } from '../components/AdminControls'
import { AdminMobPanel } from '../components/AdminMobPanel'
import { MudConsole } from '../components/MudConsole'
// import { RoomPanel } from '../components/RoomPanel' // Deprecated - not needed anymore
import { SessionForm } from '../components/SessionForm'
import { isDevEnvironment } from '../config/devMode'
import { NavigatorProvider, useNavigator } from '../context/NavigatorContext'

const NavigatorContent = () => {
  const { session } = useNavigator()
  const [controlsOpen, setControlsOpen] = useState(true)
  const sessionToken = session?.token ?? null
  const controlsId = 'navigator-controls'

  useEffect(() => {
    setControlsOpen(!sessionToken)
  }, [sessionToken])

  const controlsStateClass = controlsOpen ? 'controls-open' : 'controls-closed'

  return (
    <main className={`navigator ${isDevEnvironment ? 'dev-layout' : ''} ${controlsStateClass}`}>
      <header className="masthead">
        <p className="eyebrow">Fantasy world console</p>
        <h1>Kyrandia Explorer</h1>
        <p className="muted">
          A MUD-style interface inspired by the original BBS client. Type commands below to walk, chat,
          and inspect just like the legacy flow.
        </p>
      </header>
      <button
        type="button"
        className="mobile-controls-toggle"
        aria-controls={controlsId}
        aria-expanded={controlsOpen}
        onClick={() => setControlsOpen((current) => !current)}
      >
        {controlsOpen ? 'Hide controls' : 'Show controls'}
      </button>
      <div className="layout">
        <div className="primary">
          <MudConsole />
        </div>
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
      </div>
    </main>
  )
}

export const Navigator = () => {
  return (
    <NavigatorProvider>
      <NavigatorContent />
    </NavigatorProvider>
  )
}
