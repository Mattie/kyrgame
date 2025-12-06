import { ActivityLog } from '../components/ActivityLog'
import { RoomPanel } from '../components/RoomPanel'
import { SessionForm } from '../components/SessionForm'
import { NavigatorProvider } from '../context/NavigatorContext'

export const Navigator = () => {
  return (
    <NavigatorProvider>
      <main className="navigator">
        <section className="grid">
          <SessionForm />
          <RoomPanel />
        </section>
        <ActivityLog />
      </main>
    </NavigatorProvider>
  )
}
