import type { CSSProperties } from 'react'

import { formatGemstoneLabel, getGemstoneVisual } from '../data/gemstonePalette'

type GemstoneBadgeProps = {
  name: string
}

const badgeStyle = (light?: string, dark?: string): CSSProperties => ({
  '--gem-light': light ?? '#0ea5e9',
  '--gem-dark': dark ?? '#0b1020',
})

export const GemstoneBadge = ({ name }: GemstoneBadgeProps) => {
  const visual = getGemstoneVisual(name)

  if (!visual) {
    return (
      <span className="gemstone-badge" style={badgeStyle()}>
        {formatGemstoneLabel(name)}
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
