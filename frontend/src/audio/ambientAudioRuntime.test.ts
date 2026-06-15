import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AmbientAudioRuntime } from './ambientAudioRuntime'

class MockAudio {
  static instances: MockAudio[] = []
  static rejectNextPlay = false
  static deferNextPlay = false
  static resolveDeferredPlay: (() => void) | null = null
  static rejectDeferredPlay: (() => void) | null = null

  src = ''
  preload = ''
  currentTime = 0
  duration = 120
  volume = 1
  paused = true
  play = vi.fn(() => {
    if (MockAudio.rejectNextPlay) {
      MockAudio.rejectNextPlay = false
      return Promise.reject(new Error('play rejected'))
    }
    if (MockAudio.deferNextPlay) {
      MockAudio.deferNextPlay = false
      return new Promise<void>((resolve, reject) => {
        MockAudio.resolveDeferredPlay = () => {
          this.paused = false
          MockAudio.resolveDeferredPlay = null
          MockAudio.rejectDeferredPlay = null
          resolve()
        }
        MockAudio.rejectDeferredPlay = () => {
          MockAudio.resolveDeferredPlay = null
          MockAudio.rejectDeferredPlay = null
          reject(new Error('play rejected'))
        }
      })
    }
    this.paused = false
    return Promise.resolve()
  })
  pause = vi.fn(() => {
    this.paused = true
  })
  private listeners = new Map<string, Set<() => void>>()

  constructor() {
    MockAudio.instances.push(this)
  }

  addEventListener(type: string, listener: () => void) {
    const listeners = this.listeners.get(type) ?? new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  removeEventListener(type: string, listener: () => void) {
    this.listeners.get(type)?.delete(listener)
  }

  dispatch(type: string) {
    this.listeners.get(type)?.forEach((listener) => listener())
  }
}

const createRuntime = () =>
  new AmbientAudioRuntime({
    audioFactory: () => new MockAudio() as unknown as HTMLAudioElement,
  })

const flushPromises = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

const playableAudios = (needle: string) =>
  MockAudio.instances.filter((audio) => audio.src.includes(needle))

const startRuntimeInRoom = async (room: number) => {
  const runtime = createRuntime()
  runtime.setSessionActive(true)
  runtime.setRoom(room)
  runtime.unlock()
  await flushPromises()
  vi.advanceTimersByTime(1000)
  return runtime
}

describe('AmbientAudioRuntime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockAudio.instances = []
    MockAudio.rejectNextPlay = false
    MockAudio.deferNextPlay = false
    MockAudio.resolveDeferredPlay = null
    MockAudio.rejectDeferredPlay = null
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('cancels a pending different-track play before accepting the current track', async () => {
    const runtime = await startRuntimeInRoom(0)

    const willowAudio = playableAudios('WillowDrift1.mp3')[0]
    expect(willowAudio?.paused).toBe(false)
    expect(willowAudio?.volume).toBeCloseTo(0.3, 2)

    MockAudio.deferNextPlay = true
    runtime.setRoom(169)
    const pendingSpelunking = playableAudios('Spelunking.mp3')[0]
    expect(pendingSpelunking?.play).toHaveBeenCalledTimes(1)
    expect(pendingSpelunking?.paused).toBe(true)

    runtime.setRoom(0)
    MockAudio.resolveDeferredPlay?.()
    await flushPromises()
    vi.advanceTimersByTime(2000)

    expect(willowAudio?.paused).toBe(false)
    expect(willowAudio?.volume).toBeCloseTo(0.3, 2)
    expect(pendingSpelunking?.paused).toBe(true)
  })

  it('cancels a pending silence fade when returning to the same mapped track', async () => {
    const runtime = await startRuntimeInRoom(0)

    const willowAudio = playableAudios('WillowDrift1.mp3')[0]
    runtime.setRoom(303)
    vi.advanceTimersByTime(500)
    expect(willowAudio?.volume).toBeLessThan(0.3)

    runtime.setRoom(0)
    vi.advanceTimersByTime(2000)

    expect(willowAudio?.paused).toBe(false)
    expect(willowAudio?.volume).toBeCloseTo(0.3, 2)
  })

  it('keeps rejected playback retryable without committing the rejected track', async () => {
    const runtime = await startRuntimeInRoom(0)

    MockAudio.rejectNextPlay = true
    runtime.setRoom(189)
    await flushPromises()

    const rejectedGolden = playableAudios('GoldenForay.mp3')[0]
    expect(rejectedGolden?.paused).toBe(true)

    runtime.retry()
    await flushPromises()
    vi.advanceTimersByTime(2000)

    const goldenAttempts = playableAudios('GoldenForay.mp3')
    expect(goldenAttempts.some((audio) => !audio.paused && audio.volume > 0)).toBe(true)
  })

  it('starts only one repeat crossfade for repeated boundary events', async () => {
    await startRuntimeInRoom(0)

    const firstWillow = playableAudios('WillowDrift1.mp3')[0]
    firstWillow.currentTime = 119
    firstWillow.dispatch('timeupdate')
    firstWillow.dispatch('timeupdate')
    firstWillow.dispatch('ended')
    await flushPromises()

    const willowPlayers = playableAudios('WillowDrift1.mp3')
    expect(willowPlayers).toHaveLength(2)
    expect(willowPlayers.reduce((count, audio) => count + audio.play.mock.calls.length, 0)).toBe(2)
  })

  it('revalidates the current room before starting delayed level-up music', async () => {
    const runtime = await startRuntimeInRoom(189)

    runtime.handleLevelUpCue({ sequence: 1, location: 189 })
    const sfxAudio = playableAudios('SFX_LevelUp.mp3')[0]
    expect(sfxAudio?.play).toHaveBeenCalled()

    runtime.setRoom(219)
    await flushPromises()
    expect(playableAudios('ThroughTheGate.mp3')).toHaveLength(0)
    sfxAudio.dispatch('ended')
    await flushPromises()

    expect(playableAudios('GoldenForay_LevelUp.mp3')).toHaveLength(0)
    expect(playableAudios('ThroughTheGate.mp3').some((audio) => audio.play.mock.calls.length > 0)).toBe(
      true
    )
  })

  it('ducks every audible ambient deck when level-up SFX starts during a crossfade', async () => {
    const runtime = await startRuntimeInRoom(0)

    runtime.setRoom(189)
    await flushPromises()
    vi.advanceTimersByTime(500)

    const willowAudio = playableAudios('WillowDrift1.mp3')[0]
    const goldenAudio = playableAudios('GoldenForay.mp3')[0]
    expect(willowAudio?.volume).toBeGreaterThan(0)
    expect(goldenAudio?.volume).toBeGreaterThan(0)

    runtime.handleLevelUpCue({ sequence: 1, location: 189 })
    vi.advanceTimersByTime(350)

    expect(willowAudio?.volume).toBeCloseTo(0, 2)
    expect(goldenAudio?.volume).toBeCloseTo(0, 2)
  })

  it('resumes the room loop when ambient level-up playback fails', async () => {
    const runtime = await startRuntimeInRoom(189)

    runtime.handleLevelUpCue({ sequence: 1, location: 189 })
    const sfxAudio = playableAudios('SFX_LevelUp.mp3')[0]
    MockAudio.rejectNextPlay = true
    sfxAudio.dispatch('ended')
    await flushPromises()

    const rejectedLevelUp = playableAudios('GoldenForay_LevelUp.mp3')[0]
    expect(rejectedLevelUp?.paused).toBe(true)

    vi.advanceTimersByTime(2000)

    const roomLoop = playableAudios('GoldenForay.mp3')[0]
    expect(roomLoop?.paused).toBe(false)
    expect(roomLoop?.volume).toBeCloseTo(0.3, 2)
  })

  it('keeps village level-up cues on the normal village loop', async () => {
    const runtime = await startRuntimeInRoom(5)

    runtime.handleLevelUpCue({ sequence: 1, location: 5 })
    const sfxAudio = playableAudios('SFX_LevelUp.mp3')[0]
    expect(sfxAudio?.play).toHaveBeenCalled()

    sfxAudio.dispatch('ended')
    await flushPromises()
    vi.advanceTimersByTime(2000)

    expect(playableAudios('WillowDrift_LevelUp.mp3')).toHaveLength(0)
    expect(playableAudios('Villager.mp3').some((audio) => !audio.paused)).toBe(true)
  })

  it('does not duck ambient when muted audio skips level-up SFX', async () => {
    const runtime = await startRuntimeInRoom(189)

    runtime.setMasterMuted(true)
    MockAudio.deferNextPlay = true
    runtime.handleLevelUpCue({ sequence: 1, location: 189 })
    expect(playableAudios('SFX_LevelUp.mp3')).toHaveLength(0)

    vi.advanceTimersByTime(350)
    MockAudio.resolveDeferredPlay?.()
    await flushPromises()
    runtime.setMasterMuted(false)
    vi.advanceTimersByTime(1350)

    const levelUpAudio = playableAudios('GoldenForay_LevelUp.mp3')[0]
    expect(levelUpAudio?.paused).toBe(false)
    expect(levelUpAudio?.volume).toBeCloseTo(0.3, 2)
  })

  it('ignores stale level-up SFX completion after logout', async () => {
    const runtime = await startRuntimeInRoom(189)

    MockAudio.deferNextPlay = true
    runtime.handleLevelUpCue({ sequence: 1, location: 189 })
    const sfxAudio = playableAudios('SFX_LevelUp.mp3')[0]
    expect(sfxAudio?.paused).toBe(true)

    runtime.setSessionActive(false)
    MockAudio.rejectDeferredPlay?.()
    await flushPromises()

    expect(playableAudios('GoldenForay_LevelUp.mp3')).toHaveLength(0)
  })

  it('applies master volume changes to ambient decks and SFX during fades', async () => {
    const runtime = await startRuntimeInRoom(189)

    runtime.setRoom(219)
    runtime.handleLevelUpCue({ sequence: 1, location: 219 })
    vi.advanceTimersByTime(100)

    runtime.setMasterVolume(0)
    vi.advanceTimersByTime(2000)

    expect(MockAudio.instances.every((audio) => audio.volume === 0)).toBe(true)
  })
})
