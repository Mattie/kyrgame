import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'

import {
  defaultFireBorderAccentStyle,
  defaultFireBorderEffectPreset,
  defaultFireBorderInverted,
  defaultFireBorderPalette,
  defaultFireBorderRenderStyle,
  defaultFireBorderTuning,
  GamePanelFireBorder,
  fireBorderEffectPresets,
  fireBorderAccentStyles,
  fireBorderPalettePresets,
  fireBorderRenderStyles,
  getBurningPaperShade,
  getFireBorderFrameIntervalMs,
  getPaperEmberParticleCount,
  getThresholdMaskDimensions,
  getIntegratedFlameLickShape,
  getThresholdBurnBand,
} from './CrtFireBorder'

const mockContext = {
  clearRect: vi.fn(),
  setTransform: vi.fn(),
}
const originalMatchMedia = window.matchMedia

class MockResizeObserver {
  observe = vi.fn()
  disconnect = vi.fn()

  constructor(callback: ResizeObserverCallback) {
    void callback
  }
}

describe('CrtFireBorder', () => {
  beforeEach(() => {
    mockContext.clearRect.mockReset()
    mockContext.setTransform.mockReset()

    vi.stubGlobal('ResizeObserver', MockResizeObserver)
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(mockContext as never)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      bottom: 50,
      height: 50,
      left: 0,
      right: 50,
      top: 0,
      width: 50,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect)
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn((query: string) => ({
        addEventListener: vi.fn(),
        addListener: vi.fn(),
        dispatchEvent: vi.fn(),
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        onchange: null,
        removeEventListener: vi.fn(),
        removeListener: vi.fn(),
      })),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: originalMatchMedia,
    })
  })

  it('uses the selected soft burn tuning defaults', () => {
    expect(defaultFireBorderTuning).toEqual({
      charDepth: 8,
      detail: 0.64,
      driftSpeed: 0.06,
      edgeAmplitude: 7,
      edgeFrequency: 0.012,
      embers: 1.45,
      flickerAmount: 4.5,
      flickerSpeed: 1,
      glowBleed: 3,
      glowRadius: 2,
      outerGlow: 0.14,
      pulseDepth: 0.1,
      pulseSpeed: 0.7,
      softness: 1.2,
    })
  })

  it('uses the tuned burning paper preset as the default effect', () => {
    expect(defaultFireBorderRenderStyle).toBe('paperMask')
    expect(defaultFireBorderInverted).toBe(false)
    expect(defaultFireBorderEffectPreset).toMatchObject({
      id: 'burningPaperTuned',
      inverted: false,
      label: 'Burning paper tuned',
      renderStyle: 'paperMask',
      tuning: defaultFireBorderTuning,
    })
    expect(fireBorderEffectPresets.map((preset) => preset.id)).toEqual([
      'burningPaperTuned',
      'calmSmolder',
      'wildGlow',
    ])
  })

  it('uses the v2 My Palette colors for the burning paper variant', () => {
    expect(defaultFireBorderPalette).toEqual({
      char: '#743502',
      deep: '#e48686',
      emberBright: '#d294a9',
      emberDim: '#2a1dcc',
      flame: '#dfb801',
      lip: '#e3e2de',
      paper: '#010101',
      void: '#160f09',
    })
  })

  it('exposes the requested palette presets for tuning', () => {
    expect(fireBorderPalettePresets.map((preset) => preset.id)).toEqual([
      'myPalette',
      'violetGreen',
      'violetRed',
      'blueLip',
    ])
    expect(fireBorderPalettePresets[1].palette).toEqual({
      char: '#67225b',
      deep: '#16ac34',
      emberBright: '#e4becb',
      emberDim: '#2a1dcc',
      flame: '#edb407',
      lip: '#f7f7f7',
      paper: '#000000',
      void: '#050505',
    })
  })

  it('defaults to flame licks while keeping the previous curl style selectable', () => {
    expect(defaultFireBorderAccentStyle).toBe('flameLicks')
    expect(fireBorderAccentStyles).toEqual(['curls', 'flameLicks'])
  })

  it('keeps every fire border renderer selectable', () => {
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
    expect(getBurningPaperShade(0, { charDepth: 18, glowOut: 5 })).toMatchObject({
      blue: 222,
      green: 226,
      red: 227,
      zone: 'lip',
    })
    expect(getBurningPaperShade(-1.5, { charDepth: 18, glowOut: 5 })).toMatchObject({
      blue: 1,
      green: 184,
      red: 223,
      zone: 'flame',
    })
    expect(getBurningPaperShade(-42, { charDepth: 18, glowOut: 5 })).toMatchObject({
      blue: 1,
      green: 1,
      red: 1,
      zone: 'paper',
    })
  })

  it('sizes the threshold mask from the detail setting for smoother paper edges', () => {
    expect(getThresholdMaskDimensions(600, 400, 0.66)).toEqual({
      maskHeight: 264,
      maskWidth: 396,
    })
    expect(getThresholdMaskDimensions(600, 400, 0.3)).toEqual({
      maskHeight: 120,
      maskWidth: 180,
    })
  })

  it('derives visible floating paper embers from the ember tuning amount', () => {
    expect(getPaperEmberParticleCount({ ...defaultFireBorderTuning, embers: 0 })).toBe(0)
    expect(getPaperEmberParticleCount(defaultFireBorderTuning)).toBeGreaterThan(0)
    expect(getPaperEmberParticleCount({ ...defaultFireBorderTuning, embers: 2 })).toBe(220)
  })

  it('anchors flame licks into neighboring edge points while fading over time', () => {
    const previous = { x: 6, y: 10, nx: 0, ny: -1, seed: 11 }
    const point = { x: 10, y: 10, nx: 0, ny: -1, seed: 17 }
    const next = { x: 14, y: 10, nx: 0, ny: -1, seed: 23 }
    const tuning = { ...defaultFireBorderTuning, embers: 1, pulseSpeed: 3.2 }
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

  it('redraws reduced-motion fire borders when tuning changes', () => {
    const { rerender } = render(<GamePanelFireBorder />)

    expect(mockContext.clearRect).toHaveBeenCalledTimes(1)

    rerender(
      <GamePanelFireBorder
        tuning={{ ...defaultFireBorderTuning, embers: defaultFireBorderTuning.embers + 0.1 }}
      />
    )

    expect(mockContext.clearRect).toHaveBeenCalledTimes(2)
  })
})
