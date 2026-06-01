import { useEffect, useRef } from 'react'

export type EdgePoint = {
  x: number
  y: number
  nx: number
  ny: number
  seed: number
}

export type FireBorderTuning = {
  charDepth: number
  detail: number
  driftSpeed: number
  edgeAmplitude: number
  edgeFrequency: number
  embers: number
  flickerAmount: number
  flickerSpeed: number
  glowBleed: number
  glowRadius: number
  outerGlow: number
  pulseDepth: number
  pulseSpeed: number
  softness: number
}

export const fireBorderAccentStyles = ['curls', 'flameLicks'] as const
export type FireBorderAccentStyle = (typeof fireBorderAccentStyles)[number]

export const fireBorderRenderStyles = ['path', 'thresholdMask', 'paperMask'] as const
export type FireBorderRenderStyle = (typeof fireBorderRenderStyles)[number]

export const defaultFireBorderTuning: FireBorderTuning = {
  charDepth: 6,
  detail: 0.66,
  driftSpeed: 1.8,
  edgeAmplitude: 31,
  edgeFrequency: 0.02,
  embers: 0.5,
  flickerAmount: 3.5,
  flickerSpeed: 3,
  glowBleed: 7.5,
  glowRadius: 7,
  outerGlow: 0.14,
  pulseDepth: 0.2,
  pulseSpeed: 3.2,
  softness: 2.6,
}

export const defaultFireBorderAccentStyle: FireBorderAccentStyle = 'flameLicks'
export const defaultFireBorderRenderStyle: FireBorderRenderStyle = 'path'

const TAU = Math.PI * 2
const MOBILE_VIEWPORT_WIDTH = 720
const MOBILE_FRAME_INTERVAL_MS = 1000 / 30
const FRAME_INTERVAL_TOLERANCE_MS = 2

export const getFireBorderFrameIntervalMs = ({
  coarsePointer,
  viewportWidth,
}: {
  coarsePointer: boolean
  viewportWidth: number
}) => (coarsePointer || viewportWidth <= MOBILE_VIEWPORT_WIDTH ? MOBILE_FRAME_INTERVAL_MS : 0)

const fract = (value: number) => value - Math.floor(value)

const random01 = (seed: number) => fract(Math.sin(seed * 12.9898) * 43758.5453)

const clamp01 = (value: number) => Math.min(1, Math.max(0, value))

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

const lerp = (start: number, end: number, amount: number) => start + (end - start) * amount

const smoothstep = (value: number) => value * value * (3 - 2 * value)

const getPathFrequency = (tuning: FireBorderTuning) =>
  clamp((tuning.edgeFrequency / 0.02) * 0.6, 0.25, 2.75)

const getPathAmplitude = (tuning: FireBorderTuning) =>
  clamp((tuning.edgeAmplitude / 31) * 0.75, 0, 2.5)

const getPathAccentAmount = (tuning: FireBorderTuning) => clamp(tuning.embers * 1.3, 0, 2.5)

const getPathPulseSpeed = (tuning: FireBorderTuning) =>
  clamp((tuning.pulseSpeed / 3.2) * 1.1, 0, 3)

export type ThresholdBurnZone = 'transparent' | 'glow' | 'char' | 'fill'

export type ThresholdBurnBand = {
  alpha: number
  blue: number
  green: number
  red: number
  zone: ThresholdBurnZone
}

const GLOW_BAND_WIDTH = 0.035
const CHAR_BAND_WIDTH = 0.13

export const getThresholdBurnBand = (
  noiseValue: number,
  threshold: number
): ThresholdBurnBand => {
  if (noiseValue < threshold) {
    return { alpha: 0, blue: 0, green: 0, red: 0, zone: 'transparent' }
  }
  if (noiseValue < threshold + GLOW_BAND_WIDTH) {
    return { alpha: 230, blue: 118, green: 224, red: 255, zone: 'glow' }
  }
  if (noiseValue < threshold + CHAR_BAND_WIDTH) {
    return { alpha: 235, blue: 10, green: 31, red: 64, zone: 'char' }
  }
  return { alpha: 245, blue: 24, green: 16, red: 8, zone: 'fill' }
}

export type BurningPaperZone = 'transparent' | 'lip' | 'flame' | 'char' | 'paper'

export type BurningPaperShade = {
  alpha: number
  blue: number
  green: number
  red: number
  zone: BurningPaperZone
}

type BurningPaperShadeConfig = {
  charDepth: number
  glowOut: number
}

const PAPER_BASE_COLOR = [216, 195, 154] as const
const HOT_LIP_DEPTH = 1.5

export const getBurningPaperShade = (
  edgeValue: number,
  { charDepth, glowOut }: BurningPaperShadeConfig
): BurningPaperShade => {
  if (edgeValue > glowOut) {
    return { alpha: 0, blue: 0, green: 0, red: 0, zone: 'transparent' }
  }

  if (edgeValue > -HOT_LIP_DEPTH) {
    const outwardFade = Math.max(0, 1 - Math.max(edgeValue, 0) / glowOut)
    return {
      alpha: Math.round(214 * outwardFade * outwardFade),
      blue: 205,
      green: 245,
      red: 255,
      zone: 'lip',
    }
  }

  const depth = -edgeValue
  if (depth < charDepth) {
    const gradient = clamp01((depth - HOT_LIP_DEPTH) / (charDepth - HOT_LIP_DEPTH))
    if (gradient < 0.45) {
      const amount = gradient / 0.45
      return {
        alpha: 184,
        blue: Math.round(lerp(116, 36, amount)),
        green: Math.round(lerp(224, 156, amount)),
        red: 255,
        zone: 'flame',
      }
    }

    const amount = (gradient - 0.45) / 0.55
    return {
      alpha: 216,
      blue: Math.round(lerp(32, 18, amount)),
      green: Math.round(lerp(92, 34, amount)),
      red: Math.round(lerp(174, 70, amount)),
      zone: 'char',
    }
  }

  const scorch = Math.max(0, 1 - (depth - charDepth) / 18)
  return {
    alpha: 226,
    blue: Math.round(lerp(PAPER_BASE_COLOR[2], 24, scorch)),
    green: Math.round(lerp(PAPER_BASE_COLOR[1], 36, scorch)),
    red: Math.round(lerp(PAPER_BASE_COLOR[0], 66, scorch)),
    zone: 'paper',
  }
}

type Point2D = {
  x: number
  y: number
}

type IntegratedFlameLickShape = {
  baseEnd: Point2D
  baseStart: Point2D
  chance: number
  leftShoulder: Point2D
  opacity: number
  rightShoulder: Point2D
  tip: Point2D
  width: number
}

const midpoint = (first: Point2D, second: Point2D): Point2D => ({
  x: (first.x + second.x) / 2,
  y: (first.y + second.y) / 2,
})

const edgeWave = (
  seed: number,
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
) => {
  const t = staticMode ? 0 : time * getPathPulseSpeed(tuning)
  const frequency = getPathFrequency(tuning)
  const broad = Math.sin(seed * 0.071 * frequency + t * 0.0014)
  const lick = Math.sin(seed * 0.183 * frequency - t * 0.0021)
  const spark = Math.sin(seed * 0.713 * frequency + t * 0.0037)
  return (broad + lick * 0.58 + spark * 0.24) / 1.82
}

const addPoint = (
  points: EdgePoint[],
  x: number,
  y: number,
  nx: number,
  ny: number,
  time: number,
  staticMode: boolean,
  strength: number,
  tuning: FireBorderTuning
) => {
  const seed = x * 0.73 + y * 1.29 + points.length * 19.17
  const amplitude = getPathAmplitude(tuning)
  const accents = getPathAccentAmount(tuning)
  const tunedStrength = strength * amplitude
  const deckle = (random01(seed) - 0.5) * tunedStrength * 0.72
  const shimmer = edgeWave(seed, time, staticMode, tuning) * tunedStrength
  const tangent =
    edgeWave(seed + 41, time * 0.7, staticMode, tuning) * tunedStrength * 0.18 * accents
  points.push({
    x: x + nx * (deckle + shimmer) + -ny * tangent,
    y: y + ny * (deckle + shimmer) + nx * tangent,
    nx,
    ny,
    seed,
  })
}

const buildEdgePath = (
  width: number,
  height: number,
  inset: number,
  radius: number,
  time: number,
  staticMode: boolean,
  strength: number,
  tuning: FireBorderTuning
) => {
  const points: EdgePoint[] = []
  const left = inset
  const top = inset
  const right = width - inset
  const bottom = height - inset
  const frequency = getPathFrequency(tuning)
  const step = Math.max(4, 12 - frequency * 4)
  const arcStep = Math.PI / Math.max(18, 18 + frequency * 13)
  const r = Math.min(radius, (right - left) / 2, (bottom - top) / 2)

  for (let x = left + r; x <= right - r; x += step) {
    addPoint(points, x, top, 0, -1, time, staticMode, strength, tuning)
  }
  for (let angle = -Math.PI / 2; angle <= 0; angle += arcStep) {
    addPoint(
      points,
      right - r + Math.cos(angle) * r,
      top + r + Math.sin(angle) * r,
      Math.cos(angle),
      Math.sin(angle),
      time,
      staticMode,
      strength,
      tuning
    )
  }
  for (let y = top + r; y <= bottom - r; y += step) {
    addPoint(points, right, y, 1, 0, time, staticMode, strength, tuning)
  }
  for (let angle = 0; angle <= Math.PI / 2; angle += arcStep) {
    addPoint(
      points,
      right - r + Math.cos(angle) * r,
      bottom - r + Math.sin(angle) * r,
      Math.cos(angle),
      Math.sin(angle),
      time,
      staticMode,
      strength,
      tuning
    )
  }
  for (let x = right - r; x >= left + r; x -= step) {
    addPoint(points, x, bottom, 0, 1, time, staticMode, strength, tuning)
  }
  for (let angle = Math.PI / 2; angle <= Math.PI; angle += arcStep) {
    addPoint(
      points,
      left + r + Math.cos(angle) * r,
      bottom - r + Math.sin(angle) * r,
      Math.cos(angle),
      Math.sin(angle),
      time,
      staticMode,
      strength,
      tuning
    )
  }
  for (let y = bottom - r; y >= top + r; y -= step) {
    addPoint(points, left, y, -1, 0, time, staticMode, strength, tuning)
  }
  for (let angle = Math.PI; angle <= Math.PI * 1.5; angle += arcStep) {
    addPoint(
      points,
      left + r + Math.cos(angle) * r,
      top + r + Math.sin(angle) * r,
      Math.cos(angle),
      Math.sin(angle),
      time,
      staticMode,
      strength,
      tuning
    )
  }

  return points
}

const strokeEdge = (
  context: CanvasRenderingContext2D,
  points: EdgePoint[],
  color: string,
  lineWidth: number,
  shadowColor: string,
  shadowBlur: number
) => {
  if (points.length === 0) return

  context.save()
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.strokeStyle = color
  context.lineWidth = lineWidth
  context.shadowColor = shadowColor
  context.shadowBlur = shadowBlur
  context.beginPath()
  context.moveTo(points[0].x, points[0].y)
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index]
    context.lineTo(point.x, point.y)
  }
  context.closePath()
  context.stroke()
  context.restore()
}

const traceEdgePath = (context: CanvasRenderingContext2D, points: EdgePoint[]) => {
  if (points.length === 0) return

  context.beginPath()
  context.moveTo(points[0].x, points[0].y)
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index]
    context.lineTo(point.x, point.y)
  }
  context.closePath()
}

export const getIntegratedFlameLickShape = (
  previous: EdgePoint,
  point: EdgePoint,
  next: EdgePoint,
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
): IntegratedFlameLickShape => {
  const chance = random01(point.seed + 173)
  const accents = getPathAccentAmount(tuning)
  const amplitude = getPathAmplitude(tuning)
  const pulseSpeed = getPathPulseSpeed(tuning)
  const envelope = staticMode
    ? 0.72
    : Math.max(0, Math.sin(time * 0.0025 * pulseSpeed + point.seed * 0.31) * 0.5 + 0.5)
  const tangentX = -point.ny
  const tangentY = point.nx
  const wave = edgeWave(point.seed + 67, time, staticMode, tuning)
  const baseStart = midpoint(previous, point)
  const baseEnd = midpoint(point, next)
  const anchor = midpoint(baseStart, baseEnd)
  const length =
    (5 + chance * 12) * (0.55 + accents * 0.5) * amplitude * (0.16 + envelope * 0.84)
  const width = Math.max(0.9, length * (0.14 + chance * 0.04))
  const tip = {
    x: anchor.x + point.nx * length + tangentX * wave * length * 0.38,
    y: anchor.y + point.ny * length + tangentY * wave * length * 0.38,
  }

  return {
    baseEnd,
    baseStart,
    chance,
    leftShoulder: {
      x: anchor.x + point.nx * length * 0.44 + tangentX * (width + wave * length * 0.12),
      y: anchor.y + point.ny * length * 0.44 + tangentY * (width + wave * length * 0.12),
    },
    opacity: envelope * (0.35 + chance * 0.65),
    rightShoulder: {
      x: anchor.x + point.nx * length * 0.5 - tangentX * (width * 0.78 - wave * length * 0.08),
      y: anchor.y + point.ny * length * 0.5 - tangentY * (width * 0.78 - wave * length * 0.08),
    },
    tip,
    width,
  }
}

const fillBurntShell = (
  context: CanvasRenderingContext2D,
  points: EdgePoint[],
  width: number,
  height: number
) => {
  const fill = context.createLinearGradient(0, 0, width, height)
  fill.addColorStop(0, 'rgba(10, 23, 34, 0.96)')
  fill.addColorStop(0.45, 'rgba(8, 16, 28, 0.98)')
  fill.addColorStop(1, 'rgba(7, 13, 22, 0.96)')

  context.save()
  context.shadowColor = 'rgba(0, 0, 0, 0.5)'
  context.shadowBlur = 22
  context.shadowOffsetY = 14
  context.fillStyle = fill
  traceEdgePath(context, points)
  context.fill()

  context.globalCompositeOperation = 'screen'
  const innerGlow = context.createRadialGradient(width * 0.18, 0, 0, width * 0.18, 0, width * 0.55)
  innerGlow.addColorStop(0, 'rgba(255, 203, 108, 0.08)')
  innerGlow.addColorStop(0.62, 'rgba(255, 153, 39, 0.025)')
  innerGlow.addColorStop(1, 'rgba(255, 153, 39, 0)')
  context.fillStyle = innerGlow
  traceEdgePath(context, points)
  context.fill()
  context.restore()
}

const drawEmbers = (
  context: CanvasRenderingContext2D,
  points: EdgePoint[],
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
) => {
  context.save()
  context.globalCompositeOperation = 'screen'
  const accents = getPathAccentAmount(tuning)
  const pulseSpeed = getPathPulseSpeed(tuning)
  const sampleEvery = Math.max(1, Math.floor(points.length / (28 + accents * 18)))

  for (let index = 0; index < points.length; index += sampleEvery) {
    const point = points[index]
    const chance = random01(point.seed + 77)
    if (chance < 0.9 - accents * 0.08) continue

    const drift = edgeWave(point.seed + 9, time, staticMode, tuning)
    const pulse = staticMode
      ? 0.3
      : 0.2 + Math.sin(time * 0.003 * pulseSpeed + point.seed) * 0.08
    const radius = (0.4 + chance * 0.8) * (0.75 + accents * 0.25)
    const x = point.x - point.nx * (3 + drift * 4)
    const y = point.y - point.ny * (3 + drift * 4)
    const gradient = context.createRadialGradient(x, y, 0, x, y, radius * 3.5)

    gradient.addColorStop(0, `rgba(255, 230, 166, ${0.32 * pulse})`)
    gradient.addColorStop(0.34, `rgba(255, 165, 58, ${0.2 * pulse})`)
    gradient.addColorStop(1, 'rgba(255, 98, 18, 0)')
    context.fillStyle = gradient
    context.beginPath()
    context.arc(x, y, radius * 3.5, 0, TAU)
    context.fill()
  }

  context.restore()
}

const drawAccentCurls = (
  context: CanvasRenderingContext2D,
  points: EdgePoint[],
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
) => {
  const accents = getPathAccentAmount(tuning)
  const amplitude = getPathAmplitude(tuning)
  if (accents <= 0.05) return

  context.save()
  context.globalCompositeOperation = 'screen'
  context.lineCap = 'round'
  context.lineJoin = 'round'
  const count = Math.floor(8 + accents * 18)
  const spacing = Math.max(1, Math.floor(points.length / count))

  for (let index = 0; index < points.length; index += spacing) {
    const point = points[index]
    const chance = random01(point.seed + 131)
    if (chance < 0.58) continue

    const curl = edgeWave(point.seed + 55, time, staticMode, tuning)
    const length = (8 + chance * 18) * accents * amplitude
    const tangentX = -point.ny
    const tangentY = point.nx
    const startX = point.x - point.nx * 2
    const startY = point.y - point.ny * 2
    const controlX = startX - point.nx * length * 0.8 + tangentX * curl * length * 0.7
    const controlY = startY - point.ny * length * 0.8 + tangentY * curl * length * 0.7
    const endX = startX - point.nx * length * 0.35 - tangentX * curl * length * 0.55
    const endY = startY - point.ny * length * 0.35 - tangentY * curl * length * 0.55

    context.strokeStyle = `rgba(255, 169, 61, ${0.05 + accents * 0.07})`
    context.lineWidth = 0.65 + accents * 0.45
    context.shadowColor = 'rgba(255, 121, 31, 0.26)'
    context.shadowBlur = 6 + accents * 5
    context.beginPath()
    context.moveTo(startX, startY)
    context.quadraticCurveTo(controlX, controlY, endX, endY)
    context.stroke()
  }

  context.restore()
}

const drawFlameLicks = (
  context: CanvasRenderingContext2D,
  points: EdgePoint[],
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
) => {
  const accents = getPathAccentAmount(tuning)
  if (accents <= 0.05) return

  context.save()
  context.globalCompositeOperation = 'screen'
  context.lineCap = 'round'
  context.lineJoin = 'round'
  const count = Math.floor(10 + accents * 16)
  const spacing = Math.max(1, Math.floor(points.length / count))

  for (let index = 0; index < points.length; index += spacing) {
    const previous = points[(index - 1 + points.length) % points.length]
    const point = points[index]
    const next = points[(index + 1) % points.length]
    const shape = getIntegratedFlameLickShape(previous, point, next, time, staticMode, tuning)
    if (shape.chance < 0.42 || shape.opacity < 0.08) continue

    const glow = context.createLinearGradient(
      (shape.baseStart.x + shape.baseEnd.x) / 2,
      (shape.baseStart.y + shape.baseEnd.y) / 2,
      shape.tip.x,
      shape.tip.y
    )

    glow.addColorStop(0, `rgba(255, 108, 24, ${0.015 + shape.opacity * 0.035})`)
    glow.addColorStop(0.38, `rgba(255, 172, 42, ${0.045 + shape.opacity * 0.08})`)
    glow.addColorStop(0.72, `rgba(255, 238, 154, ${0.055 + shape.opacity * 0.11})`)
    glow.addColorStop(1, 'rgba(255, 89, 17, 0)')

    context.fillStyle = glow
    context.shadowColor = `rgba(255, 113, 18, ${0.1 + shape.opacity * 0.16})`
    context.shadowBlur = 5 + accents * 7
    context.beginPath()
    context.moveTo(shape.baseStart.x, shape.baseStart.y)
    context.bezierCurveTo(
      shape.leftShoulder.x,
      shape.leftShoulder.y,
      shape.tip.x + -point.ny * shape.width * 0.28,
      shape.tip.y + point.nx * shape.width * 0.28,
      shape.tip.x,
      shape.tip.y
    )
    context.bezierCurveTo(
      shape.tip.x - -point.ny * shape.width * 0.24,
      shape.tip.y - point.nx * shape.width * 0.24,
      shape.rightShoulder.x,
      shape.rightShoulder.y,
      shape.baseEnd.x,
      shape.baseEnd.y
    )
    context.quadraticCurveTo(point.x, point.y, shape.baseStart.x, shape.baseStart.y)
    context.fill()

    context.strokeStyle = `rgba(255, 232, 157, ${0.08 + shape.opacity * 0.18})`
    context.lineWidth = 0.35 + accents * 0.32
    context.shadowBlur = 3 + accents * 4
    context.beginPath()
    context.moveTo(point.x, point.y)
    context.quadraticCurveTo(shape.leftShoulder.x, shape.leftShoulder.y, shape.tip.x, shape.tip.y)
    context.stroke()

    const fleckChance = random01(point.seed + 307)
    if (fleckChance > 0.58 && shape.opacity > 0.24) {
      const drift = edgeWave(point.seed + 91, time * 0.85, staticMode, tuning)
      const fleckRadius = 0.45 + fleckChance * 0.8
      const fleckX = shape.tip.x + point.nx * (1 + fleckChance * 4) + -point.ny * drift * 4
      const fleckY = shape.tip.y + point.ny * (1 + fleckChance * 4) + point.nx * drift * 4
      const fleckGlow = context.createRadialGradient(fleckX, fleckY, 0, fleckX, fleckY, fleckRadius * 4)

      fleckGlow.addColorStop(0, `rgba(255, 238, 177, ${shape.opacity * 0.24})`)
      fleckGlow.addColorStop(0.42, `rgba(255, 137, 30, ${shape.opacity * 0.12})`)
      fleckGlow.addColorStop(1, 'rgba(255, 87, 17, 0)')
      context.fillStyle = fleckGlow
      context.beginPath()
      context.arc(fleckX, fleckY, fleckRadius * 4, 0, TAU)
      context.fill()
    }
  }

  context.restore()
}

type ThresholdMaskCache = {
  canvas: HTMLCanvasElement
  context: CanvasRenderingContext2D
  edgeDepth: Float32Array
  imageData: ImageData
  maskHeight: number
  maskWidth: number
  noise: Float32Array
  sourceHeight: number
  sourceWidth: number
}

const thresholdMaskCaches = new Map<string, ThresholdMaskCache>()
const THRESHOLD_MASK_SCALE = 0.42
const THRESHOLD_MASK_MAX_SIZE = 420
const THRESHOLD_MASK_MIN_SIZE = 72
const THRESHOLD_EDGE_INSET = 9

const valueNoise2d = (x: number, y: number, seed: number) => {
  const x0 = Math.floor(x)
  const y0 = Math.floor(y)
  const fx = smoothstep(fract(x))
  const fy = smoothstep(fract(y))
  const seedOffset = seed * 37.13
  const topLeft = random01(x0 * 127.1 + y0 * 311.7 + seedOffset)
  const topRight = random01((x0 + 1) * 127.1 + y0 * 311.7 + seedOffset)
  const bottomLeft = random01(x0 * 127.1 + (y0 + 1) * 311.7 + seedOffset)
  const bottomRight = random01((x0 + 1) * 127.1 + (y0 + 1) * 311.7 + seedOffset)

  return lerp(lerp(topLeft, topRight, fx), lerp(bottomLeft, bottomRight, fx), fy)
}

const fractalValueNoise2d = (x: number, y: number, seed: number) => {
  let amplitude = 0.56
  let frequency = 1
  let total = 0
  let normalizer = 0

  for (let octave = 0; octave < 4; octave += 1) {
    total += valueNoise2d(x * frequency, y * frequency, seed + octave * 19.37) * amplitude
    normalizer += amplitude
    amplitude *= 0.52
    frequency *= 2.08
  }

  return total / normalizer
}

const roundedRectSignedDistance = (
  x: number,
  y: number,
  width: number,
  height: number,
  inset: number,
  radius: number
) => {
  const halfWidth = Math.max(0, width / 2 - inset - radius)
  const halfHeight = Math.max(0, height / 2 - inset - radius)
  const dx = Math.abs(x - width / 2) - halfWidth
  const dy = Math.abs(y - height / 2) - halfHeight
  const outsideDistance = Math.hypot(Math.max(dx, 0), Math.max(dy, 0))
  const insideDistance = Math.min(Math.max(dx, dy), 0)

  return outsideDistance + insideDistance - radius
}

const getThresholdMaskDimensions = (width: number, height: number) => {
  const longestSide = Math.max(width, height)
  const scale = Math.min(THRESHOLD_MASK_SCALE, THRESHOLD_MASK_MAX_SIZE / longestSide)

  return {
    maskHeight: Math.max(THRESHOLD_MASK_MIN_SIZE, Math.round(height * scale)),
    maskWidth: Math.max(THRESHOLD_MASK_MIN_SIZE, Math.round(width * scale)),
  }
}

const createThresholdMaskCache = (
  width: number,
  height: number,
  frequencyBucket: number
): ThresholdMaskCache | null => {
  const { maskHeight, maskWidth } = getThresholdMaskDimensions(width, height)
  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d', { alpha: true })

  if (!context) return null

  canvas.width = maskWidth
  canvas.height = maskHeight

  const imageData = context.createImageData(maskWidth, maskHeight)
  const noise = new Float32Array(maskWidth * maskHeight)
  const edgeDepth = new Float32Array(maskWidth * maskHeight)
  const radius = Math.min(20, width / 9, height / 9)
  const noiseScale = 0.038 + frequencyBucket * 0.0016
  const panelSeed = width * 0.137 + height * 0.233 + frequencyBucket * 3.17

  for (let y = 0; y < maskHeight; y += 1) {
    for (let x = 0; x < maskWidth; x += 1) {
      const index = y * maskWidth + x
      const sourceX = (x / Math.max(1, maskWidth - 1)) * width
      const sourceY = (y / Math.max(1, maskHeight - 1)) * height
      const distance = roundedRectSignedDistance(
        sourceX,
        sourceY,
        width,
        height,
        THRESHOLD_EDGE_INSET,
        radius
      )

      edgeDepth[index] = -distance
      noise[index] = fractalValueNoise2d(x * noiseScale, y * noiseScale, panelSeed)
    }
  }

  return {
    canvas,
    context,
    edgeDepth,
    imageData,
    maskHeight,
    maskWidth,
    noise,
    sourceHeight: height,
    sourceWidth: width,
  }
}

const getThresholdMaskCache = (
  width: number,
  height: number,
  tuning: FireBorderTuning
): ThresholdMaskCache | null => {
  const frequencyBucket = Math.round((tuning.edgeFrequency / 0.02) * 12)
  const { maskHeight, maskWidth } = getThresholdMaskDimensions(width, height)
  const key = `${Math.round(width)}x${Math.round(height)}:${maskWidth}x${maskHeight}:${frequencyBucket}`
  const cached = thresholdMaskCaches.get(key)

  if (cached) return cached

  const cache = createThresholdMaskCache(width, height, frequencyBucket)
  if (!cache) return null

  thresholdMaskCaches.set(key, cache)
  if (thresholdMaskCaches.size > 12) {
    const [oldestKey] = thresholdMaskCaches.keys()
    thresholdMaskCaches.delete(oldestKey)
  }

  return cache
}

const renderThresholdMaskBorder = (
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
) => {
  context.clearRect(0, 0, width, height)
  if (width < 80 || height < 80) return

  const cache = getThresholdMaskCache(width, height, tuning)
  if (!cache) return

  const {
    context: maskContext,
    edgeDepth,
    imageData,
    maskHeight,
    maskWidth,
    noise,
  } = cache
  const data = imageData.data
  const amplitude = getPathAmplitude(tuning)
  const accents = getPathAccentAmount(tuning)
  const pulseSpeed = getPathPulseSpeed(tuning)
  const frequency = getPathFrequency(tuning)
  const edgeSpan = 16 + amplitude * 7
  const outerFeather = 7 + amplitude * 2
  const threshold =
    0.37 +
    (staticMode ? 0 : Math.sin(time * 0.0013 * pulseSpeed) * tuning.pulseDepth * 0.09)
  const driftX = staticMode ? 0 : Math.floor(time * 0.008 * tuning.driftSpeed)
  const driftY = staticMode ? 0 : Math.floor(time * 0.005 * tuning.driftSpeed)
  const noiseStrength = 0.24 + frequency * 0.045 + accents * 0.018
  const movingNoiseStrength = 0.08 + accents * 0.02

  for (let y = 0; y < maskHeight; y += 1) {
    const shiftedY = ((y + driftY) % maskHeight + maskHeight) % maskHeight

    for (let x = 0; x < maskWidth; x += 1) {
      const index = y * maskWidth + x
      const dataIndex = index * 4
      const depth = edgeDepth[index]

      if (depth < -outerFeather) {
        data[dataIndex] = 0
        data[dataIndex + 1] = 0
        data[dataIndex + 2] = 0
        data[dataIndex + 3] = 0
        continue
      }

      const shiftedX = ((x + driftX) % maskWidth + maskWidth) % maskWidth
      const shiftedNoise = noise[shiftedY * maskWidth + shiftedX]
      const edgeProgress = clamp01((depth + outerFeather) / edgeSpan)
      const shimmer = staticMode
        ? 0
        : Math.sin(time * 0.0022 * pulseSpeed + noise[index] * TAU) * 0.016
      const noiseValue = clamp01(
        edgeProgress +
          (noise[index] - 0.5) * noiseStrength +
          (shiftedNoise - 0.5) * movingNoiseStrength +
          shimmer
      )
      const band = getThresholdBurnBand(noiseValue, threshold)

      if (band.zone === 'transparent') {
        data[dataIndex] = 0
        data[dataIndex + 1] = 0
        data[dataIndex + 2] = 0
        data[dataIndex + 3] = 0
        continue
      }

      const variation = noise[index] - 0.5
      const glowBoost = band.zone === 'glow' ? 1 + accents * 0.08 : 1
      const alphaScale = band.zone === 'fill' ? 0.88 + edgeProgress * 0.12 : glowBoost

      data[dataIndex] = clamp(band.red + variation * 22, 0, 255)
      data[dataIndex + 1] = clamp(band.green + variation * 18, 0, 255)
      data[dataIndex + 2] = clamp(band.blue + variation * 10, 0, 255)
      data[dataIndex + 3] = clamp(band.alpha * alphaScale, 0, 255)
    }
  }

  maskContext.putImageData(imageData, 0, 0)

  context.save()
  context.imageSmoothingEnabled = true
  context.globalCompositeOperation = 'source-over'
  context.drawImage(cache.canvas, 0, 0, width, height)
  context.globalCompositeOperation = 'screen'
  context.filter = `blur(${2.4 + tuning.glowRadius * 0.1}px)`
  context.globalAlpha = 0.42
  context.drawImage(cache.canvas, 0, 0, width, height)
  context.filter = 'none'
  context.globalAlpha = 1
  context.restore()
}

const renderBurningPaperMaskBorder = (
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning
) => {
  context.clearRect(0, 0, width, height)
  if (width < 80 || height < 80) return

  const cache = getThresholdMaskCache(width, height, tuning)
  if (!cache) return

  const {
    context: maskContext,
    edgeDepth,
    imageData,
    maskHeight,
    maskWidth,
    noise,
  } = cache
  const data = imageData.data
  const edgeAmp = tuning.edgeAmplitude
  const flickAmp = tuning.flickerAmount
  const charDepth = tuning.charDepth
  const glowOut = tuning.glowBleed
  const driftX = staticMode ? 0 : Math.floor(time * 0.0045 * tuning.driftSpeed)
  const driftY = staticMode ? 0 : Math.floor(time * 0.013 * tuning.driftSpeed)
  const shimmerX = staticMode ? 0 : Math.floor(time * 0.028 * tuning.flickerSpeed)
  const shimmerY = staticMode ? 0 : Math.floor(-time * 0.021 * tuning.flickerSpeed)
  const softnessScale = Math.max(0.2, tuning.softness / 2.6)
  const farVoidCutoff = glowOut + edgeAmp + flickAmp + 3
  const deepPaperCutoff = -(charDepth + edgeAmp + flickAmp + 18)

  for (let y = 0; y < maskHeight; y += 1) {
    const driftedY = ((y + driftY) % maskHeight + maskHeight) % maskHeight
    const shimmeredY = ((y + shimmerY) % maskHeight + maskHeight) % maskHeight

    for (let x = 0; x < maskWidth; x += 1) {
      const index = y * maskWidth + x
      const dataIndex = index * 4
      const outerDistance = -edgeDepth[index]
      const localTexture = noise[index] - 0.5

      if (outerDistance > farVoidCutoff) {
        data[dataIndex] = 0
        data[dataIndex + 1] = 0
        data[dataIndex + 2] = 0
        data[dataIndex + 3] = 0
        continue
      }

      if (outerDistance < deepPaperCutoff) {
        const parchmentVariation = localTexture * 18 * tuning.detail
        data[dataIndex] = clamp(PAPER_BASE_COLOR[0] + parchmentVariation, 0, 255)
        data[dataIndex + 1] = clamp(PAPER_BASE_COLOR[1] + parchmentVariation * 0.8, 0, 255)
        data[dataIndex + 2] = clamp(PAPER_BASE_COLOR[2] + parchmentVariation * 0.55, 0, 255)
        data[dataIndex + 3] = 232
        continue
      }

      const driftedX = ((x + driftX) % maskWidth + maskWidth) % maskWidth
      const shimmeredX = ((x + shimmerX) % maskWidth + maskWidth) % maskWidth
      const bigNoise = noise[driftedY * maskWidth + driftedX] - 0.5
      const fastNoise = noise[shimmeredY * maskWidth + shimmeredX] - 0.5
      const pulse =
        staticMode
          ? 0
          : Math.sin(time * 0.0015 * tuning.pulseSpeed + localTexture * TAU) *
            tuning.pulseDepth *
            edgeAmp
      const edgeValue = outerDistance + bigNoise * edgeAmp * 2 + fastNoise * flickAmp * 2 + pulse
      const shade = getBurningPaperShade(edgeValue / softnessScale, { charDepth, glowOut })

      if (shade.zone === 'transparent') {
        data[dataIndex] = 0
        data[dataIndex + 1] = 0
        data[dataIndex + 2] = 0
        data[dataIndex + 3] = 0
        continue
      }

      const textureAmount = shade.zone === 'paper' ? 18 : 8
      const texture = localTexture * textureAmount
      const emberBoost = shade.zone === 'lip' || shade.zone === 'flame' ? tuning.embers * 6 : 0

      data[dataIndex] = clamp(shade.red + texture + emberBoost, 0, 255)
      data[dataIndex + 1] = clamp(shade.green + texture * 0.75 + emberBoost * 0.4, 0, 255)
      data[dataIndex + 2] = clamp(shade.blue + texture * 0.45, 0, 255)
      data[dataIndex + 3] = shade.alpha
    }
  }

  maskContext.putImageData(imageData, 0, 0)

  context.save()
  context.imageSmoothingEnabled = true
  context.clearRect(0, 0, width, height)
  context.globalCompositeOperation = 'screen'
  context.filter = `blur(${tuning.glowRadius}px)`
  context.globalAlpha = tuning.outerGlow
  context.drawImage(cache.canvas, 0, 0, width, height)
  context.filter = 'none'
  context.globalAlpha = 1
  context.globalCompositeOperation = 'source-over'
  context.drawImage(cache.canvas, 0, 0, width, height)
  context.restore()
}

const renderBorder = (
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning,
  accentStyle: FireBorderAccentStyle,
  renderStyle: FireBorderRenderStyle
) => {
  context.clearRect(0, 0, width, height)
  if (width < 80 || height < 80) return

  if (renderStyle === 'thresholdMask') {
    renderThresholdMaskBorder(context, width, height, time, staticMode, tuning)
    return
  }

  if (renderStyle === 'paperMask') {
    renderBurningPaperMaskBorder(context, width, height, time, staticMode, tuning)
    return
  }

  const inset = 9
  const radius = Math.min(20, width / 9, height / 9)
  const outer = buildEdgePath(width, height, inset, radius, time, staticMode, 3.8, tuning)
  const inner = buildEdgePath(width, height, inset + 4, radius - 2, time + 230, staticMode, 2.1, tuning)

  context.save()
  context.globalCompositeOperation = 'source-over'
  fillBurntShell(context, outer, width, height)
  strokeEdge(context, outer, 'rgba(31, 11, 5, 0.22)', 14, 'rgba(18, 6, 3, 0.32)', 7)

  context.globalCompositeOperation = 'screen'
  strokeEdge(context, outer, 'rgba(148, 50, 11, 0.1)', 19, 'rgba(255, 94, 20, 0.17)', 18)
  strokeEdge(context, outer, 'rgba(226, 118, 31, 0.14)', 7, 'rgba(255, 132, 34, 0.18)', 12)
  if (accentStyle === 'flameLicks') {
    drawFlameLicks(context, inner, time, staticMode, tuning)
  }
  strokeEdge(context, inner, 'rgba(255, 187, 75, 0.24)', 3, 'rgba(255, 178, 62, 0.26)', 9)
  strokeEdge(context, inner, 'rgba(255, 237, 179, 0.32)', 1, 'rgba(255, 225, 151, 0.18)', 5)
  if (accentStyle === 'curls') {
    drawAccentCurls(context, inner, time, staticMode, tuning)
  }
  drawEmbers(context, inner, time, staticMode, tuning)
  context.restore()
}

export const GamePanelFireBorder = ({
  accentStyle = defaultFireBorderAccentStyle,
  renderStyle = defaultFireBorderRenderStyle,
  tuning = defaultFireBorderTuning,
}: {
  accentStyle?: FireBorderAccentStyle
  renderStyle?: FireBorderRenderStyle
  tuning?: FireBorderTuning
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const accentStyleRef = useRef(accentStyle)
  const renderStyleRef = useRef(renderStyle)
  const tuningRef = useRef(tuning)

  useEffect(() => {
    accentStyleRef.current = accentStyle
  }, [accentStyle])

  useEffect(() => {
    renderStyleRef.current = renderStyle
  }, [renderStyle])

  useEffect(() => {
    tuningRef.current = tuning
  }, [tuning])

  useEffect(() => {
    const canvas = canvasRef.current
    const frame = canvas?.parentElement
    if (!canvas || !frame || typeof ResizeObserver === 'undefined') return

    const context = canvas.getContext('2d')
    if (!context) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const coarsePointer = window.matchMedia('(pointer: coarse)')
    let animationFrame = 0
    let width = 0
    let height = 0
    let frameIntervalMs = 0
    let lastRenderTime = Number.NEGATIVE_INFINITY

    const resizeCanvas = () => {
      const rect = frame.getBoundingClientRect()
      const nextWidth = Math.max(1, Math.round(rect.width))
      const nextHeight = Math.max(1, Math.round(rect.height))
      const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2))

      width = nextWidth
      height = nextHeight
      canvas.width = Math.round(nextWidth * dpr)
      canvas.height = Math.round(nextHeight * dpr)
      canvas.style.width = `${nextWidth}px`
      canvas.style.height = `${nextHeight}px`
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      frameIntervalMs = getFireBorderFrameIntervalMs({
        coarsePointer: coarsePointer.matches,
        viewportWidth: window.innerWidth,
      })
    }

    const draw = (time: number) => {
      lastRenderTime = time
      renderBorder(
        context,
        width,
        height,
        time,
        reducedMotion.matches,
        tuningRef.current,
        accentStyleRef.current,
        renderStyleRef.current
      )
    }

    const animate = (time: number) => {
      if (
        frameIntervalMs === 0 ||
        time - lastRenderTime >= frameIntervalMs - FRAME_INTERVAL_TOLERANCE_MS
      ) {
        draw(time)
      }
      if (!reducedMotion.matches && document.visibilityState !== 'hidden') {
        animationFrame = window.requestAnimationFrame(animate)
      }
    }

    const start = () => {
      window.cancelAnimationFrame(animationFrame)
      lastRenderTime = Number.NEGATIVE_INFINITY
      resizeCanvas()
      if (reducedMotion.matches || document.visibilityState === 'hidden') {
        draw(0)
        return
      }
      animationFrame = window.requestAnimationFrame(animate)
    }

    const handleVisibility = () => start()
    const observer = new ResizeObserver(start)

    observer.observe(frame)
    reducedMotion.addEventListener('change', start)
    coarsePointer.addEventListener('change', start)
    document.addEventListener('visibilitychange', handleVisibility)
    start()

    return () => {
      window.cancelAnimationFrame(animationFrame)
      observer.disconnect()
      reducedMotion.removeEventListener('change', start)
      coarsePointer.removeEventListener('change', start)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  return (
    <canvas
      aria-hidden="true"
      className="game-panel-fire-border"
      data-render-style={renderStyle}
      data-testid="game-panel-fire-border"
      ref={canvasRef}
    />
  )
}
