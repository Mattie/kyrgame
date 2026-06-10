import { type FocusEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getWebSocketUrl } from '../config/endpoints'
import { useNavigator } from '../context/NavigatorContext'

type ActivePlayerSummary = {
  player_id: string
  display_name: string
  level: number
  rank_title: string
  wizard_symbol?: string | null
  active: boolean
  connected_at?: string | null
  connection_duration_seconds?: number | null
}

type PlayerActivityPayload = {
  active?: ActivePlayerSummary[]
}

const POLL_INTERVAL_MS = 30_000
type ScryStatus = 'idle' | 'connecting' | 'active' | 'closed' | 'error'

const formatConnectionDuration = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined) return 'just now'
  const safeSeconds = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const remainingSeconds = safeSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${remainingSeconds}s`
  return `${remainingSeconds}s`
}

const formatConnectionDurationDateTime = (seconds: number | null | undefined) => {
  const safeSeconds = Math.max(0, Math.floor(seconds ?? 0))
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const remainingSeconds = safeSeconds % 60
  const hoursPart = hours > 0 ? `${hours}H` : ''
  const minutesPart = minutes > 0 ? `${minutes}M` : ''
  const secondsPart =
    remainingSeconds > 0 || (hours === 0 && minutes === 0) ? `${remainingSeconds}S` : ''
  return `PT${hoursPart}${minutesPart}${secondsPart}`
}

const activePlayerSummariesEqual = (
  left: ActivePlayerSummary[],
  right: ActivePlayerSummary[]
) =>
  left.length === right.length &&
  left.every((player, index) => {
    const nextPlayer = right[index]
    return (
      player.player_id === nextPlayer.player_id &&
      player.display_name === nextPlayer.display_name &&
      player.level === nextPlayer.level &&
      player.rank_title === nextPlayer.rank_title &&
      player.wizard_symbol === nextPlayer.wizard_symbol &&
      player.active === nextPlayer.active &&
      player.connected_at === nextPlayer.connected_at &&
      player.connection_duration_seconds === nextPlayer.connection_duration_seconds
    )
  })

export const ActivePlayerIndicator = () => {
  const { apiBaseUrl, connectionStatus, adminToken, session, logoutSession } = useNavigator()
  const wsBaseUrl = useMemo(() => getWebSocketUrl(), [])
  const [players, setPlayers] = useState<ActivePlayerSummary[]>([])
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [scryTarget, setScryTarget] = useState<ActivePlayerSummary | null>(null)
  const [scryStatus, setScryStatus] = useState<ScryStatus>('idle')
  const [scryEventCount, setScryEventCount] = useState(0)
  const scrySocketRef = useRef<WebSocket | null>(null)
  const visible = (open || hovered) && !dismissed

  const loadPlayers = useCallback(async (options?: { cancelled?: () => boolean; signal?: AbortSignal }) => {
    try {
      const response = await fetch(`${apiBaseUrl}/public/player-activity`, {
        signal: options?.signal,
      })
      if (!response.ok) throw new Error('Unable to load active players')
      const payload = (await response.json()) as PlayerActivityPayload
      if (!options?.cancelled?.()) {
        const activePlayers = Array.isArray(payload.active)
          ? payload.active.filter((player) => player.active)
          : []
        setPlayers((current) =>
          activePlayerSummariesEqual(current, activePlayers) ? current : activePlayers
        )
      }
    } catch {
      if (!options?.signal?.aborted && !options?.cancelled?.()) {
        setPlayers((current) => (current.length === 0 ? current : []))
      }
    }
  }, [apiBaseUrl])

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const isCancelled = () => cancelled
    void loadPlayers({ cancelled: isCancelled, signal: controller.signal })
    const interval = window.setInterval(
      () => void loadPlayers({ cancelled: isCancelled, signal: controller.signal }),
      POLL_INTERVAL_MS
    )
    return () => {
      cancelled = true
      controller.abort()
      window.clearInterval(interval)
    }
  }, [loadPlayers])

  useEffect(() => {
    if (connectionStatus === 'connected' || connectionStatus === 'disconnected') {
      let cancelled = false
      const controller = new AbortController()
      void loadPlayers({ cancelled: () => cancelled, signal: controller.signal })
      return () => {
        cancelled = true
        controller.abort()
      }
    }
  }, [connectionStatus, loadPlayers])

  const sortedPlayers = useMemo(
    () =>
      [...players].sort((left, right) => {
        const leftDuration = left.connection_duration_seconds ?? Number.MAX_SAFE_INTEGER
        const rightDuration = right.connection_duration_seconds ?? Number.MAX_SAFE_INTEGER
        if (leftDuration !== rightDuration) return leftDuration - rightDuration
        return left.display_name.localeCompare(right.display_name)
      }),
    [players]
  )

  const closePopover = useCallback(() => {
    setOpen(false)
    setHovered(false)
    setDismissed(true)
  }, [])

  const openPopover = useCallback(() => {
    setDismissed(false)
    setOpen(true)
  }, [])

  const handleMouseLeave = useCallback(() => {
    setHovered(false)
    setDismissed(false)
  }, [])

  const handleBlur = useCallback((event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setHovered(false)
      setDismissed(false)
    }
  }, [])

  const stopScry = useCallback(() => {
    const socket = scrySocketRef.current
    scrySocketRef.current = null
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close(1000, 'SCRY stopped')
    }
    setScryStatus('idle')
    setScryTarget(null)
    setScryEventCount(0)
  }, [])

  const handleLogout = useCallback(async () => {
    await logoutSession()
    await loadPlayers()
    closePopover()
  }, [closePopover, loadPlayers, logoutSession])

  const startScry = useCallback(
    (player: ActivePlayerSummary) => {
      if (!adminToken) return
      const existingSocket = scrySocketRef.current
      if (existingSocket && existingSocket.readyState !== WebSocket.CLOSED) {
        existingSocket.close(1000, 'Switching SCRY target')
      }
      setScryTarget(player)
      setScryStatus('connecting')
      setScryEventCount(0)
      const socket = new WebSocket(
        `${wsBaseUrl}/admin/scry/${encodeURIComponent(player.player_id)}?token=${encodeURIComponent(
          adminToken
        )}`
      )
      scrySocketRef.current = socket
      socket.onopen = () => setScryStatus('active')
      socket.onmessage = () => setScryEventCount((count) => count + 1)
      socket.onerror = () => setScryStatus('error')
      socket.onclose = () => {
        if (scrySocketRef.current === socket) {
          scrySocketRef.current = null
          setScryStatus((current) => (current === 'idle' ? current : 'closed'))
        }
      }
    },
    [adminToken, wsBaseUrl]
  )

  useEffect(() => {
    if (!adminToken && scrySocketRef.current) {
      stopScry()
    }
  }, [adminToken, stopScry])

  useEffect(
    () => () => {
      const socket = scrySocketRef.current
      scrySocketRef.current = null
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        socket.close(1000, 'SCRY component unmounted')
      }
    },
    []
  )

  return (
    <div
      className="active-player-indicator"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={handleMouseLeave}
      onFocus={() => setHovered(true)}
      onBlur={handleBlur}
      onKeyDown={(event) => {
        if (event.key === 'Escape') closePopover()
      }}
    >
      <button
        type="button"
        className="active-player-trigger"
        aria-expanded={visible}
        aria-label={`Active players: ${sortedPlayers.length}`}
        onClick={() => {
          if (open) {
            closePopover()
            return
          }
          openPopover()
        }}
      >
        <span className="active-player-count">{sortedPlayers.length}</span>
        <span>active</span>
      </button>
      {scryTarget && scryStatus !== 'idle' && (
        <div className="scry-banner" role="status" aria-label="SCRY session">
          <span>
            SCRY {scryStatus}: {scryTarget.display_name}
            {scryEventCount > 0 ? ` (${scryEventCount})` : ''}
          </span>
          <button type="button" onClick={stopScry}>
            Stop
          </button>
        </div>
      )}
      {visible && (
        <div className="active-player-popover" role="dialog" aria-label="Active players">
          <div className="active-player-popover-header">
            <span>Active players</span>
            {session?.sessionKind === 'game' && (
              <button
                type="button"
                className="logout-button"
                aria-label={`Log out ${session.playerId}`}
                onClick={() => void handleLogout()}
              >
                Logout
              </button>
            )}
            <button type="button" aria-label="Close active player list" onClick={closePopover}>
              X
            </button>
          </div>
          {sortedPlayers.length === 0 ? (
            <p className="muted">No active players.</p>
          ) : (
            <ul>
              {sortedPlayers.map((player) => (
                <li key={player.player_id} data-testid="active-player-row">
                  <span className="active-player-identity">
                    <span className="active-player-symbol" aria-hidden="true">
                      {player.wizard_symbol ?? '🧙‍♂️'}
                    </span>
                    <strong data-testid="active-player-name">{player.display_name}</strong>
                    <small>{player.rank_title}</small>
                  </span>
                  <time dateTime={formatConnectionDurationDateTime(player.connection_duration_seconds)}>
                    {formatConnectionDuration(player.connection_duration_seconds)}
                  </time>
                  {adminToken && (
                    <button
                      type="button"
                      className="scry-button"
                      aria-label={`Start SCRY for ${player.display_name}`}
                      onClick={() => startScry(player)}
                    >
                      SCRY
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
