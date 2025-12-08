import { ReactNode } from 'react'

import { gemstonePalette, getGemstoneVisual } from '../data/gemstonePalette'

/**
 * Parses text and renders gemstone names with their emoji and color styling.
 * Matches gemstone names case-insensitively and replaces them with styled spans.
 */
export const GemstoneText = ({ text }: { text: string }): JSX.Element => {
  // Get gemstone names from the palette to maintain single source of truth
  const gemstoneNames = Object.keys(gemstonePalette)

  // Create a regex pattern that matches any gemstone name (case-insensitive, word boundaries)
  const pattern = new RegExp(`\\b(${gemstoneNames.join('|')})\\b`, 'gi')

  const parts: ReactNode[] = []
  let lastIndex = 0

  // Use matchAll for safer iteration
  const matches = text.matchAll(pattern)

  for (const match of matches) {
    const matchedText = match[0]
    const matchIndex = match.index!

    // Add text before the match
    if (matchIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchIndex))
    }

    // Get gemstone visual data
    const visual = getGemstoneVisual(matchedText)

    if (visual) {
      // Render gemstone with emoji and light color for visibility on dark background
      parts.push(
        <span
          key={`gem-${matchIndex}`}
          style={{ color: visual.lightColor }}
          className="gemstone-inline"
        >
          {visual.emoji} {matchedText}
        </span>
      )
    } else {
      // Fallback if visual not found
      parts.push(matchedText)
    }

    lastIndex = matchIndex + matchedText.length
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  // Return parts directly without unnecessary Fragment wrappers
  return <>{parts}</>
}
