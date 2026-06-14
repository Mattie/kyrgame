import { describe, expect, it } from 'vitest'

import {
  AMBIENT_TRACK_GOLDEN_FORAY,
  AMBIENT_TRACK_GOLDEN_LEVEL_UP,
  AMBIENT_TRACK_THROUGH_GATE,
  AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP,
  AMBIENT_TRACK_WILLOW_DRIFT,
  AMBIENT_TRACK_WILLOW_LEVEL_UP,
  resolveAmbientTrack,
  resolveLevelUpTrack,
} from './ambientMusic'

describe('ambient music track selection', () => {
  it('exports stable IDs for every mapped track', () => {
    expect(AMBIENT_TRACK_WILLOW_DRIFT).toBe('willow-drift')
    expect(AMBIENT_TRACK_GOLDEN_FORAY).toBe('golden-foray')
    expect(AMBIENT_TRACK_THROUGH_GATE).toBe('through-the-gate')
    expect(AMBIENT_TRACK_WILLOW_LEVEL_UP).toBe('willow-drift-level-up')
    expect(AMBIENT_TRACK_GOLDEN_LEVEL_UP).toBe('golden-foray-level-up')
    expect(AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP).toBe('through-the-gate-level-up')
  })

  it('maps dark forest, golden forest, and castle rooms to their ambient tracks', () => {
    expect(resolveAmbientTrack(0)?.id).toBe(AMBIENT_TRACK_WILLOW_DRIFT)
    expect(resolveAmbientTrack(171)?.id).toBe(AMBIENT_TRACK_WILLOW_DRIFT)
    expect(resolveAmbientTrack(189)?.id).toBe(AMBIENT_TRACK_GOLDEN_FORAY)
    expect(resolveAmbientTrack(218)?.id).toBe(AMBIENT_TRACK_GOLDEN_FORAY)
    expect(resolveAmbientTrack(219)?.id).toBe(AMBIENT_TRACK_THROUGH_GATE)
    expect(resolveAmbientTrack(302)?.id).toBe(AMBIENT_TRACK_THROUGH_GATE)
  })

  it('fades to silence for unmapped rooms', () => {
    expect(resolveAmbientTrack(null)).toBeNull()
    expect(resolveAmbientTrack(172)).toBeNull()
    expect(resolveAmbientTrack(188)).toBeNull()
    expect(resolveAmbientTrack(303)).toBeNull()
  })

  it('uses the level-up track for mapped area level-up cues', () => {
    expect(resolveLevelUpTrack({ location: 0 })?.id).toBe(AMBIENT_TRACK_WILLOW_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 171 })?.id).toBe(AMBIENT_TRACK_WILLOW_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 189 })?.id).toBe(AMBIENT_TRACK_GOLDEN_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 218 })?.id).toBe(AMBIENT_TRACK_GOLDEN_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 219 })?.id).toBe(AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 302 })?.id).toBe(AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 172 })).toBeNull()
    expect(resolveLevelUpTrack({ location: null })).toBeNull()
  })
})
