import { describe, expect, it } from 'vitest'

import {
  defaultFireBorderAccentStyle,
  defaultFireBorderTuning,
  fireBorderAccentStyles,
  getFireBorderFrameIntervalMs,
  getIntegratedFlameLickShape,
} from './CrtFireBorder'

describe('CrtFireBorder', () => {
  it('uses the selected soft burn tuning defaults', () => {
    expect(defaultFireBorderTuning).toEqual({
      pulseSpeed: 1.1,
      frequency: 0.6,
      amplitude: 0.75,
      accents: 0.65,
    })
  })

  it('defaults to flame licks while keeping the previous curl style selectable', () => {
    expect(defaultFireBorderAccentStyle).toBe('flameLicks')
    expect(fireBorderAccentStyles).toEqual(['curls', 'flameLicks'])
  })

  it('anchors flame licks into neighboring edge points while fading over time', () => {
    const previous = { x: 6, y: 10, nx: 0, ny: -1, seed: 11 }
    const point = { x: 10, y: 10, nx: 0, ny: -1, seed: 17 }
    const next = { x: 14, y: 10, nx: 0, ny: -1, seed: 23 }
    const tuning = { ...defaultFireBorderTuning, accents: 1 }
    const first = getIntegratedFlameLickShape(previous, point, next, 0, false, tuning)
    const later = getIntegratedFlameLickShape(previous, point, next, 900, false, tuning)

    expect(first.baseStart).toEqual({ x: 8, y: 10 })
    expect(first.baseEnd).toEqual({ x: 12, y: 10 })
    expect(first.tip.y).toBeLessThan(point.y)
    expect(first.opacity).not.toBeCloseTo(later.opacity, 2)
  })

  it('keeps desktop animation unthrottled while reducing mobile canvas cadence', () => {
    expect(getFireBorderFrameIntervalMs({ coarsePointer: false, viewportWidth: 1024 })).toBe(0)
    expect(Math.round(getFireBorderFrameIntervalMs({ coarsePointer: true, viewportWidth: 390 }))).toBe(
      33
    )
    expect(
      Math.round(getFireBorderFrameIntervalMs({ coarsePointer: false, viewportWidth: 640 }))
    ).toBe(33)
  })
})
