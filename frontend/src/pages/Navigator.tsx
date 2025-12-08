import { ActivityLog } from '../components/ActivityLog'
import { MudConsole } from '../components/MudConsole'
import { RoomPanel } from '../components/RoomPanel'
import { SessionForm } from '../components/SessionForm'
import { isDevEnvironment } from '../config/devMode'
import { NavigatorProvider } from '../context/NavigatorContext'

export const Navigator = () => {
  return (
    <NavigatorProvider>
      <main className={`navigator ${isDevEnvironment ? 'dev-layout' : ''}`}>
        <header className="masthead">
          <p className="eyebrow">Starlit forest console</p>
          <h1>Emerald Tides Navigator</h1>
          <p className="muted">
            A luminous, shrine-like overlay inspired by Kyrandia's marble stairs, lagoon banks, and shimmering
            chambers. Type commands below to wander, chat, and inspect with the same cadence as the legacy flow.
          </p>
        </header>
        <div className="layout">
          <div className="primary">
            <MudConsole />
          </div>
          <div className="secondary">
            <SessionForm />
            <RoomPanel />
            <ActivityLog />
          </div>
        </div>
      </main>
    </NavigatorProvider>
  )
}
