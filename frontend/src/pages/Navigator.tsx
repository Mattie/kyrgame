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
          <p className="eyebrow">Echoes of Kyrandia</p>
          <h1>Marble Canopy Navigator</h1>
          <p className="muted">
            Glide from abandoned camps to aurora-lit chambers, following the lagoon shimmer and marble stair glow that
            define Kyrandia&apos;s dreamlike wilderness.
          </p>
          <p className="muted">
            This console keeps the BBS feel while wrapping it in the same twilight palette the world descriptions paint.
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
