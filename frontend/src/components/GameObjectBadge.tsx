import { getGemstoneTheme } from '../assets/gemstoneThemes'

type Props = {
  name: string
}

export const GameObjectBadge = ({ name }: Props) => {
  const theme = getGemstoneTheme(name)
  const displayName = name || 'Unknown object'

  if (!theme) {
    return <span className="object-badge">{displayName}</span>
  }

  return (
    <span
      className="object-badge gemstone"
      data-gemstone={theme.name}
      data-testid={`object-badge-${theme.name}`}
      style={{
        background: `linear-gradient(135deg, ${theme.lightColor}, ${theme.darkColor})`,
        borderColor: theme.darkColor,
      }}
    >
      <span className="object-emoji" aria-hidden>
        {theme.emoji}
      </span>
      <span className="object-name">{displayName}</span>
    </span>
  )
}
