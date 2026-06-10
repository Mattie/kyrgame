import type { CSSProperties } from 'react'

import { formatGemstoneLabel, getGemstoneVisual } from '../data/gemstonePalette'
import { getGroundObjectVisual } from '../data/groundObjectVisuals'
import { GemstoneText } from './GemstoneText'

type GemstoneBadgeProps = {
  name: string
}

const badgeStyle = (light?: string, dark?: string): CSSProperties => ({
  '--gem-light': light ?? '#0ea5e9',
  '--gem-dark': dark ?? '#0b1020',
  color: dark ?? '#c7ffda',
} as CSSProperties)

export const GemstoneBadge = ({ name }: GemstoneBadgeProps) => {
  const visual = getGemstoneVisual(name)
  const groundObjectVisual = getGroundObjectVisual(name)

  if (groundObjectVisual) {
    return (
      <span
        className={`gemstone-badge ground-object-badge ${groundObjectVisual.className}`}
        data-testid={`ground-object-badge-${groundObjectVisual.name}`}
        style={badgeStyle(groundObjectVisual.color, groundObjectVisual.darkColor)}
      >
        <span className="gem-emoji" aria-hidden="true">
          {groundObjectVisual.emoji}
        </span>
        <span className="gem-name">{groundObjectVisual.displayName}</span>
        <span className="sr-only">{groundObjectVisual.displayName} ground object</span>
      </span>
    )
  }

  if (!visual) {
    return (
      <span className="gemstone-badge" style={badgeStyle()}>
        <GemstoneText text={formatGemstoneLabel(name)} />
      </span>
    )
  }

  return (
    <span
      className="gemstone-badge"
      data-testid={`gemstone-badge-${visual.name}`}
      style={badgeStyle(visual.lightColor, visual.darkColor)}
    >
      <span className="gem-emoji" aria-hidden="true">
        {visual.emoji}
      </span>
      <span className="gem-name">{visual.displayName}</span>
      <span className="sr-only">{visual.displayName} gemstone</span>
    </span>
  )
}
