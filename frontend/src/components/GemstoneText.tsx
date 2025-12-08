import { Fragment, ReactNode } from 'react'

import { getGemstoneVisual } from '../data/gemstonePalette'

/**
 * Parses text and renders gemstone names with their emoji and color styling.
 * Matches gemstone names case-insensitively and replaces them with styled spans.
 */
export const GemstoneText = ({ text }: { text: string }): JSX.Element => {
  // List of gemstone names to search for (case-insensitive)
  const gemstoneNames = [
    'ruby',
    'emerald',
    'garnet',
    'pearl',
    'aquamarine',
    'moonstone',
    'sapphire',
    'diamond',
    'amethyst',
    'onyx',
    'opal',
    'bloodstone',
    'kyragem',
    'soulstone',
  ]

  // Create a regex pattern that matches any gemstone name (case-insensitive, word boundaries)
  const pattern = new RegExp(`\\b(${gemstoneNames.join('|')})\\b`, 'gi')

  const parts: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    const matchedText = match[0]
    const matchIndex = match.index

    // Add text before the match
    if (matchIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchIndex))
    }

    // Get gemstone visual data
    const visual = getGemstoneVisual(matchedText)

    if (visual) {
      // Render gemstone with emoji and color
      parts.push(
        <span
          key={`gem-${matchIndex}`}
          style={{ color: visual.darkColor }}
          className="gemstone-inline"
        >
          {visual.emoji} {matchedText}
        </span>
      )
    } else {
      // Fallback if visual not found
      parts.push(matchedText)
    }

    lastIndex = pattern.lastIndex
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return <>{parts.map((part, i) => (typeof part === 'string' ? <Fragment key={i}>{part}</Fragment> : part))}</>
}
