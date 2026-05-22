import { useCallback, useEffect, useMemo, useState } from 'react'

import { AdminMobRecord, AdminMobSnapshot, useNavigator } from '../context/NavigatorContext'

const REFRESH_INTERVAL_MS = 15_000

const formatSeconds = (seconds?: number | null) => {
  if (seconds === undefined || seconds === null) return 'n/a'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`
}

const formatRoom = (mob: AdminMobRecord) => {
  if (mob.room_id === undefined || mob.room_id === null) return 'No current room'
  const brief = mob.room?.brief
  return brief ? `Room ${mob.room_id}: ${brief}` : `Room ${mob.room_id}`
}

const formatMobDetail = (mob: AdminMobRecord) => {
  if (mob.id === 'brownie') {
    const nextRoom =
      mob.next_room_id === undefined || mob.next_room_id === null
        ? 'next unknown'
        : `next ${mob.next_room_id}`
    return `path ${mob.path_index ?? '?'} of ${mob.path_length ?? '?'}; ${nextRoom}`
  }
  if (mob.id === 'elf') {
    return `next ${mob.next_outcome ?? 'event'}; hint ${mob.hint_index ?? 0}`
  }
  return mob.status.replace(/_/g, ' ')
}

export const AdminMobPanel = () => {
  const { adminToken, currentRoom, fetchAdminMobs, session, triggerElf } = useNavigator()
  const [snapshot, setSnapshot] = useState<AdminMobSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [triggeringElf, setTriggeringElf] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [triggerStatus, setTriggerStatus] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)

  const loadMobs = useCallback(async () => {
    if (!adminToken) return
    setLoading(true)
    setError(null)
    try {
      const next = await fetchAdminMobs()
      setSnapshot(next)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to refresh mob data')
    } finally {
      setLoading(false)
    }
  }, [adminToken, fetchAdminMobs])

  const handleTriggerElf = useCallback(async () => {
    if (!session) {
      setError('Start a session before triggering the elf')
      return
    }
    const roomId = currentRoom ?? session.roomId
    setTriggeringElf(true)
    setError(null)
    setTriggerStatus(null)
    try {
      const result = await triggerElf(session.playerId, roomId)
      setSnapshot(result.snapshot)
      setLastUpdated(new Date().toLocaleTimeString())
      setTriggerStatus(
        result.status === 'triggered'
          ? `Elf triggered: ${result.outcome}`
          : 'Elf trigger found no active player'
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to trigger elf')
    } finally {
      setTriggeringElf(false)
    }
  }, [currentRoom, session, triggerElf])

  useEffect(() => {
    if (!adminToken) {
      setSnapshot(null)
      setError(null)
      return
    }

    void loadMobs()
    const refreshId = window.setInterval(() => {
      void loadMobs()
    }, REFRESH_INTERVAL_MS)
    return () => window.clearInterval(refreshId)
  }, [adminToken, loadMobs])

  const mobs = useMemo(() => snapshot?.mobs ?? [], [snapshot?.mobs])

  if (!adminToken) return null

  return (
    <section className="panel admin-mob-panel">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Admin only</p>
          <h2>Mob tracker</h2>
          {snapshot && (
            <p className="muted">
              Next {snapshot.animation.next_routine}; tick every{' '}
              {formatSeconds(snapshot.animation.animation_tick_interval_seconds)}
            </p>
          )}
        </div>
        <div className="mob-panel-actions">
          <button type="button" onClick={handleTriggerElf} disabled={triggeringElf || !session}>
            {triggeringElf ? 'Triggering...' : 'Trigger Elf'}
          </button>
          <button type="button" onClick={loadMobs} disabled={loading}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </header>

      <div className="mob-panel-body">
        {error && <p className="status error">{error}</p>}
        {triggerStatus && <p className="field-hint">{triggerStatus}</p>}
        {lastUpdated && <p className="field-hint">Updated {lastUpdated}</p>}
        {snapshot && (
          <div className="mob-timing">
            <span>Brownie step {formatSeconds(snapshot.animation.brownie_routine_interval_seconds)}</span>
            <span>Full path {formatSeconds(snapshot.animation.brownie_full_path_interval_seconds)}</span>
          </div>
        )}
        <div className="mob-list">
          {mobs.map((mob) => (
            <article className="mob-row" key={mob.id}>
              <div>
                <h3>{mob.name}</h3>
                <p>{formatRoom(mob)}</p>
              </div>
              <span>{formatMobDetail(mob)}</span>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
