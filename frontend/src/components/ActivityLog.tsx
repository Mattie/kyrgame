import { useMemo } from 'react'

import { ActivityEntry, useNavigator } from '../context/NavigatorContext'

const formatPayload = (entry: ActivityEntry): string | null => {
  if (entry.payload === undefined || entry.payload === null) return null
  if (typeof entry.payload === 'string') return entry.payload
  if (typeof entry.payload === 'number' || typeof entry.payload === 'boolean') {
    return String(entry.payload)
  }
  return JSON.stringify(entry.payload)
}

export const ActivityLog = () => {
  const { activity } = useNavigator()
  const reversed = useMemo(() => [...activity].reverse(), [activity])

  return (
    <section className="panel activity-log">
      <header>
        <p className="eyebrow">Room activity</p>
        <h2>Events</h2>
      </header>
      <div className="log-entries">
        {reversed.length === 0 && <p className="muted">No events yet</p>}
        {reversed.map((entry) => (
          <article key={entry.id} className="log-entry">
            <div>
              <p className="eyebrow">{entry.type}</p>
              <p className="summary">{entry.summary}</p>
            </div>
            {entry.room !== undefined && <p className="muted">Room {entry.room}</p>}
            {formatPayload(entry) && (
              <pre aria-label="payload" className="payload">
                {formatPayload(entry)}
              </pre>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
