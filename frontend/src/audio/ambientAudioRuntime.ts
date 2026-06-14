import {
  LEVEL_UP_SFX_SRC,
  type AmbientTrack,
  areRoomsInSameAmbientArea,
  isLevelUpAmbientTrack,
  resolveAmbientTrack,
  resolveLevelUpTrack,
} from '../data/ambientMusic'

export type AudioRuntimeStatus = 'waiting' | 'playing' | 'silent'

export type AudioRuntimeSnapshot = {
  status: AudioRuntimeStatus
  unlocked: boolean
}

export type AudioRuntimeLevelUpCue = {
  sequence: number
  location: number | null
}

export type AmbientAudioRuntimeOptions = {
  audioFactory?: () => HTMLAudioElement
  fadeStepMs?: number
}

type AmbientDeck = {
  audio: HTMLAudioElement
  gain: number
  track: AmbientTrack | null
  removeListeners: () => void
}

type PendingAmbient = {
  operationId: number
  deckIndex: number
  trackId: string
  repeat: boolean
}

const DEFAULT_MASTER_VOLUME = 0.3
const FADE_IN_MS = 1000
const CROSSFADE_MS = 2000
const DEFAULT_FADE_STEP_MS = 50
const LEVEL_UP_AMBIENT_FADE_MS = Math.round(CROSSFADE_MS / 1.5)
const LEVEL_UP_DUCK_MS = 350

const clampVolume = (value: number) => Math.min(1, Math.max(0, value))

export class AmbientAudioRuntime {
  private audioFactory: () => HTMLAudioElement
  private fadeStepMs: number
  private decks: [AmbientDeck, AmbientDeck]
  private activeDeckIndex = 0
  private activeTrack: AmbientTrack | null = null
  private pendingAmbient: PendingAmbient | null = null
  private ambientOperationId = 0
  private duckOperationId = 0
  private sfxOperationId = 0
  private levelUpOperationId = 0
  private ambientFadeTimer: number | null = null
  private duckFadeTimer: number | null = null
  private sfxAudio: HTMLAudioElement | null = null
  private sfxCleanup: (() => void) | null = null
  private currentRoom: number | null = null
  private sessionActive = false
  private unlocked = false
  private masterVolume = DEFAULT_MASTER_VOLUME
  private masterMuted = false
  private seenLevelUpSequence: number | null = null
  private activeLevelUpCue: AudioRuntimeLevelUpCue | null = null
  private ambientSuspendedForSfx = false
  private status: AudioRuntimeStatus = 'waiting'
  private subscribers = new Set<(snapshot: AudioRuntimeSnapshot) => void>()

  constructor(options: AmbientAudioRuntimeOptions = {}) {
    this.audioFactory = options.audioFactory ?? (() => new Audio())
    this.fadeStepMs = options.fadeStepMs ?? DEFAULT_FADE_STEP_MS
    this.decks = [this.createDeck(), this.createDeck()]
  }

  getSnapshot(): AudioRuntimeSnapshot {
    return {
      status: this.status,
      unlocked: this.unlocked,
    }
  }

  subscribe(listener: (snapshot: AudioRuntimeSnapshot) => void) {
    this.subscribers.add(listener)
    listener(this.getSnapshot())
    return () => {
      this.subscribers.delete(listener)
    }
  }

  unlock() {
    if (this.unlocked) return
    this.unlocked = true
    this.notify()
    this.requestDesiredAmbient(this.activeTrack ? CROSSFADE_MS : FADE_IN_MS)
  }

  retry() {
    if (this.status !== 'waiting') return
    this.requestDesiredAmbient(this.activeTrack ? CROSSFADE_MS : FADE_IN_MS)
  }

  setRoom(room: number | null) {
    if (this.currentRoom === room) return
    this.currentRoom = room
    if (
      this.activeLevelUpCue &&
      !areRoomsInSameAmbientArea(this.activeLevelUpCue.location, this.currentRoom)
    ) {
      this.activeLevelUpCue = null
    }
    if (this.ambientSuspendedForSfx) return
    this.requestDesiredAmbient(this.activeTrack ? CROSSFADE_MS : FADE_IN_MS)
  }

  setSessionActive(active: boolean) {
    if (this.sessionActive === active) return
    this.sessionActive = active
    if (!active) {
      this.levelUpOperationId += 1
      this.activeLevelUpCue = null
      this.ambientSuspendedForSfx = false
      this.stopSfx()
      this.requestAmbientTrack(null, CROSSFADE_MS)
      return
    }
    this.requestDesiredAmbient(this.activeTrack ? CROSSFADE_MS : FADE_IN_MS)
  }

  setMasterVolume(volume: number) {
    this.masterVolume = clampVolume(volume)
    this.applyVolumes()
  }

  setMasterMuted(muted: boolean) {
    this.masterMuted = muted
    this.applyVolumes()
  }

  handleLevelUpCue(cue: AudioRuntimeLevelUpCue | null | undefined) {
    if (!cue || cue.sequence === this.seenLevelUpSequence || !this.sessionActive) return
    this.seenLevelUpSequence = cue.sequence
    const levelUpTrack = resolveLevelUpTrack(cue)
    const levelUpOperation = ++this.levelUpOperationId
    this.activeLevelUpCue = null

    const resumeAfterSfx = () => {
      if (this.levelUpOperationId !== levelUpOperation || !this.sessionActive) return
      this.ambientSuspendedForSfx = false
      this.cancelDuckFade()
      const roomAtCompletion = this.currentRoom
      if (levelUpTrack && areRoomsInSameAmbientArea(cue.location, roomAtCompletion)) {
        this.activeLevelUpCue = cue
        this.requestAmbientTrack(levelUpTrack, LEVEL_UP_AMBIENT_FADE_MS, {
          forceRestart: true,
        })
        return
      }
      this.activeLevelUpCue = null
      this.requestAmbientTrack(resolveAmbientTrack(roomAtCompletion), CROSSFADE_MS)
    }

    if (this.playSfx(resumeAfterSfx)) {
      this.ambientSuspendedForSfx = true
      this.duckAmbientForLevelUp()
      return
    }
    this.ambientSuspendedForSfx = false
    resumeAfterSfx()
  }

  dispose() {
    this.levelUpOperationId += 1
    this.ambientOperationId += 1
    this.duckOperationId += 1
    this.clearAmbientFade()
    this.clearDuckFade()
    this.stopSfx()
    this.decks.forEach((deck) => {
      deck.removeListeners()
      this.resetDeck(deck)
    })
    this.subscribers.clear()
  }

  private createDeck(): AmbientDeck {
    const audio = this.audioFactory()
    audio.preload = 'auto'
    const deck: AmbientDeck = {
      audio,
      gain: 0,
      track: null,
      removeListeners: () => {},
    }
    const handleEnded = () => this.handleDeckEnded(deck)
    const handleTimeUpdate = () => this.handleDeckTimeUpdate(deck)
    audio.addEventListener('ended', handleEnded)
    audio.addEventListener('timeupdate', handleTimeUpdate)
    deck.removeListeners = () => {
      audio.removeEventListener('ended', handleEnded)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
    }
    return deck
  }

  private notify() {
    const snapshot = this.getSnapshot()
    this.subscribers.forEach((listener) => listener(snapshot))
  }

  private setStatus(status: AudioRuntimeStatus) {
    if (this.status === status) return
    this.status = status
    this.notify()
  }

  private activeDeck() {
    return this.decks[this.activeDeckIndex]
  }

  private getDesiredAmbientTrack() {
    if (!this.sessionActive) return null
    if (
      this.activeLevelUpCue &&
      areRoomsInSameAmbientArea(this.activeLevelUpCue.location, this.currentRoom)
    ) {
      return resolveLevelUpTrack(this.activeLevelUpCue)
    }
    return resolveAmbientTrack(this.currentRoom)
  }

  private requestDesiredAmbient(durationMs: number) {
    this.requestAmbientTrack(this.getDesiredAmbientTrack(), durationMs)
  }

  private requestAmbientTrack(
    track: AmbientTrack | null,
    durationMs: number,
    options: { repeat?: boolean; forceRestart?: boolean } = {}
  ) {
    if (!this.unlocked) {
      this.setStatus('waiting')
      return
    }

    if (!track) {
      this.cancelPendingAmbient()
      this.startSilenceFade(durationMs)
      return
    }

    if (
      this.pendingAmbient &&
      (!this.pendingAmbient.repeat || !options.repeat) &&
      this.pendingAmbient.trackId !== track.id
    ) {
      this.cancelPendingAmbient()
    }

    const activeDeck = this.activeDeck()
    if (!options.repeat && !options.forceRestart && this.activeTrack?.id === track.id) {
      if (activeDeck.gain < 1) {
        this.startDeckGainFade(activeDeck, durationMs, 1)
      } else {
        this.setStatus('playing')
        this.applyVolumes()
      }
      return
    }

    if (
      !options.forceRestart &&
      this.pendingAmbient?.trackId === track.id &&
      this.pendingAmbient.repeat === Boolean(options.repeat)
    ) {
      return
    }

    this.startCrossfade(track, durationMs, Boolean(options.repeat))
  }

  private cancelPendingAmbient(cleanupInactive = true) {
    if (!this.pendingAmbient && this.ambientFadeTimer === null) return
    this.ambientOperationId += 1
    this.clearAmbientFade()
    if (this.pendingAmbient) {
      this.resetDeck(this.decks[this.pendingAmbient.deckIndex])
      this.pendingAmbient = null
    }
    if (cleanupInactive) {
      this.cleanupInactiveDecks()
    }
  }

  private startCrossfade(track: AmbientTrack, durationMs: number, repeat: boolean) {
    this.cancelPendingAmbient()
    const previousDeck = this.activeDeck()
    const nextDeckIndex = this.activeDeckIndex === 0 ? 1 : 0
    const nextDeck = this.decks[nextDeckIndex]
    const operationId = ++this.ambientOperationId

    this.resetDeck(nextDeck)
    nextDeck.track = track
    nextDeck.audio.src = track.src
    nextDeck.audio.preload = 'auto'
    nextDeck.audio.currentTime = 0
    nextDeck.gain = 0
    this.applyVolumes()
    this.pendingAmbient = {
      operationId,
      deckIndex: nextDeckIndex,
      trackId: track.id,
      repeat,
    }
    this.setStatus('waiting')

    void nextDeck.audio
      .play()
      .then(() => {
        if (!this.isPendingAmbientCurrent(operationId, track)) {
          this.resetDeck(nextDeck)
          return
        }
        this.pendingAmbient = null
        this.activeDeckIndex = nextDeckIndex
        this.activeTrack = track
        this.setStatus('playing')
        this.startCrossfadeTimer(operationId, previousDeck, nextDeck, durationMs)
      })
      .catch(() => {
        if (!this.isPendingAmbientCurrent(operationId, track)) {
          this.resetDeck(nextDeck)
          return
        }
        this.pendingAmbient = null
        this.resetDeck(nextDeck)
        if (isLevelUpAmbientTrack(track)) {
          this.activeLevelUpCue = null
          this.requestAmbientTrack(resolveAmbientTrack(this.currentRoom), CROSSFADE_MS)
          return
        }
        this.setStatus('waiting')
      })
  }

  private isPendingAmbientCurrent(operationId: number, track: AmbientTrack) {
    const desiredTrack = this.getDesiredAmbientTrack()
    return (
      this.ambientOperationId === operationId &&
      this.pendingAmbient?.operationId === operationId &&
      desiredTrack?.id === track.id
    )
  }

  private startCrossfadeTimer(
    operationId: number,
    previousDeck: AmbientDeck,
    nextDeck: AmbientDeck,
    durationMs: number
  ) {
    this.clearAmbientFade()
    const previousStartGain = previousDeck.gain
    const steps = this.stepsFor(durationMs)
    let step = 0
    this.ambientFadeTimer = window.setInterval(() => {
      if (this.ambientOperationId !== operationId) {
        this.clearAmbientFade()
        return
      }
      step += 1
      const progress = Math.min(1, step / steps)
      previousDeck.gain = previousStartGain * (1 - progress)
      nextDeck.gain = progress
      this.applyVolumes()
      if (progress >= 1) {
        this.clearAmbientFade()
        this.resetDeck(previousDeck)
      }
    }, this.fadeStepMs)
  }

  private startDeckGainFade(deck: AmbientDeck, durationMs: number, targetGain: number) {
    this.cancelPendingAmbient()
    const operationId = ++this.ambientOperationId
    const startGain = deck.gain
    const steps = this.stepsFor(durationMs)
    let step = 0
    this.setStatus('playing')
    this.ambientFadeTimer = window.setInterval(() => {
      if (this.ambientOperationId !== operationId) {
        this.clearAmbientFade()
        return
      }
      step += 1
      const progress = Math.min(1, step / steps)
      deck.gain = startGain + (targetGain - startGain) * progress
      this.applyVolumes()
      if (progress >= 1) {
        this.clearAmbientFade()
      }
    }, this.fadeStepMs)
  }

  private startSilenceFade(durationMs: number) {
    const activeDeck = this.activeDeck()
    if (!this.activeTrack || activeDeck.gain <= 0) {
      this.resetDeck(activeDeck)
      this.activeTrack = null
      this.setStatus('silent')
      return
    }
    const operationId = ++this.ambientOperationId
    const startGain = activeDeck.gain
    const steps = this.stepsFor(durationMs)
    let step = 0
    this.ambientFadeTimer = window.setInterval(() => {
      if (this.ambientOperationId !== operationId) {
        this.clearAmbientFade()
        return
      }
      step += 1
      const progress = Math.min(1, step / steps)
      activeDeck.gain = startGain * (1 - progress)
      this.applyVolumes()
      if (progress >= 1) {
        this.clearAmbientFade()
        this.resetDeck(activeDeck)
        this.activeTrack = null
        this.setStatus('silent')
      }
    }, this.fadeStepMs)
  }

  private duckAmbientForLevelUp() {
    this.cancelPendingAmbient(false)
    this.clearDuckFade()
    this.duckOperationId += 1
    const operationId = this.duckOperationId
    const decksToDuck = this.decks.filter((deck) => deck.track && deck.gain > 0)
    if (decksToDuck.length === 0) return
    const startGains = decksToDuck.map((deck) => deck.gain)
    const steps = this.stepsFor(LEVEL_UP_DUCK_MS)
    let step = 0
    this.duckFadeTimer = window.setInterval(() => {
      if (this.duckOperationId !== operationId) {
        this.clearDuckFade()
        return
      }
      step += 1
      const progress = Math.min(1, step / steps)
      decksToDuck.forEach((deck, index) => {
        deck.gain = startGains[index] * (1 - progress)
      })
      this.applyVolumes()
      if (progress >= 1) {
        this.clearDuckFade()
        this.cleanupInactiveDecks()
      }
    }, this.fadeStepMs)
  }

  private playSfx(onComplete: () => void) {
    this.stopSfx()
    if (!this.unlocked || this.effectiveSfxVolume() <= 0) return false

    const operationId = ++this.sfxOperationId
    const audio = this.audioFactory()
    let completed = false
    let cleanup = () => {}
    const complete = () => {
      if (completed) return
      completed = true
      cleanup()
      if (this.sfxOperationId === operationId && this.sfxAudio === audio) {
        this.sfxCleanup = null
        this.sfxAudio = null
        onComplete()
      }
    }
    cleanup = () => {
      audio.removeEventListener('ended', complete)
      audio.removeEventListener('error', complete)
    }
    audio.preload = 'auto'
    audio.src = LEVEL_UP_SFX_SRC
    audio.currentTime = 0
    audio.volume = this.effectiveSfxVolume()
    audio.addEventListener('ended', complete)
    audio.addEventListener('error', complete)
    this.sfxCleanup = cleanup
    this.sfxAudio = audio
    void audio.play().catch(complete)
    return true
  }

  private stopSfx() {
    this.sfxOperationId += 1
    const cleanup = this.sfxCleanup
    const audio = this.sfxAudio
    this.sfxCleanup = null
    this.sfxAudio = null
    cleanup?.()
    if (audio) {
      audio.pause()
      audio.currentTime = 0
    }
  }

  private handleDeckEnded(deck: AmbientDeck) {
    if (deck !== this.activeDeck() || !this.activeTrack) return
    if (this.pendingAmbient?.repeat) return
    if (isLevelUpAmbientTrack(this.activeTrack)) {
      this.activeLevelUpCue = null
      this.requestDesiredAmbient(CROSSFADE_MS)
      return
    }
    this.requestAmbientTrack(this.activeTrack, CROSSFADE_MS, { repeat: true })
  }

  private handleDeckTimeUpdate(deck: AmbientDeck) {
    if (
      deck !== this.activeDeck() ||
      !this.activeTrack ||
      isLevelUpAmbientTrack(this.activeTrack) ||
      this.pendingAmbient?.repeat
    ) {
      return
    }
    const audio = deck.audio
    if (
      Number.isFinite(audio.duration) &&
      audio.duration > CROSSFADE_MS / 1000 &&
      audio.duration - audio.currentTime <= CROSSFADE_MS / 1000
    ) {
      this.requestAmbientTrack(this.activeTrack, CROSSFADE_MS, { repeat: true })
    }
  }

  private cleanupInactiveDecks() {
    const activeDeck = this.activeDeck()
    this.decks.forEach((deck) => {
      if (deck !== activeDeck) {
        this.resetDeck(deck)
      }
    })
  }

  private resetDeck(deck: AmbientDeck) {
    deck.audio.pause()
    deck.audio.currentTime = 0
    deck.audio.volume = 0
    deck.gain = 0
    deck.track = null
  }

  private applyVolumes() {
    const ambientVolume = this.effectiveAmbientVolume()
    this.decks.forEach((deck) => {
      deck.audio.volume = ambientVolume * deck.gain
    })
    if (this.sfxAudio) {
      this.sfxAudio.volume = this.effectiveSfxVolume()
    }
  }

  private effectiveAmbientVolume() {
    return this.masterMuted ? 0 : this.masterVolume
  }

  private effectiveSfxVolume() {
    return this.masterMuted ? 0 : this.masterVolume
  }

  private clearAmbientFade() {
    if (this.ambientFadeTimer !== null) {
      window.clearInterval(this.ambientFadeTimer)
      this.ambientFadeTimer = null
    }
  }

  private clearDuckFade() {
    if (this.duckFadeTimer !== null) {
      window.clearInterval(this.duckFadeTimer)
      this.duckFadeTimer = null
    }
  }

  private cancelDuckFade() {
    this.duckOperationId += 1
    this.clearDuckFade()
  }

  private stepsFor(durationMs: number) {
    return Math.max(1, Math.ceil(durationMs / this.fadeStepMs))
  }
}
