import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AmbientMusicPlayer } from './AmbientMusicPlayer'

const navigatorState = vi.hoisted(() => ({
  value: {
    currentRoom: 0 as number | null,
    latestLevelUpCue: null as
      | {
          sequence: number
          player: string
          previousLevel: number
          level: number
          location: number | null
        }
      | null,
    session: {
      token: 'token',
      playerId: 'hero',
      roomId: 0,
      sessionKind: 'game' as const,
    } as
      | {
          token: string
          playerId: string
          roomId: number
          sessionKind: 'game'
        }
      | null,
  },
}))

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => navigatorState.value,
}))

class MockAudio {
  static instances: MockAudio[] = []
  static rejectNextPlay = false
  static deferNextPlay = false
  static resolveDeferredPlay: (() => void) | null = null
  src = ''
  preload = ''
  currentTime = 0
  duration = 120
  volume = 1
  paused = true
  play = vi.fn(async () => {
    if (MockAudio.rejectNextPlay) {
      MockAudio.rejectNextPlay = false
      throw new Error('play rejected')
    }
    if (MockAudio.deferNextPlay) {
      MockAudio.deferNextPlay = false
      return new Promise<void>((resolve) => {
        MockAudio.resolveDeferredPlay = () => {
          this.paused = false
          MockAudio.resolveDeferredPlay = null
          resolve()
        }
      })
    }
    this.paused = false
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

describe('AmbientMusicPlayer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    navigatorState.value = {
      currentRoom: 0,
      latestLevelUpCue: null,
      session: { token: 'token', playerId: 'hero', roomId: 0, sessionKind: 'game' },
    }
    MockAudio.instances = []
    MockAudio.rejectNextPlay = false
    MockAudio.deferNextPlay = false
    MockAudio.resolveDeferredPlay = null
    vi.stubGlobal('Audio', MockAudio)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('starts after user interaction at the default 30% volume', async () => {
    render(<AmbientMusicPlayer />)

    expect(screen.queryByLabelText(/ambient volume/i)).toBeNull()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('30')

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    const activeAudio = MockAudio.instances.find((audio) => audio.src.includes('WillowDrift1.mp3'))
    expect(activeAudio?.volume).toBeCloseTo(0.3, 2)
  })

  it('restores persisted mute and volume settings', async () => {
    localStorage.setItem('kyrgame.ambient.volume', '0.7')
    localStorage.setItem('kyrgame.ambient.muted', 'true')

    render(<AmbientMusicPlayer />)

    expect(screen.queryByLabelText(/ambient volume/i)).toBeNull()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('70')
    expect(screen.getByRole('button', { name: /unmute ambient music/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: /unmute ambient music/i })).toHaveTextContent(
      '\u{1F507}'
    )
  })

  it('falls back to default volume for invalid persisted settings', async () => {
    localStorage.setItem('kyrgame.ambient.volume', 'loud')

    render(<AmbientMusicPlayer />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('30')
  })

  it('restores default volume when unmuting from zero volume', async () => {
    localStorage.setItem('kyrgame.ambient.volume', '0')

    render(<AmbientMusicPlayer />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })
    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('0')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /unmute ambient music/i }))
      await Promise.resolve()
    })

    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('30')
    expect(screen.getByRole('button', { name: /mute ambient music/i })).toHaveTextContent(
      '\u{1F50A}'
    )
  })

  it('collapses the volume slider after leaving the audio control', async () => {
    render(<AmbientMusicPlayer />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })
    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('30')

    fireEvent.pointerLeave(screen.getByTestId('ambient-music-player'))
    act(() => {
      vi.advanceTimersByTime(2999)
    })
    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('30')

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(screen.queryByLabelText(/ambient volume/i)).toBeNull()
    expect(screen.getByRole('button', { name: /open ambient music controls/i })).toHaveTextContent(
      '\u{1F50A}'
    )
  })

  it('keeps the volume slider expanded while keyboard focus remains inside it', async () => {
    render(<AmbientMusicPlayer />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    const volumeInput = screen.getByLabelText(/ambient volume/i)
    act(() => {
      volumeInput.focus()
      fireEvent.focus(volumeInput)
      vi.advanceTimersByTime(3000)
    })

    expect(screen.getByLabelText(/ambient volume/i)).toHaveValue('30')
  })

  it('crossfades to mapped area tracks and silence for unmapped rooms', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    expect(MockAudio.instances.some((audio) => audio.src.includes('GoldenForay.mp3'))).toBe(true)

    navigatorState.value = { ...navigatorState.value, currentRoom: 219 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    expect(MockAudio.instances.some((audio) => audio.src.includes('ThroughTheGate.mp3'))).toBe(
      true
    )

    navigatorState.value = { ...navigatorState.value, currentRoom: 303 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(2000)
    })

    expect(MockAudio.instances.every((audio) => audio.paused || audio.volume === 0)).toBe(true)
  })

  it('cancels a pending silence fade when returning to the same ambient track', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    const willowAudio = MockAudio.instances.find((audio) => audio.src.includes('WillowDrift1.mp3'))
    expect(willowAudio?.volume).toBeCloseTo(0.3, 2)

    navigatorState.value = { ...navigatorState.value, currentRoom: 172 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(willowAudio?.volume).toBeLessThan(0.3)

    navigatorState.value = { ...navigatorState.value, currentRoom: 0 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(2000)
    })

    expect(willowAudio?.paused).toBe(false)
    expect(willowAudio?.volume).toBeCloseTo(0.3, 2)
  })

  it('uses the current volume setting while a room crossfade is active', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/ambient volume/i), { target: { value: '0' } })
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(2000)
    })

    const goldenAudio = MockAudio.instances.find((audio) => audio.src.includes('GoldenForay.mp3'))
    expect(goldenAudio?.volume).toBe(0)
    expect(MockAudio.instances.every((audio) => audio.volume === 0)).toBe(true)
  })

  it('retries the same room track after a rejected playback attempt', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    MockAudio.rejectNextPlay = true
    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
      await Promise.resolve()
    })

    const goldenAudio = MockAudio.instances.find((audio) => audio.src.includes('GoldenForay.mp3'))
    expect(goldenAudio?.play).toHaveBeenCalledTimes(1)
    expect(goldenAudio?.paused).toBe(true)

    MockAudio.rejectNextPlay = true
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /mute ambient music/i }))
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(goldenAudio?.play).toHaveBeenCalledTimes(2)
    expect(goldenAudio?.paused).toBe(true)

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/ambient volume/i), { target: { value: '40' } })
      await Promise.resolve()
    })

    expect(goldenAudio?.play).toHaveBeenCalledTimes(3)
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(goldenAudio?.volume).toBeCloseTo(0.4, 2)
  })

  it('self-crossfades at repeat boundaries', async () => {
    render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    const firstWillow = MockAudio.instances.find((audio) => audio.src.includes('WillowDrift1.mp3'))
    expect(firstWillow?.play).toHaveBeenCalled()

    await act(async () => {
      if (firstWillow) {
        firstWillow.currentTime = 119
        firstWillow.dispatch('timeupdate')
      }
      await Promise.resolve()
    })

    const willowPlayers = MockAudio.instances.filter((audio) =>
      audio.src.includes('WillowDrift1.mp3')
    )
    expect(willowPlayers).toHaveLength(2)
    expect(willowPlayers.every((audio) => audio.play.mock.calls.length > 0)).toBe(true)
  })

  it('fades to silence when the active session logs out', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    navigatorState.value = { ...navigatorState.value, currentRoom: null, session: null }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(2000)
    })

    expect(MockAudio.instances.every((audio) => audio.paused || audio.volume === 0)).toBe(true)
  })

  it('clears active level-up ambient music when the active session logs out', async () => {
    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    navigatorState.value = {
      ...navigatorState.value,
      latestLevelUpCue: {
        sequence: 1,
        player: 'hero',
        previousLevel: 4,
        level: 5,
        location: 189,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const sfxAudio = MockAudio.instances.find((audio) => audio.src.includes('SFX_LevelUp.mp3'))
    await act(async () => {
      sfxAudio?.dispatch('ended')
      await Promise.resolve()
    })

    const levelUpAudio = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay_LevelUp.mp3')
    )
    expect(levelUpAudio?.play).toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(1350)
    })
    expect(levelUpAudio?.volume).toBeCloseTo(0.3, 2)

    navigatorState.value = { ...navigatorState.value, currentRoom: null, session: null }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(2000)
    })

    expect(levelUpAudio?.paused || levelUpAudio?.volume === 0).toBe(true)
  })

  it('plays the dark-forest level-up cue once before returning to the room track', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    navigatorState.value = {
      ...navigatorState.value,
      latestLevelUpCue: {
        sequence: 1,
        player: 'hero',
        previousLevel: 1,
        level: 2,
        location: 0,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const levelUpBeforeSfxEnds = MockAudio.instances.find((audio) =>
      audio.src.includes('WillowDrift_LevelUp.mp3')
    )
    expect(levelUpBeforeSfxEnds).toBeUndefined()

    const levelUpSfx = MockAudio.instances.find((audio) => audio.src.includes('SFX_LevelUp.mp3'))
    expect(levelUpSfx?.play).toHaveBeenCalled()

    await act(async () => {
      levelUpSfx?.dispatch('ended')
      await Promise.resolve()
    })

    const levelUpAudio = MockAudio.instances.find((audio) =>
      audio.src.includes('WillowDrift_LevelUp.mp3')
    )
    expect(levelUpAudio?.play).toHaveBeenCalled()

    await act(async () => {
      levelUpAudio?.dispatch('ended')
      await Promise.resolve()
    })

    expect(MockAudio.instances.some((audio) => audio.src.includes('WillowDrift1.mp3'))).toBe(true)
  })

  it('plays mapped area level-up cues once before returning to the room track', async () => {
    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    navigatorState.value = {
      ...navigatorState.value,
      latestLevelUpCue: {
        sequence: 1,
        player: 'hero',
        previousLevel: 4,
        level: 5,
        location: 189,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const goldenBeforeSfxEnds = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay_LevelUp.mp3')
    )
    expect(goldenBeforeSfxEnds).toBeUndefined()

    const firstSfx = MockAudio.instances.find((audio) => audio.src.includes('SFX_LevelUp.mp3'))
    expect(firstSfx?.play).toHaveBeenCalled()

    await act(async () => {
      firstSfx?.dispatch('ended')
      await Promise.resolve()
    })

    const goldenLevelUp = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay_LevelUp.mp3')
    )
    expect(goldenLevelUp?.play).toHaveBeenCalled()

    await act(async () => {
      goldenLevelUp?.dispatch('ended')
      await Promise.resolve()
    })

    expect(MockAudio.instances.some((audio) => audio.src.includes('GoldenForay.mp3'))).toBe(true)

    navigatorState.value = {
      ...navigatorState.value,
      currentRoom: 219,
      latestLevelUpCue: {
        sequence: 2,
        player: 'hero',
        previousLevel: 5,
        level: 6,
        location: 219,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const secondSfxCandidates = MockAudio.instances.filter((audio) =>
      audio.src.includes('SFX_LevelUp.mp3')
    )
    const secondSfx = secondSfxCandidates[secondSfxCandidates.length - 1]
    expect(secondSfx?.play).toHaveBeenCalled()

    await act(async () => {
      secondSfx?.dispatch('ended')
      await Promise.resolve()
    })

    const castleLevelUp = MockAudio.instances.find((audio) =>
      audio.src.includes('ThroughTheGate_LevelUp.mp3')
    )
    expect(castleLevelUp?.play).toHaveBeenCalled()

    await act(async () => {
      castleLevelUp?.dispatch('ended')
      await Promise.resolve()
    })

    expect(MockAudio.instances.some((audio) => audio.src.includes('ThroughTheGate.mp3'))).toBe(
      true
    )
  })

  it('ducks background music during the level-up SFX before starting the ambient cue', async () => {
    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    const backgroundAudio = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay.mp3')
    )
    expect(backgroundAudio?.volume).toBeCloseTo(0.3, 2)

    navigatorState.value = {
      ...navigatorState.value,
      latestLevelUpCue: {
        sequence: 1,
        player: 'hero',
        previousLevel: 4,
        level: 5,
        location: 189,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const sfxAudio = MockAudio.instances.find((audio) => audio.src.includes('SFX_LevelUp.mp3'))
    const levelUpBeforeSfxEnds = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay_LevelUp.mp3')
    )
    expect(sfxAudio?.play).toHaveBeenCalled()
    expect(sfxAudio?.volume).toBeCloseTo(0.3, 2)
    expect(levelUpBeforeSfxEnds).toBeUndefined()

    act(() => {
      vi.advanceTimersByTime(350)
    })
    expect(backgroundAudio?.volume).toBeCloseTo(0, 2)

    await act(async () => {
      sfxAudio?.dispatch('ended')
      await Promise.resolve()
    })

    const levelUpAudio = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay_LevelUp.mp3')
    )
    expect(levelUpAudio?.play).toHaveBeenCalled()
    expect(levelUpAudio?.volume).toBe(0)

    act(() => {
      vi.advanceTimersByTime(1350)
    })
    expect(levelUpAudio?.volume).toBeCloseTo(0.3, 2)
  })

  it('invalidates pending room transitions before ducking level-up audio', async () => {
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    MockAudio.deferNextPlay = true
    navigatorState.value = { ...navigatorState.value, currentRoom: 189 }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const pendingGolden = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay.mp3')
    )
    expect(pendingGolden?.play).toHaveBeenCalled()
    expect(pendingGolden?.paused).toBe(true)

    navigatorState.value = {
      ...navigatorState.value,
      latestLevelUpCue: {
        sequence: 1,
        player: 'hero',
        previousLevel: 4,
        level: 5,
        location: 189,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const sfxAudio = MockAudio.instances.find((audio) => audio.src.includes('SFX_LevelUp.mp3'))
    expect(sfxAudio?.play).toHaveBeenCalled()

    await act(async () => {
      MockAudio.resolveDeferredPlay?.()
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(350)
    })

    await act(async () => {
      sfxAudio?.dispatch('ended')
      await Promise.resolve()
    })

    const levelUpAudio = MockAudio.instances.find((audio) =>
      audio.src.includes('GoldenForay_LevelUp.mp3')
    )
    expect(levelUpAudio?.play).toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(1350)
    })

    expect(levelUpAudio?.volume).toBeCloseTo(0.3, 2)
  })

  it('keeps level-up SFX silent while muted', async () => {
    localStorage.setItem('kyrgame.ambient.muted', 'true')
    navigatorState.value = { ...navigatorState.value, currentRoom: 219 }
    const { rerender } = render(<AmbientMusicPlayer />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /open ambient music controls/i }))
      await Promise.resolve()
    })

    navigatorState.value = {
      ...navigatorState.value,
      latestLevelUpCue: {
        sequence: 1,
        player: 'hero',
        previousLevel: 5,
        level: 6,
        location: 219,
      },
    }
    await act(async () => {
      rerender(<AmbientMusicPlayer />)
      await Promise.resolve()
    })

    const audibleSfx = MockAudio.instances.some(
      (audio) =>
        audio.src.includes('SFX_LevelUp.mp3') && audio.play.mock.calls.length > 0 && audio.volume > 0
    )
    expect(audibleSfx).toBe(false)
  })
})
