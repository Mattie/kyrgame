import { FormEvent, useEffect, useState } from 'react'

import { isDevEnvironment } from '../config/devMode'
import { useNavigator } from '../context/NavigatorContext'
import { AnsiText } from './AnsiText'

const storageKeys = {
  playerId: 'kyrgame.navigator.playerId',
  roomId: 'kyrgame.navigator.roomId',
  adminSession: 'kyrgame.navigator.adminSession',
  adminToken: 'kyrgame.navigator.adminToken',
}

const fallbackLegacyPlayerIdPrompt =
  '\u001b[0m\r\n\r\n\u001b[1;32mSince this is your first time entering Kyrandia (Fantasy-world), you\r\nmust pick a 3-9 character Player-ID for yourself.  This is what you will\r\nbe known as throughout the game.\r\n\r\n\u001b[36mPlease enter your Player-ID: '

const formatTokenTtl = (seconds?: number | null) => {
  if (seconds === undefined || seconds === null) return null
  const safeSeconds = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  return `${hours}h ${minutes}m`
}

export const SessionForm = () => {
  const {
    startSession,
    connectionStatus,
    error,
    apiBaseUrl,
    setAdminToken,
    session,
    currentRoom,
  } = useNavigator()
  const [playerId, setPlayerId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [adminTokenInput, setAdminTokenInput] = useState('')
  const [joinAsAdmin, setJoinAsAdmin] = useState(false)
  const [claimNewPlayer, setClaimNewPlayer] = useState(false)
  const [legacyPlayerIdPrompt, setLegacyPlayerIdPrompt] = useState(fallbackLegacyPlayerIdPrompt)
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

  useEffect(() => {
    if (!claimNewPlayer) return

    let cancelled = false
    const loadPrompt = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/i18n/en-US/messages`)
        if (!response.ok) return
        const payload = await response.json()
        const prompt = payload?.messages?.GETALS
        if (!cancelled && typeof prompt === 'string' && prompt.trim() !== '') {
          setLegacyPlayerIdPrompt(prompt)
        }
      } catch {
        // Keep the catalog-matching fallback if the public message bundle is unavailable.
      }
    }

    void loadPrompt()
    return () => {
      cancelled = true
    }
  }, [apiBaseUrl, claimNewPlayer])

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
      const parsedRoom = claimNewPlayer || roomId.trim() === '' ? null : Number(roomId)
      const trimmedPlayerId = playerId.trim()
      const trimmedAdminToken = adminTokenInput.trim()

      setAdminToken(joinAsAdmin ? trimmedAdminToken || null : null)
      persistPlayerId(trimmedPlayerId)
      if (!claimNewPlayer) {
        persistRoomId(roomId)
      }
      persistAdminSession(joinAsAdmin)
      if (joinAsAdmin) {
        persistAdminToken(trimmedAdminToken)
      }
      await startSession(trimmedPlayerId, Number.isNaN(parsedRoom) ? null : parsedRoom, {
        createPlayer: claimNewPlayer,
      })
    } finally {
      setSubmitting(false)
    }
  }

  const handleReconnect = async () => {
    if (!session) return
    setSubmitting(true)
    try {
      await startSession(session.playerId, currentRoom ?? session.roomId)
    } catch {
      // `startSession` is responsible for updating shared error state.
      // Swallow reconnect failures here to avoid an unhandled promise rejection
      // from this UI event handler.
    } finally {
      setSubmitting(false)
    }
  }

  const tokenTtl = formatTokenTtl(session?.expiresInSeconds)

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
                disabled={claimNewPlayer}
                onChange={(event) => {
                  const nextValue = event.target.value
                  setRoomId(nextValue)
                  persistRoomId(nextValue)
                }}
              />
              <p className="field-hint">
                {claimNewPlayer
                  ? 'New Player-IDs always enter Kyrandia at the willow tree.'
                  : "Leave blank to use the player's current room."}
              </p>
            </div>

            <label className="checkbox">
              <input
                type="checkbox"
                name="claim-new-player"
                checked={claimNewPlayer}
                onChange={(event) => setClaimNewPlayer(event.target.checked)}
              />
              Claim new Player-ID
            </label>

            {claimNewPlayer && (
              <p className="field-hint">
                <AnsiText text={legacyPlayerIdPrompt} />
              </p>
            )}

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
              {submitting ? 'Requesting...' : claimNewPlayer ? 'Claim Player-ID' : 'Start session'}
            </button>
          </form>
          <p className={`status ${connectionStatus}`}>
            Connection: {connectionStatus}
          </p>
          {tokenTtl && <p className="status">Token expires in {tokenTtl}</p>}
          {error && (
            <p className="status error">
              <AnsiText text={error} />
            </p>
          )}
          {session && connectionStatus === 'disconnected' && (
            <button type="button" onClick={handleReconnect} disabled={submitting}>
              Reconnect session
            </button>
          )}
        </div>
      )}
    </section>
  )
}
