import { FormEvent, useState } from 'react'

import { isDevEnvironment } from '../config/devMode'
import { useNavigator } from '../context/NavigatorContext'

export const SessionForm = () => {
  const { startSession, connectionStatus, error, apiBaseUrl } = useNavigator()
  const [playerId, setPlayerId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    try {
      const parsedRoom = roomId.trim() === '' ? null : Number(roomId)
      await startSession(playerId.trim(), Number.isNaN(parsedRoom) ? null : parsedRoom)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className={`panel session-form ${collapsed ? 'collapsed' : ''}`}>
      <header className="panel-header">
        <div>
          <p className="eyebrow">Session</p>
          <h2>Request a token</h2>
          <p className="endpoint">API base: {apiBaseUrl}</p>
        </div>
        {isDevEnvironment && (
          <button
            type="button"
            className="panel-toggle"
            aria-label={`${collapsed ? 'Expand' : 'Collapse'} session panel`}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((prev) => !prev)}
          >
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        )}
      </header>
      {!collapsed && (
        <div className="panel-body" data-testid="session-panel-body">
          <form onSubmit={handleSubmit}>
            <label htmlFor="player-id">Player ID</label>
            <input
              id="player-id"
              name="player-id"
              value={playerId}
              onChange={(event) => setPlayerId(event.target.value)}
              required
            />

            <label htmlFor="room-id">Room ID (optional)</label>
            <input
              id="room-id"
              name="room-id"
              value={roomId}
              onChange={(event) => setRoomId(event.target.value)}
              placeholder="Defaults to player room"
            />

            <button type="submit" disabled={submitting || playerId.trim() === ''}>
              {submitting ? 'Requesting…' : 'Start session'}
            </button>
          </form>
          <p className={`status ${connectionStatus}`}>
            Connection: {connectionStatus}
          </p>
          {error && <p className="status error">{error}</p>}
        </div>
      )}
    </section>
  )
}
