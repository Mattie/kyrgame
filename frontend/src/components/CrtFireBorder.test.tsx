import { describe, expect, it } from 'vitest'

import {
  defaultFireBorderAccentStyle,
  defaultFireBorderRenderStyle,
  defaultFireBorderTuning,
  fireBorderAccentStyles,
  fireBorderRenderStyles,
  getBurningPaperShade,
  getFireBorderFrameIntervalMs,
  getIntegratedFlameLickShape,
  getThresholdBurnBand,
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

  it('keeps the current path renderer as default while exposing the threshold mask variant', () => {
    expect(defaultFireBorderRenderStyle).toBe('path')
    expect(fireBorderRenderStyles).toEqual(['path', 'thresholdMask', 'paperMask'])
  })

  it('classifies threshold burn bands around the animated edge', () => {
    expect(getThresholdBurnBand(0.2, 0.35).zone).toBe('transparent')
    expect(getThresholdBurnBand(0.36, 0.35).zone).toBe('glow')
    expect(getThresholdBurnBand(0.42, 0.35).zone).toBe('char')
    expect(getThresholdBurnBand(0.6, 0.35).zone).toBe('fill')
  })

  it('shades the burning paper mask from void to paper through a hot lip', () => {
    expect(getBurningPaperShade(7, { charDepth: 18, glowOut: 5 }).zone).toBe('transparent')
    expect(getBurningPaperShade(0, { charDepth: 18, glowOut: 5 }).zone).toBe('lip')
    expect(getBurningPaperShade(-5, { charDepth: 18, glowOut: 5 }).zone).toBe('flame')
    expect(getBurningPaperShade(-42, { charDepth: 18, glowOut: 5 }).zone).toBe('paper')
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
