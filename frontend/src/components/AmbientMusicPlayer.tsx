import { type ChangeEvent, type FocusEvent, useCallback, useEffect, useRef, useState } from 'react'

import {
  AmbientAudioRuntime,
  type AudioRuntimeSnapshot,
} from '../audio/ambientAudioRuntime'
import { useNavigator } from '../context/NavigatorContext'

const DEFAULT_VOLUME = 0.3
const COLLAPSE_DELAY_MS = 3000
const VOLUME_STORAGE_KEY = 'kyrgame.ambient.volume'
const MUTED_STORAGE_KEY = 'kyrgame.ambient.muted'

const clampVolume = (value: number) => Math.min(1, Math.max(0, value))

const safeReadStorage = (key: string) => {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

const safeWriteStorage = (key: string, value: string) => {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Browsers can block storage in privacy modes; audio still works with in-memory state.
  }
}

const readStoredVolume = () => {
  const raw = safeReadStorage(VOLUME_STORAGE_KEY)
  if (raw === null) return DEFAULT_VOLUME
  const parsed = Number.parseFloat(raw)
  return Number.isFinite(parsed) ? clampVolume(parsed) : DEFAULT_VOLUME
}

const readStoredMuted = () => safeReadStorage(MUTED_STORAGE_KEY) === 'true'

export const AmbientMusicPlayer = () => {
  const { currentRoom, gameSessionReplaced, latestLevelUpCue, session } = useNavigator()
  const runtimeRef = useRef<AmbientAudioRuntime | null>(null)
  if (!runtimeRef.current) {
    runtimeRef.current = new AmbientAudioRuntime()
  }
  const runtime = runtimeRef.current
  const [volume, setVolume] = useState(readStoredVolume)
  const [muted, setMuted] = useState(readStoredMuted)
  const [expanded, setExpanded] = useState(false)
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<AudioRuntimeSnapshot>(() =>
    runtime.getSnapshot()
  )
  const rootRef = useRef<HTMLDivElement | null>(null)
  const collapseTimerRef = useRef<number | null>(null)
  const scheduleCollapseRef = useRef<(() => void) | null>(null)

  const clearCollapseTimer = useCallback(() => {
    if (collapseTimerRef.current !== null) {
      window.clearTimeout(collapseTimerRef.current)
      collapseTimerRef.current = null
    }
  }, [])

  const shouldKeepExpanded = useCallback(() => {
    const root = rootRef.current
    const activeElement = document.activeElement
    return Boolean(
      root && (root.matches(':hover') || (activeElement && root.contains(activeElement)))
    )
  }, [])

  const scheduleCollapse = useCallback(() => {
    clearCollapseTimer()
    collapseTimerRef.current = window.setTimeout(() => {
      collapseTimerRef.current = null
      if (shouldKeepExpanded()) {
        scheduleCollapseRef.current?.()
        return
      }
      setExpanded(false)
    }, COLLAPSE_DELAY_MS)
  }, [clearCollapseTimer, shouldKeepExpanded])

  scheduleCollapseRef.current = scheduleCollapse

  useEffect(() => {
    const unsubscribe = runtime.subscribe(setRuntimeSnapshot)
    return () => {
      unsubscribe()
      runtime.dispose()
    }
  }, [runtime])

  useEffect(() => {
    safeWriteStorage(VOLUME_STORAGE_KEY, String(volume))
    safeWriteStorage(MUTED_STORAGE_KEY, muted ? 'true' : 'false')
    runtime.setMasterVolume(volume)
    runtime.setMasterMuted(muted)
  }, [muted, runtime, volume])

  useEffect(() => clearCollapseTimer, [clearCollapseTimer])

  useEffect(() => {
    if (expanded) {
      scheduleCollapse()
      return
    }
    clearCollapseTimer()
  }, [clearCollapseTimer, expanded, scheduleCollapse])

  useEffect(() => {
    if (runtimeSnapshot.unlocked) return
    const unlock = () => runtime.unlock()
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    return () => {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }, [runtime, runtimeSnapshot.unlocked])

  useEffect(() => {
    runtime.setRoom(currentRoom)
  }, [currentRoom, runtime])

  useEffect(() => {
    runtime.setSessionActive(session?.sessionKind === 'game' && !gameSessionReplaced)
  }, [gameSessionReplaced, runtime, session?.sessionKind])

  useEffect(() => {
    runtime.handleLevelUpCue(latestLevelUpCue)
  }, [latestLevelUpCue, runtime])

  const retryWaitingPlayback = () => {
    if (runtimeSnapshot.status !== 'waiting') return
    runtime.retry()
  }

  const handleToggle = () => {
    if (!expanded) {
      setExpanded(true)
      if (!runtimeSnapshot.unlocked) {
        runtime.unlock()
      } else {
        retryWaitingPlayback()
      }
      return
    }
    if (!runtimeSnapshot.unlocked) {
      runtime.unlock()
      if (effectiveMuted) {
        if (volume === 0) {
          setVolume(DEFAULT_VOLUME)
        }
        setMuted(false)
      }
      return
    }
    if (runtimeSnapshot.status === 'waiting') {
      retryWaitingPlayback()
      return
    }
    if (effectiveMuted) {
      if (volume === 0) {
        setVolume(DEFAULT_VOLUME)
      }
      setMuted(false)
      retryWaitingPlayback()
      return
    }
    setMuted((current) => !current)
  }

  const handleVolumeChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextVolume = clampVolume(Number(event.target.value) / 100)
    setVolume(nextVolume)
    if (nextVolume > 0) {
      setMuted(false)
    }
    retryWaitingPlayback()
  }

  const handleControlBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      scheduleCollapse()
    }
  }

  if (session?.sessionKind === 'admin') return null

  const effectiveMuted = muted || volume === 0
  const buttonLabel = !expanded
    ? 'Open ambient music controls'
    : effectiveMuted
      ? 'Unmute ambient music'
      : !runtimeSnapshot.unlocked
        ? 'Enable ambient music'
        : 'Mute ambient music'
  const icon = effectiveMuted ? '\u{1F507}' : '\u{1F50A}'

  return (
    <div
      ref={rootRef}
      className="ambient-music-player"
      data-state={runtimeSnapshot.status}
      data-expanded={expanded}
      data-testid="ambient-music-player"
      onPointerEnter={scheduleCollapse}
      onPointerLeave={scheduleCollapse}
      onMouseEnter={scheduleCollapse}
      onMouseLeave={scheduleCollapse}
      onFocus={scheduleCollapse}
      onBlur={handleControlBlur}
    >
      <button
        type="button"
        className="ambient-music-toggle"
        aria-label={buttonLabel}
        aria-expanded={expanded}
        aria-pressed={effectiveMuted}
        onClick={handleToggle}
      >
        <span aria-hidden="true">{icon}</span>
      </button>
      {expanded && (
        <label className="ambient-volume-control">
          <span className="sr-only">Audio volume</span>
          <input
            aria-label="Audio volume"
            type="range"
            min="0"
            max="100"
            step="1"
            value={Math.round(volume * 100)}
            onChange={handleVolumeChange}
          />
        </label>
      )}
    </div>
  )
}
