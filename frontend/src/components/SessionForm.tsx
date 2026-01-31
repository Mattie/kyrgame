import { FormEvent, useEffect, useState } from 'react'

import { isDevEnvironment } from '../config/devMode'
import { useNavigator } from '../context/NavigatorContext'

const storageKeys = {
  playerId: 'kyrgame.navigator.playerId',
  roomId: 'kyrgame.navigator.roomId',
  adminSession: 'kyrgame.navigator.adminSession',
  adminToken: 'kyrgame.navigator.adminToken',
}

export const SessionForm = () => {
  const { startSession, connectionStatus, error, apiBaseUrl, setAdminToken } = useNavigator()
  const [playerId, setPlayerId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [adminTokenInput, setAdminTokenInput] = useState('')
  const [joinAsAdmin, setJoinAsAdmin] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    const storedPlayerId = localStorage.getItem(storageKeys.playerId)
    if (storedPlayerId) {
      setPlayerId(storedPlayerId)
    }

    const storedRoomId = localStorage.getItem(storageKeys.roomId)
    if (storedRoomId) {
      setRoomId(storedRoomId)
    }

    const storedAdminSession = localStorage.getItem(storageKeys.adminSession) === 'true'
    setJoinAsAdmin(storedAdminSession)

    if (storedAdminSession) {
      const storedAdminToken = localStorage.getItem(storageKeys.adminToken)
      if (storedAdminToken) {
        setAdminTokenInput(storedAdminToken)
      }
    } else {
      localStorage.removeItem(storageKeys.adminToken)
    }
  }, [])

  const persistPlayerId = (nextValue: string) => {
    if (nextValue.trim() === '') {
      localStorage.removeItem(storageKeys.playerId)
      return
    }
    localStorage.setItem(storageKeys.playerId, nextValue)
  }

  const persistRoomId = (nextValue: string) => {
    if (nextValue.trim() === '') {
      localStorage.removeItem(storageKeys.roomId)
      return
    }
    localStorage.setItem(storageKeys.roomId, nextValue)
  }

  const persistAdminSession = (enabled: boolean) => {
    localStorage.setItem(storageKeys.adminSession, String(enabled))
    if (!enabled) {
      localStorage.removeItem(storageKeys.adminToken)
    }
  }

  const persistAdminToken = (nextValue: string) => {
    if (!joinAsAdmin) {
      localStorage.removeItem(storageKeys.adminToken)
      return
    }
    if (nextValue.trim() === '') {
      localStorage.removeItem(storageKeys.adminToken)
      return
    }
    localStorage.setItem(storageKeys.adminToken, nextValue)
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    try {
      const parsedRoom = roomId.trim() === '' ? null : Number(roomId)
      const trimmedPlayerId = playerId.trim()
      const trimmedAdminToken = adminTokenInput.trim()

      setAdminToken(joinAsAdmin ? trimmedAdminToken || null : null)
      persistPlayerId(trimmedPlayerId)
      persistRoomId(roomId)
      persistAdminSession(joinAsAdmin)
      if (joinAsAdmin) {
        persistAdminToken(trimmedAdminToken)
      }
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
                onChange={(event) => {
                  const nextValue = event.target.value
                  setPlayerId(nextValue)
                  persistPlayerId(nextValue)
                }}
                required
              />
            </div>

            <div className="field">
              <label htmlFor="room-id">Room ID (optional)</label>
              <input
                id="room-id"
                name="room-id"
                value={roomId}
                onChange={(event) => {
                  const nextValue = event.target.value
                  setRoomId(nextValue)
                  persistRoomId(nextValue)
                }}
              />
              <p className="field-hint">Leave blank to use the player’s current room.</p>
            </div>

            <label className="checkbox">
              <input
                type="checkbox"
                name="admin-session"
                checked={joinAsAdmin}
                onChange={(event) => {
                  const enabled = event.target.checked
                  setJoinAsAdmin(enabled)
                  persistAdminSession(enabled)
                  if (!enabled) {
                    setAdminTokenInput('')
                    setAdminToken(null)
                  }
                }}
              />
              Admin session
            </label>

            <div className="field">
              <label htmlFor="admin-token">Admin token</label>
              <input
                id="admin-token"
                name="admin-token"
                value={adminTokenInput}
                onChange={(event) => {
                  const nextValue = event.target.value
                  setAdminTokenInput(nextValue)
                  persistAdminToken(nextValue)
                }}
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
