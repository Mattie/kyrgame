import { ActivityLog } from '../components/ActivityLog'
import { AdminControls } from '../components/AdminControls'
import { MudConsole } from '../components/MudConsole'
// import { RoomPanel } from '../components/RoomPanel' // Deprecated - not needed anymore
import { SessionForm } from '../components/SessionForm'
import { isDevEnvironment } from '../config/devMode'
import { NavigatorProvider } from '../context/NavigatorContext'

export const Navigator = () => {
  return (
    <NavigatorProvider>
      <main className={`navigator ${isDevEnvironment ? 'dev-layout' : ''}`}>
        <header className="masthead">
          <p className="eyebrow">Fantasy world console</p>
          <h1>Kyrandia Explorer</h1>
          <p className="muted">
            A MUD-style interface inspired by the original BBS client. Type commands below to walk, chat,
            and inspect just like the legacy flow.
          </p>
        </header>
        <div className="layout">
          <div className="primary">
            <MudConsole />
          </div>
          <div className="secondary">
            <SessionForm />
            <AdminControls />
            {/* <RoomPanel /> */}
            <ActivityLog />
          </div>
        </div>
      </main>
    </NavigatorProvider>
  )
}
