import { describe, expect, it } from 'vitest'

import {
  AMBIENT_TRACK_GOLDEN_FORAY,
  AMBIENT_TRACK_GOLDEN_LEVEL_UP,
  AMBIENT_TRACK_SPELUNKING,
  AMBIENT_TRACK_SPELUNKING_LEVEL_UP,
  AMBIENT_TRACK_THROUGH_GATE,
  AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP,
  AMBIENT_TRACK_VILLAGER,
  AMBIENT_TRACK_WILLOW_DRIFT,
  AMBIENT_TRACK_WILLOW_LEVEL_UP,
  resolveAmbientTrack,
  resolveLevelUpTrack,
} from './ambientMusic'

describe('ambient music track selection', () => {
  it('exports stable IDs for every mapped track', () => {
    expect(AMBIENT_TRACK_WILLOW_DRIFT).toBe('willow-drift')
    expect(AMBIENT_TRACK_SPELUNKING).toBe('spelunking')
    expect(AMBIENT_TRACK_GOLDEN_FORAY).toBe('golden-foray')
    expect(AMBIENT_TRACK_THROUGH_GATE).toBe('through-the-gate')
    expect(AMBIENT_TRACK_VILLAGER).toBe('villager')
    expect(AMBIENT_TRACK_WILLOW_LEVEL_UP).toBe('willow-drift-level-up')
    expect(AMBIENT_TRACK_SPELUNKING_LEVEL_UP).toBe('spelunking-level-up')
    expect(AMBIENT_TRACK_GOLDEN_LEVEL_UP).toBe('golden-foray-level-up')
    expect(AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP).toBe('through-the-gate-level-up')
  })

  it('maps village, dark forest, spelunking, golden forest, and castle rooms to their ambient tracks', () => {
    expect(resolveAmbientTrack(0)?.id).toBe(AMBIENT_TRACK_WILLOW_DRIFT)
    expect(resolveAmbientTrack(4)?.id).toBe(AMBIENT_TRACK_WILLOW_DRIFT)
    expect(resolveAmbientTrack(5)?.id).toBe(AMBIENT_TRACK_VILLAGER)
    expect(resolveAmbientTrack(11)?.id).toBe(AMBIENT_TRACK_VILLAGER)
    expect(resolveAmbientTrack(12)?.id).toBe(AMBIENT_TRACK_WILLOW_DRIFT)
    expect(resolveAmbientTrack(168)?.id).toBe(AMBIENT_TRACK_WILLOW_DRIFT)
    expect(resolveAmbientTrack(169)?.id).toBe(AMBIENT_TRACK_SPELUNKING)
    expect(resolveAmbientTrack(188)?.id).toBe(AMBIENT_TRACK_SPELUNKING)
    expect(resolveAmbientTrack(189)?.id).toBe(AMBIENT_TRACK_GOLDEN_FORAY)
    expect(resolveAmbientTrack(218)?.id).toBe(AMBIENT_TRACK_GOLDEN_FORAY)
    expect(resolveAmbientTrack(219)?.id).toBe(AMBIENT_TRACK_THROUGH_GATE)
    expect(resolveAmbientTrack(302)?.id).toBe(AMBIENT_TRACK_THROUGH_GATE)
  })

  it('fades to silence for unmapped rooms', () => {
    expect(resolveAmbientTrack(null)).toBeNull()
    expect(resolveAmbientTrack(-1)).toBeNull()
    expect(resolveAmbientTrack(303)).toBeNull()
  })

  it('uses the level-up track for mapped area level-up cues', () => {
    expect(resolveLevelUpTrack({ location: 0 })?.id).toBe(AMBIENT_TRACK_WILLOW_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 4 })?.id).toBe(AMBIENT_TRACK_WILLOW_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 5 })).toBeNull()
    expect(resolveLevelUpTrack({ location: 11 })).toBeNull()
    expect(resolveLevelUpTrack({ location: 12 })?.id).toBe(AMBIENT_TRACK_WILLOW_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 168 })?.id).toBe(AMBIENT_TRACK_WILLOW_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 169 })?.id).toBe(AMBIENT_TRACK_SPELUNKING_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 188 })?.id).toBe(AMBIENT_TRACK_SPELUNKING_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 189 })?.id).toBe(AMBIENT_TRACK_GOLDEN_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 218 })?.id).toBe(AMBIENT_TRACK_GOLDEN_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 219 })?.id).toBe(AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 302 })?.id).toBe(AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP)
    expect(resolveLevelUpTrack({ location: 303 })).toBeNull()
    expect(resolveLevelUpTrack({ location: null })).toBeNull()
  })
})
