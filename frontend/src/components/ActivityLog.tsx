import { useMemo, useState } from 'react'

import { isDevEnvironment } from '../config/devMode'
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
  const [collapsed, setCollapsed] = useState(false)
  const reversed = useMemo(() => [...activity].reverse(), [activity])

  return (
    <section className={`panel activity-log ${collapsed ? 'collapsed' : ''}`}>
      <header className="panel-header">
        <div>
          <p className="eyebrow">Room activity</p>
          <h2>Events</h2>
        </div>
        {isDevEnvironment && (
          <button
            type="button"
            className="panel-toggle"
            aria-label={`${collapsed ? 'Expand' : 'Collapse'} room activity panel`}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((prev) => !prev)}
          >
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        )}
      </header>
      {!collapsed && (
        <div className="log-entries" data-testid="activity-log-body">
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
      )}
    </section>
  )
}
