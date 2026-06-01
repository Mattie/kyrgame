import { useEffect, useRef } from 'react'

export type EdgePoint = {
  x: number
  y: number
  nx: number
  ny: number
  seed: number
}

export type FireBorderTuning = {
  pulseSpeed: number
  frequency: number
  amplitude: number
  accents: number
}

export const fireBorderAccentStyles = ['curls', 'flameLicks'] as const
export type FireBorderAccentStyle = (typeof fireBorderAccentStyles)[number]

export const defaultFireBorderTuning: FireBorderTuning = {
  pulseSpeed: 1.1,
  frequency: 0.6,
  amplitude: 0.75,
  accents: 0.65,
}

export const defaultFireBorderAccentStyle: FireBorderAccentStyle = 'flameLicks'

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
  const t = staticMode ? 0 : time * tuning.pulseSpeed
  const frequency = tuning.frequency
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
  const tunedStrength = strength * tuning.amplitude
  const deckle = (random01(seed) - 0.5) * tunedStrength * 0.72
  const shimmer = edgeWave(seed, time, staticMode, tuning) * tunedStrength
  const tangent =
    edgeWave(seed + 41, time * 0.7, staticMode, tuning) * tunedStrength * 0.18 * tuning.accents
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
  const step = Math.max(4, 12 - tuning.frequency * 4)
  const arcStep = Math.PI / Math.max(18, 18 + tuning.frequency * 13)
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
  const envelope = staticMode
    ? 0.72
    : Math.max(0, Math.sin(time * 0.0025 * tuning.pulseSpeed + point.seed * 0.31) * 0.5 + 0.5)
  const tangentX = -point.ny
  const tangentY = point.nx
  const wave = edgeWave(point.seed + 67, time, staticMode, tuning)
  const baseStart = midpoint(previous, point)
  const baseEnd = midpoint(point, next)
  const anchor = midpoint(baseStart, baseEnd)
  const length =
    (5 + chance * 12) * (0.55 + tuning.accents * 0.5) * tuning.amplitude * (0.16 + envelope * 0.84)
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
  const sampleEvery = Math.max(1, Math.floor(points.length / (28 + tuning.accents * 18)))

  for (let index = 0; index < points.length; index += sampleEvery) {
    const point = points[index]
    const chance = random01(point.seed + 77)
    if (chance < 0.9 - tuning.accents * 0.08) continue

    const drift = edgeWave(point.seed + 9, time, staticMode, tuning)
    const pulse = staticMode
      ? 0.3
      : 0.2 + Math.sin(time * 0.003 * tuning.pulseSpeed + point.seed) * 0.08
    const radius = (0.4 + chance * 0.8) * (0.75 + tuning.accents * 0.25)
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
  if (tuning.accents <= 0.05) return

  context.save()
  context.globalCompositeOperation = 'screen'
  context.lineCap = 'round'
  context.lineJoin = 'round'
  const count = Math.floor(8 + tuning.accents * 18)
  const spacing = Math.max(1, Math.floor(points.length / count))

  for (let index = 0; index < points.length; index += spacing) {
    const point = points[index]
    const chance = random01(point.seed + 131)
    if (chance < 0.58) continue

    const curl = edgeWave(point.seed + 55, time, staticMode, tuning)
    const length = (8 + chance * 18) * tuning.accents * tuning.amplitude
    const tangentX = -point.ny
    const tangentY = point.nx
    const startX = point.x - point.nx * 2
    const startY = point.y - point.ny * 2
    const controlX = startX - point.nx * length * 0.8 + tangentX * curl * length * 0.7
    const controlY = startY - point.ny * length * 0.8 + tangentY * curl * length * 0.7
    const endX = startX - point.nx * length * 0.35 - tangentX * curl * length * 0.55
    const endY = startY - point.ny * length * 0.35 - tangentY * curl * length * 0.55

    context.strokeStyle = `rgba(255, 169, 61, ${0.05 + tuning.accents * 0.07})`
    context.lineWidth = 0.65 + tuning.accents * 0.45
    context.shadowColor = 'rgba(255, 121, 31, 0.26)'
    context.shadowBlur = 6 + tuning.accents * 5
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
  if (tuning.accents <= 0.05) return

  context.save()
  context.globalCompositeOperation = 'screen'
  context.lineCap = 'round'
  context.lineJoin = 'round'
  const count = Math.floor(10 + tuning.accents * 16)
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
    context.shadowBlur = 5 + tuning.accents * 7
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
    context.lineWidth = 0.35 + tuning.accents * 0.32
    context.shadowBlur = 3 + tuning.accents * 4
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

const renderBorder = (
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  time: number,
  staticMode: boolean,
  tuning: FireBorderTuning,
  accentStyle: FireBorderAccentStyle
) => {
  context.clearRect(0, 0, width, height)
  if (width < 80 || height < 80) return

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
  tuning = defaultFireBorderTuning,
}: {
  accentStyle?: FireBorderAccentStyle
  tuning?: FireBorderTuning
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const accentStyleRef = useRef(accentStyle)
  const tuningRef = useRef(tuning)

  useEffect(() => {
    accentStyleRef.current = accentStyle
  }, [accentStyle])

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
        accentStyleRef.current
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
      data-testid="game-panel-fire-border"
      ref={canvasRef}
    />
  )
}
