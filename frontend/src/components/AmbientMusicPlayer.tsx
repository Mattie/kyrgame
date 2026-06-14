import {
  type ChangeEvent,
  type FocusEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { useNavigator, type PlayerLevelUpCue } from '../context/NavigatorContext'
import {
  LEVEL_UP_SFX_SRC,
  type AmbientTrack,
  areRoomsInSameAmbientArea,
  isLevelUpAmbientTrack,
  resolveAmbientTrack,
  resolveLevelUpTrack,
} from '../data/ambientMusic'

const DEFAULT_VOLUME = 0.3
const FADE_IN_MS = 1000
const CROSSFADE_MS = 2000
const FADE_STEP_MS = 50
const LEVEL_UP_AMBIENT_FADE_MS = Math.round(CROSSFADE_MS / 1.5)
const LEVEL_UP_DUCK_MS = 350
const COLLAPSE_DELAY_MS = 3000
const VOLUME_STORAGE_KEY = 'kyrgame.ambient.volume'
const MUTED_STORAGE_KEY = 'kyrgame.ambient.muted'

const clampVolume = (value: number) => Math.min(1, Math.max(0, value))

const readStoredVolume = () => {
  const raw = window.localStorage.getItem(VOLUME_STORAGE_KEY)
  if (raw === null) return DEFAULT_VOLUME
  const parsed = Number.parseFloat(raw)
  return Number.isFinite(parsed) ? clampVolume(parsed) : DEFAULT_VOLUME
}

const readStoredMuted = () => window.localStorage.getItem(MUTED_STORAGE_KEY) === 'true'

export const AmbientMusicPlayer = () => {
  const { currentRoom, latestLevelUpCue, session } = useNavigator()
  const [volume, setVolume] = useState(readStoredVolume)
  const [muted, setMuted] = useState(readStoredMuted)
  const [unlocked, setUnlocked] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [activeLevelUpCue, setActiveLevelUpCue] = useState<PlayerLevelUpCue | null>(null)
  const [status, setStatus] = useState<'waiting' | 'playing' | 'silent'>('waiting')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const audioRefs = useRef<[HTMLAudioElement | null, HTMLAudioElement | null]>([null, null])
  const levelUpSfxRef = useRef<HTMLAudioElement | null>(null)
  const levelUpSfxCleanupRef = useRef<(() => void) | null>(null)
  const activeIndexRef = useRef(0)
  const activeTrackRef = useRef<AmbientTrack | null>(null)
  const pendingTrackIdRef = useRef<string | null>(null)
  const transitionAttemptRef = useRef(0)
  const pendingAudioAttemptRef = useRef(new WeakMap<HTMLAudioElement, number>())
  const silenceFadeTrackIdRef = useRef<string | null>(null)
  const fadeTimerRef = useRef<number | null>(null)
  const collapseTimerRef = useRef<number | null>(null)
  const scheduleCollapseRef = useRef<(() => void) | null>(null)
  const targetVolumeRef = useRef(muted ? 0 : volume)
  const seenLevelUpCueRef = useRef<number | null>(null)
  const repeatArmedRef = useRef(false)
  const startTransitionRef = useRef<
    ((track: AmbientTrack | null, durationMs: number, repeat?: boolean) => void) | null
  >(null)

  const desiredTrack = useMemo(() => {
    const levelUpTrack = resolveLevelUpTrack(activeLevelUpCue)
    return levelUpTrack ?? resolveAmbientTrack(currentRoom)
  }, [activeLevelUpCue, currentRoom])

  const clearFadeTimer = useCallback(() => {
    if (fadeTimerRef.current !== null) {
      window.clearInterval(fadeTimerRef.current)
      fadeTimerRef.current = null
    }
  }, [])

  const clearCollapseTimer = useCallback(() => {
    if (collapseTimerRef.current !== null) {
      window.clearTimeout(collapseTimerRef.current)
      collapseTimerRef.current = null
    }
  }, [])

  const stopLevelUpSfx = useCallback(() => {
    const cleanup = levelUpSfxCleanupRef.current
    const audio = levelUpSfxRef.current
    levelUpSfxCleanupRef.current = null
    levelUpSfxRef.current = null
    cleanup?.()
    if (audio) {
      audio.pause()
      audio.currentTime = 0
    }
  }, [])

  const duckAmbientForLevelUp = useCallback(() => {
    const audioElements = audioRefs.current.filter((audio): audio is HTMLAudioElement =>
      Boolean(audio)
    )
    if (audioElements.length === 0) return

    clearFadeTimer()

    const startVolumes = audioElements.map((audio) => audio.volume)
    const steps = Math.max(1, Math.ceil(LEVEL_UP_DUCK_MS / FADE_STEP_MS))
    let step = 0
    fadeTimerRef.current = window.setInterval(() => {
      step += 1
      const progress = Math.min(1, step / steps)
      audioElements.forEach((audio, index) => {
        audio.volume = Math.min(startVolumes[index] * (1 - progress), targetVolumeRef.current)
      })
      if (progress >= 1) {
        clearFadeTimer()
      }
    }, FADE_STEP_MS)
  }, [clearFadeTimer])

  const playLevelUpSfx = useCallback((onComplete?: () => void) => {
    const targetVolume = targetVolumeRef.current
    if (!unlocked || targetVolume <= 0) return false

    stopLevelUpSfx()

    const sfxAudio = new Audio()
    let completed = false
    let cleanup = () => {}
    const complete = () => {
      if (completed) return
      completed = true
      cleanup()
      if (levelUpSfxRef.current === sfxAudio) {
        levelUpSfxCleanupRef.current = null
        levelUpSfxRef.current = null
      }
      onComplete?.()
    }
    const clearSfxRef = () => {
      complete()
    }
    cleanup = () => {
      sfxAudio.removeEventListener('ended', clearSfxRef)
      sfxAudio.removeEventListener('error', clearSfxRef)
    }

    sfxAudio.preload = 'auto'
    sfxAudio.src = LEVEL_UP_SFX_SRC
    sfxAudio.currentTime = 0
    sfxAudio.volume = targetVolume
    sfxAudio.addEventListener('ended', clearSfxRef)
    sfxAudio.addEventListener('error', clearSfxRef)
    levelUpSfxCleanupRef.current = cleanup
    levelUpSfxRef.current = sfxAudio

    void sfxAudio.play().catch(complete)
    return true
  }, [stopLevelUpSfx, unlocked])

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

  const applyAudioVolume = useCallback(() => {
    targetVolumeRef.current = muted ? 0 : volume
    const activeAudio = audioRefs.current[activeIndexRef.current]
    if (fadeTimerRef.current === null && activeAudio) {
      activeAudio.volume = targetVolumeRef.current
    } else {
      audioRefs.current.forEach((audio) => {
        if (audio && audio.volume > targetVolumeRef.current) {
          audio.volume = targetVolumeRef.current
        }
      })
    }
    if (levelUpSfxRef.current) {
      levelUpSfxRef.current.volume = targetVolumeRef.current
    }
  }, [muted, volume])

  const startTransition = useCallback(
    (track: AmbientTrack | null, durationMs: number, repeat = false) => {
      const activeAudio = audioRefs.current[activeIndexRef.current]
      if (!unlocked || !activeAudio) return

      if (!repeat && track && activeTrackRef.current?.id === track.id) {
        if (silenceFadeTrackIdRef.current === track.id) {
          clearFadeTimer()
          silenceFadeTrackIdRef.current = null
          repeatArmedRef.current = false
          activeAudio.volume = targetVolumeRef.current
          setStatus('playing')
        }
        return
      }

      if (!repeat && pendingTrackIdRef.current === track?.id) {
        return
      }

      clearFadeTimer()
      transitionAttemptRef.current += 1
      const transitionAttempt = transitionAttemptRef.current

      if (!track) {
        pendingTrackIdRef.current = null
        silenceFadeTrackIdRef.current = activeTrackRef.current?.id ?? null
        const startVolume = activeAudio.volume
        const steps = Math.max(1, Math.ceil(durationMs / FADE_STEP_MS))
        let step = 0
        fadeTimerRef.current = window.setInterval(() => {
          step += 1
          const progress = Math.min(1, step / steps)
          activeAudio.volume = Math.min(startVolume * (1 - progress), targetVolumeRef.current)
          if (progress >= 1) {
            clearFadeTimer()
            activeAudio.pause()
            activeAudio.currentTime = 0
            activeTrackRef.current = null
            silenceFadeTrackIdRef.current = null
            repeatArmedRef.current = false
            setStatus('silent')
          }
        }, FADE_STEP_MS)
        return
      }

      const nextIndex = activeIndexRef.current === 0 ? 1 : 0
      const nextAudio = audioRefs.current[nextIndex]
      if (!nextAudio) return

      nextAudio.pause()
      nextAudio.src = track.src
      nextAudio.preload = 'auto'
      nextAudio.currentTime = 0
      nextAudio.volume = 0
      repeatArmedRef.current = false
      pendingTrackIdRef.current = track.id
      silenceFadeTrackIdRef.current = null
      pendingAudioAttemptRef.current.set(nextAudio, transitionAttempt)

      const previousAudio = activeAudio
      const previousStartVolume = previousAudio.volume
      const steps = Math.max(1, Math.ceil(durationMs / FADE_STEP_MS))
      let step = 0
      const resetNextAudio = () => {
        nextAudio.pause()
        nextAudio.currentTime = 0
        nextAudio.volume = 0
        pendingAudioAttemptRef.current.delete(nextAudio)
      }

      void nextAudio
        .play()
        .then(() => {
          if (transitionAttemptRef.current !== transitionAttempt) {
            if (pendingAudioAttemptRef.current.get(nextAudio) === transitionAttempt) {
              resetNextAudio()
            }
            return
          }
          setStatus('playing')
          pendingTrackIdRef.current = null
          pendingAudioAttemptRef.current.delete(nextAudio)
          activeIndexRef.current = nextIndex
          activeTrackRef.current = track

          fadeTimerRef.current = window.setInterval(() => {
            step += 1
            const progress = Math.min(1, step / steps)
            const targetVolume = targetVolumeRef.current
            nextAudio.volume = targetVolume * progress
            previousAudio.volume = Math.min(previousStartVolume * (1 - progress), targetVolume)
            if (progress >= 1) {
              clearFadeTimer()
              previousAudio.pause()
              previousAudio.currentTime = 0
              previousAudio.volume = 0
            }
          }, FADE_STEP_MS)
        })
        .catch(() => {
          if (transitionAttemptRef.current !== transitionAttempt) {
            if (pendingAudioAttemptRef.current.get(nextAudio) === transitionAttempt) {
              resetNextAudio()
            }
            return
          }
          resetNextAudio()
          repeatArmedRef.current = false
          pendingTrackIdRef.current = null
          setStatus('waiting')
        })
    },
    [clearFadeTimer, unlocked]
  )

  startTransitionRef.current = startTransition

  useEffect(() => {
    const firstAudio = new Audio()
    const secondAudio = new Audio()
    const audioElements: [HTMLAudioElement, HTMLAudioElement] = [firstAudio, secondAudio]
    const cleanupListeners: Array<() => void> = []
    audioRefs.current = audioElements
    audioElements.forEach((audio) => {
      audio.preload = 'auto'
      const handleEnded = () => {
        const track = activeTrackRef.current
        if (!track || audio !== audioRefs.current[activeIndexRef.current]) return
        if (isLevelUpAmbientTrack(track)) {
          setActiveLevelUpCue(null)
          return
        }
        startTransitionRef.current?.(track, CROSSFADE_MS, true)
      }
      const handleTimeUpdate = () => {
        const track = activeTrackRef.current
        if (
          !track ||
          isLevelUpAmbientTrack(track) ||
          repeatArmedRef.current ||
          audio !== audioRefs.current[activeIndexRef.current]
        ) {
          return
        }
        if (
          Number.isFinite(audio.duration) &&
          audio.duration > CROSSFADE_MS / 1000 &&
          audio.duration - audio.currentTime <= CROSSFADE_MS / 1000
        ) {
          repeatArmedRef.current = true
          startTransitionRef.current?.(track, CROSSFADE_MS, true)
        }
      }
      audio.addEventListener('ended', handleEnded)
      audio.addEventListener('timeupdate', handleTimeUpdate)
      cleanupListeners.push(() => {
        audio.removeEventListener('ended', handleEnded)
        audio.removeEventListener('timeupdate', handleTimeUpdate)
      })
    })

    return () => {
      clearFadeTimer()
      stopLevelUpSfx()
      cleanupListeners.forEach((cleanup) => cleanup())
      audioElements.forEach((audio) => audio.pause())
      audioRefs.current = [null, null]
    }
  }, [clearFadeTimer, stopLevelUpSfx])

  useEffect(() => {
    window.localStorage.setItem(VOLUME_STORAGE_KEY, String(volume))
    window.localStorage.setItem(MUTED_STORAGE_KEY, muted ? 'true' : 'false')
    applyAudioVolume()
  }, [applyAudioVolume, muted, volume])

  useEffect(() => clearCollapseTimer, [clearCollapseTimer])

  useEffect(() => {
    if (expanded) {
      scheduleCollapse()
      return
    }
    clearCollapseTimer()
  }, [clearCollapseTimer, expanded, scheduleCollapse])

  useEffect(() => {
    if (unlocked) return
    const unlock = () => setUnlocked(true)
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    return () => {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }, [unlocked])

  useEffect(() => {
    if (!latestLevelUpCue || latestLevelUpCue.sequence === seenLevelUpCueRef.current) return
    seenLevelUpCueRef.current = latestLevelUpCue.sequence
    const levelUpTrack = resolveLevelUpTrack(latestLevelUpCue)
    const resumeAmbientAfterSfx = () => {
      if (levelUpTrack) {
        setActiveLevelUpCue(latestLevelUpCue)
        startTransitionRef.current?.(levelUpTrack, LEVEL_UP_AMBIENT_FADE_MS, true)
        return
      }

      startTransitionRef.current?.(resolveAmbientTrack(currentRoom), CROSSFADE_MS, true)
    }

    if (playLevelUpSfx(resumeAmbientAfterSfx)) {
      duckAmbientForLevelUp()
      return
    }

    resumeAmbientAfterSfx()
  }, [currentRoom, duckAmbientForLevelUp, latestLevelUpCue, playLevelUpSfx])

  useEffect(() => {
    if (
      activeLevelUpCue &&
      currentRoom !== null &&
      !areRoomsInSameAmbientArea(activeLevelUpCue.location, currentRoom)
    ) {
      setActiveLevelUpCue(null)
    }
  }, [activeLevelUpCue, currentRoom])

  useEffect(() => {
    if (!session) {
      stopLevelUpSfx()
      setActiveLevelUpCue(null)
      startTransitionRef.current?.(null, CROSSFADE_MS, true)
    }
  }, [session, stopLevelUpSfx])

  useEffect(() => {
    if (!unlocked) return
    const initial = activeTrackRef.current === null
    startTransition(desiredTrack, initial ? FADE_IN_MS : CROSSFADE_MS)
  }, [desiredTrack, startTransition, unlocked])

  const retryWaitingPlayback = () => {
    if (status !== 'waiting') return
    const initial = activeTrackRef.current === null
    startTransitionRef.current?.(desiredTrack, initial ? FADE_IN_MS : CROSSFADE_MS)
  }

  const handleToggle = () => {
    if (!expanded) {
      setExpanded(true)
      if (!unlocked) {
        setUnlocked(true)
      } else {
        retryWaitingPlayback()
      }
      return
    }
    if (!unlocked) {
      setUnlocked(true)
      if (effectiveMuted) {
        if (volume === 0) {
          setVolume(DEFAULT_VOLUME)
        }
        setMuted(false)
      }
      return
    }
    if (status === 'waiting') {
      retryWaitingPlayback()
      return
    }
    if (effectiveMuted) {
      if (volume === 0) {
        targetVolumeRef.current = DEFAULT_VOLUME
        setVolume(DEFAULT_VOLUME)
      } else {
        targetVolumeRef.current = volume
      }
      setMuted(false)
      retryWaitingPlayback()
      return
    }
    setMuted((current) => !current)
  }

  const handleVolumeChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextVolume = clampVolume(Number(event.target.value) / 100)
    targetVolumeRef.current = nextVolume
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
      : !unlocked
        ? 'Enable ambient music'
        : 'Mute ambient music'
  const icon = effectiveMuted ? '\u{1F507}' : '\u{1F50A}'

  return (
    <div
      ref={rootRef}
      className="ambient-music-player"
      data-state={status}
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
          <span className="sr-only">Ambient volume</span>
          <input
            aria-label="Ambient volume"
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
