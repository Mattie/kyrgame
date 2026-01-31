import { FormEvent, useState } from 'react'

import { isDevEnvironment } from '../config/devMode'
import { useNavigator } from '../context/NavigatorContext'

export const SessionForm = () => {
  const { startSession, connectionStatus, error, apiBaseUrl, setAdminToken } = useNavigator()
  const [playerId, setPlayerId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [adminTokenInput, setAdminTokenInput] = useState('')
  const [joinAsAdmin, setJoinAsAdmin] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    try {
      const parsedRoom = roomId.trim() === '' ? null : Number(roomId)
      setAdminToken(joinAsAdmin ? adminTokenInput.trim() || null : null)
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
          <form onSubmit={handleSubmit} className="form-stack">
            <div className="field">
              <label htmlFor="player-id">Player ID</label>
              <input
                id="player-id"
                name="player-id"
                value={playerId}
                onChange={(event) => setPlayerId(event.target.value)}
                required
              />
            </div>

            <div className="field">
              <label htmlFor="room-id">Room ID (optional)</label>
              <input
                id="room-id"
                name="room-id"
                value={roomId}
                onChange={(event) => setRoomId(event.target.value)}
              />
              <p className="field-hint">Leave blank to use the player’s current room.</p>
            </div>

            <label className="checkbox">
              <input
                type="checkbox"
                name="admin-session"
                checked={joinAsAdmin}
                onChange={(event) => setJoinAsAdmin(event.target.checked)}
              />
              Admin session
            </label>

            <div className="field">
              <label htmlFor="admin-token">Admin token</label>
              <input
                id="admin-token"
                name="admin-token"
                value={adminTokenInput}
                onChange={(event) => setAdminTokenInput(event.target.value)}
                disabled={!joinAsAdmin}
              />
              <p className="field-hint">Configured via KYRGAME_ADMIN_TOKEN in backend/.env.</p>
            </div>

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
