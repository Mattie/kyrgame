import { FormEvent, useEffect, useId, useMemo, useRef, useState } from 'react'

import { useNavigator } from '../context/NavigatorContext'
import { AnsiText } from './AnsiText'

const storageKeys = {
  playerId: 'kyrgame.navigator.playerId',
  roomId: 'kyrgame.navigator.roomId',
  adminSession: 'kyrgame.navigator.adminSession',
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

type SessionFormProps = {
  title?: string
  eyebrow?: string
  showAdminFields?: boolean
  showRoomField?: boolean
  showEndpoint?: boolean
  onSessionStarted?: () => void
}

type CharacterBackground = 'lord' | 'lady'

type PlayerIdLookup = {
  player_id?: string
  canonical_player_id?: string
  valid?: boolean
  exists?: boolean
  available?: boolean
  reserved?: boolean
  account_bound?: boolean | null
  status?: 'invalid' | 'reserved' | 'existing' | 'available' | 'unavailable'
}

const PLAYER_ID_LOOKUP_DEBOUNCE_MS = 250
const honorDifficultyDescription =
  '⚠️ Challenging legacy style, faithful to the original game. Dying loses all levels.'
const modernDifficultyDescription =
  '✨ Forgiving modern style with quality of life enhancements. Dying loses a single level.'

const sanitizePlayerIdInput = (value: string) =>
  value.replace(/[^A-Za-z]/g, '').slice(0, 9)

export const SessionForm = ({
  title = 'Request a token',
  eyebrow = 'Session',
  showAdminFields = true,
  showRoomField = true,
  showEndpoint = true,
  onSessionStarted,
}: SessionFormProps = {}) => {
  const {
    startSession,
    connectionStatus,
    error,
    apiBaseUrl,
    setAdminToken,
    session,
    currentRoom,
    resumeRememberedSession,
    runtimeMode,
  } = useNavigator()
  const [playerId, setPlayerId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [password, setPassword] = useState('')
  const [staticAdminToken, setStaticAdminToken] = useState('')
  const [joinAsAdmin, setJoinAsAdmin] = useState(false)
  const [claimNewPlayer, setClaimNewPlayer] = useState(false)
  const [characterBackground, setCharacterBackground] =
    useState<CharacterBackground>('lord')
  const [honorMode, setHonorMode] = useState(true)
  const [playerIdLookup, setPlayerIdLookup] = useState<PlayerIdLookup | null>(
    null
  )
  const [playerIdLookupLoading, setPlayerIdLookupLoading] = useState(false)
  const [legacyPlayerIdPrompt, setLegacyPlayerIdPrompt] = useState(
    fallbackLegacyPlayerIdPrompt
  )
  const [submitting, setSubmitting] = useState(false)
  const [rememberMe, setRememberMe] = useState(false)
  const autoResumeAttemptedRef = useRef(false)
  const difficultyNoteId = useId()
  const isPlayerEntry = !showAdminFields
  const usesAccountAuth = isPlayerEntry || (showAdminFields && joinAsAdmin)

  const trimmedPlayerId = playerId.trim()
  const isPlayerEntryAvailable =
    isPlayerEntry &&
    !playerIdLookupLoading &&
    playerIdLookup?.status === 'available'
  const isPlayerEntryKnownUnowned =
    isPlayerEntry &&
    !playerIdLookupLoading &&
    playerIdLookup?.status === 'existing' &&
    playerIdLookup.account_bound === false
  const effectiveClaimNewPlayer = isPlayerEntry
    ? isPlayerEntryAvailable || isPlayerEntryKnownUnowned
    : claimNewPlayer
  const difficultyDescription = honorMode
    ? honorDifficultyDescription
    : modernDifficultyDescription

  useEffect(() => {
    const storedPlayerId = localStorage.getItem(storageKeys.playerId)
    if (storedPlayerId) {
      setPlayerId(
        isPlayerEntry ? sanitizePlayerIdInput(storedPlayerId) : storedPlayerId
      )
    }

    const storedRoomId = localStorage.getItem(storageKeys.roomId)
    if (storedRoomId) {
      setRoomId(storedRoomId)
    }

    const storedAdminSession =
      localStorage.getItem(storageKeys.adminSession) === 'true'
    setJoinAsAdmin(storedAdminSession)
    setPassword('')
  }, [isPlayerEntry])

  useEffect(() => {
    if (!isPlayerEntry || session || autoResumeAttemptedRef.current) return
    if (window.location.pathname !== '/play') return
    autoResumeAttemptedRef.current = true
    void resumeRememberedSession()
  }, [isPlayerEntry, resumeRememberedSession, session])

  useEffect(() => {
    if (!isPlayerEntry) return

    if (trimmedPlayerId.length === 0) {
      setPlayerIdLookup(null)
      setPlayerIdLookupLoading(false)
      return
    }

    if (trimmedPlayerId.length < 3) {
      setPlayerIdLookup({
        player_id: trimmedPlayerId,
        canonical_player_id: trimmedPlayerId,
        valid: false,
        exists: false,
        available: false,
        reserved: false,
        status: 'invalid',
      })
      setPlayerIdLookupLoading(false)
      return
    }

    const controller = new AbortController()
    setPlayerIdLookupLoading(true)

    const loadPlayerId = async () => {
      try {
        const response = await fetch(
          `${apiBaseUrl}/public/player-id/${encodeURIComponent(trimmedPlayerId)}`,
          { signal: controller.signal }
        )
        if (!response.ok) throw new Error('Unable to check Player-ID')
        const payload = (await response.json()) as PlayerIdLookup
        setPlayerIdLookup(payload.status ? payload : null)
      } catch (err) {
        if (controller.signal.aborted) return
        setPlayerIdLookup({
          player_id: trimmedPlayerId,
          canonical_player_id: trimmedPlayerId,
          valid: true,
          exists: false,
          available: false,
          reserved: false,
          status: 'unavailable',
        })
      } finally {
        if (!controller.signal.aborted) {
          setPlayerIdLookupLoading(false)
        }
      }
    }

    const lookupTimer = window.setTimeout(() => {
      void loadPlayerId()
    }, PLAYER_ID_LOOKUP_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(lookupTimer)
      controller.abort()
    }
  }, [apiBaseUrl, isPlayerEntry, trimmedPlayerId])

  useEffect(() => {
    if (!effectiveClaimNewPlayer || isPlayerEntry) return

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
  }, [apiBaseUrl, effectiveClaimNewPlayer, isPlayerEntry])

  useEffect(() => {
    if (!runtimeMode.selectableHonorMode) {
      setHonorMode(true)
    }
  }, [runtimeMode.selectableHonorMode])

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
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    try {
      const parsedRoom =
        !showRoomField || effectiveClaimNewPlayer || roomId.trim() === ''
          ? null
          : Number(roomId)
      const trimmedPassword = password.trim()
      const trimmedStaticAdminToken = staticAdminToken.trim()

      if (!showAdminFields) {
        setAdminToken(null)
      }
      persistPlayerId(trimmedPlayerId)
      if (showRoomField && !effectiveClaimNewPlayer) {
        persistRoomId(roomId)
      }
      persistAdminSession(showAdminFields && joinAsAdmin)
      await startSession(
        trimmedPlayerId,
        Number.isNaN(parsedRoom) ? null : parsedRoom,
        {
          createPlayer: effectiveClaimNewPlayer,
          background:
            isPlayerEntry && isPlayerEntryAvailable
              ? characterBackground
              : undefined,
          password: usesAccountAuth ? trimmedPassword : undefined,
          authMode: usesAccountAuth
            ? effectiveClaimNewPlayer
              ? 'register'
              : 'login'
            : 'legacy',
          sessionKind: showAdminFields && joinAsAdmin ? 'admin' : 'game',
          rememberMe: usesAccountAuth && isPlayerEntry ? rememberMe : false,
          honorMode:
            effectiveClaimNewPlayer && runtimeMode.selectableHonorMode
              ? honorMode
              : undefined,
        }
      )
      if (showAdminFields && !joinAsAdmin && trimmedStaticAdminToken !== '') {
        setAdminToken(trimmedStaticAdminToken)
      }
      onSessionStarted?.()
    } catch {
      // startSession is responsible for updating shared error state.
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
  const playerIdStatus = useMemo(() => {
    if (!isPlayerEntry) return null
    if (trimmedPlayerId.length === 0) {
      return {
        state: 'idle',
        text: 'Choose 3-9 letters. This is the name Kyrandia will remember.',
      }
    }
    if (playerIdLookupLoading) {
      return { state: 'checking', text: `Looking for ${trimmedPlayerId}...` }
    }
    switch (playerIdLookup?.status) {
      case 'existing':
        if (playerIdLookup.account_bound === false) {
          return {
            state: 'existing',
            text: `${trimmedPlayerId} is known in Kyrandia and can be claimed with a password.`,
          }
        }
        return {
          state: 'existing',
          text: `${trimmedPlayerId} is already known in Kyrandia. Welcome back.`,
        }
      case 'available':
        return {
          state: 'available',
          text: `${trimmedPlayerId} is yours to claim, if you wish!`,
        }
      case 'reserved':
        return {
          state: 'reserved',
          text: `${trimmedPlayerId} is part of Kyrandia's old magic. Choose another name.`,
        }
      case 'invalid':
        return {
          state: 'invalid',
          text: 'Player IDs use 3-9 letters.',
        }
      case 'unavailable':
        return {
          state: 'unavailable',
          text: `I can't check that name right now. You can try to enter as ${trimmedPlayerId}.`,
        }
      default:
        return {
          state: 'idle',
          text: 'Choose 3-9 letters. This is the name Kyrandia will remember.',
        }
    }
  }, [
    isPlayerEntry,
    playerIdLookup?.account_bound,
    playerIdLookup?.status,
    playerIdLookupLoading,
    trimmedPlayerId,
  ])
  const canSubmit =
    trimmedPlayerId !== '' &&
    (!usesAccountAuth || password.trim() !== '') &&
    (!isPlayerEntry ||
      (!playerIdLookupLoading &&
        (playerIdLookup?.status === 'existing' ||
          playerIdLookup?.status === 'available' ||
          playerIdLookup?.status === 'unavailable')))
  const submitLabel = (() => {
    if (submitting)
      return effectiveClaimNewPlayer ? 'Opening the gates...' : 'Entering...'
    if (showAdminFields && joinAsAdmin) {
      return effectiveClaimNewPlayer ? 'Create admin account' : 'Admin login'
    }
    if (isPlayerEntry) {
      if (playerIdLookupLoading) return 'Checking Player-ID...'
      if (playerIdLookup?.status === 'existing' && isPlayerEntryKnownUnowned)
        return 'Claim Player-ID'
      if (playerIdLookup?.status === 'existing')
        return `Login as ${trimmedPlayerId}`
      if (playerIdLookup?.status === 'available') return 'Create Character...'
      if (playerIdLookup?.status === 'unavailable') return 'Try Login'
      return 'Enter Player ID'
    }
    return effectiveClaimNewPlayer ? 'Claim Player-ID' : 'Start session'
  })()

  return (
    <section className="panel session-form">
      <header className="panel-header">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          {showEndpoint && <p className="endpoint">API base: {apiBaseUrl}</p>}
        </div>
      </header>
      <div className="panel-body" data-testid="session-panel-body">
        <form onSubmit={handleSubmit} className="form-stack">
          <div className="field">
            <label htmlFor="player-id">Player ID</label>
            <input
              id="player-id"
              name="player-id"
              value={playerId}
              autoComplete="username"
              inputMode="text"
              maxLength={9}
              pattern="[A-Za-z]{3,9}"
              onChange={event => {
                const nextValue = sanitizePlayerIdInput(event.target.value)
                setPlayerId(nextValue)
                if (isPlayerEntry) {
                  setPlayerIdLookup(null)
                  setPlayerIdLookupLoading(nextValue.trim().length >= 3)
                }
                persistPlayerId(nextValue)
              }}
              required
            />
            {playerIdStatus && (
              <p className="player-id-status" data-state={playerIdStatus.state}>
                {playerIdStatus.text}
              </p>
            )}
          </div>

          {usesAccountAuth && (
            <div className="field">
              <label htmlFor="account-password">
                {showAdminFields && joinAsAdmin ? 'Admin password' : 'Password'}
              </label>
              <input
                id="account-password"
                name="account-password"
                type="password"
                value={password}
                autoComplete={
                  effectiveClaimNewPlayer ? 'new-password' : 'current-password'
                }
                onChange={event => setPassword(event.target.value)}
                required
              />
            </div>
          )}

          {usesAccountAuth && isPlayerEntry && (
            <label className="checkbox">
              <input
                type="checkbox"
                name="remember-me"
                checked={rememberMe}
                onChange={event => setRememberMe(event.target.checked)}
              />
              Remember me
            </label>
          )}

          {showRoomField && (
            <div className="field">
              <label htmlFor="room-id">Room ID (optional)</label>
              <input
                id="room-id"
                name="room-id"
                value={roomId}
                disabled={claimNewPlayer}
                onChange={event => {
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
          )}

          {!isPlayerEntry && (
            <label className="checkbox">
              <input
                type="checkbox"
                name="claim-new-player"
                checked={claimNewPlayer}
                onChange={event => setClaimNewPlayer(event.target.checked)}
              />
              Claim new Player-ID
            </label>
          )}

          {isPlayerEntry && isPlayerEntryAvailable && (
            <fieldset className="character-choice">
              <legend>Choose Background</legend>
              <label>
                <input
                  type="radio"
                  name="character-background"
                  value="lord"
                  checked={characterBackground === 'lord'}
                  onChange={() => setCharacterBackground('lord')}
                />
                <span>Lord</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="character-background"
                  value="lady"
                  checked={characterBackground === 'lady'}
                  onChange={() => setCharacterBackground('lady')}
                />
                <span>Lady</span>
              </label>
            </fieldset>
          )}

          {effectiveClaimNewPlayer && runtimeMode.selectableHonorMode && (
            <fieldset
              className="character-choice difficulty-choice"
              aria-describedby={difficultyNoteId}
            >
              <legend>Choose Difficulty</legend>
              <label>
                <input
                  type="radio"
                  name="honor-mode"
                  value="honor"
                  checked={honorMode}
                  onChange={() => setHonorMode(true)}
                />
                <span>Honor mode</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="honor-mode"
                  value="modern"
                  checked={!honorMode}
                  onChange={() => setHonorMode(false)}
                />
                <span>Modern mode</span>
              </label>
              <p className="difficulty-note" id={difficultyNoteId}>
                <span aria-live="polite">{difficultyDescription}</span>
                <span>Difficulty cannot be changed later.</span>
              </p>
            </fieldset>
          )}

          {effectiveClaimNewPlayer && !isPlayerEntry && (
            <p className="field-hint">
              <AnsiText text={legacyPlayerIdPrompt} />
            </p>
          )}

          {showAdminFields && !joinAsAdmin && (
            <div className="field">
              <label htmlFor="emergency-admin-token">
                Emergency admin token (optional)
              </label>
              <input
                id="emergency-admin-token"
                name="emergency-admin-token"
                type="password"
                value={staticAdminToken}
                autoComplete="off"
                onChange={event => setStaticAdminToken(event.target.value)}
              />
              <p className="field-hint">
                Use a private KYRGAME_ADMIN_TOKEN for emergency static-token deployments.
              </p>
            </div>
          )}

          {showAdminFields && (
            <>
              <label className="checkbox">
                <input
                  type="checkbox"
                  name="admin-session"
                  checked={joinAsAdmin}
                  onChange={event => {
                    const enabled = event.target.checked
                    setJoinAsAdmin(enabled)
                    persistAdminSession(enabled)
                    if (enabled) {
                      setStaticAdminToken('')
                    }
                    if (!enabled) {
                      setPassword('')
                      setAdminToken(null)
                    }
                  }}
                />
                Admin session
              </label>
            </>
          )}

          <button type="submit" disabled={submitting || !canSubmit}>
            {submitLabel}
          </button>
        </form>
        {!isPlayerEntry && (
          <p className={`status ${connectionStatus}`}>
            Connection: {connectionStatus}
          </p>
        )}
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
    </section>
  )
}
