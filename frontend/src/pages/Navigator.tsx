import { ActivityLog } from '../components/ActivityLog'
import { CommandConsole } from '../components/CommandConsole'
import { RoomPanel } from '../components/RoomPanel'
import { SessionForm } from '../components/SessionForm'
import { StatusSidebar } from '../components/StatusSidebar'
import { NavigatorProvider } from '../context/NavigatorContext'

export const Navigator = () => {
  return (
    <NavigatorProvider>
      <main className="navigator">
        <div className="terminal-layout">
          <div className="terminal-column">
            <SessionForm />
            <CommandConsole />
            <RoomPanel />
            <ActivityLog />
          </div>
          <StatusSidebar />
        </div>
      </main>
    </NavigatorProvider>
  )
}
