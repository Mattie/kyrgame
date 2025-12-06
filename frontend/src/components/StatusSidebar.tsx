import { useMemo } from 'react'

import { useNavigator } from '../context/NavigatorContext'

const emphasizeInventory = (description: string, inventory: string[]) => {
  const tokens = description.split(/(\s+)/)
  return tokens.map((token, index) => {
    const match = inventory.find((item) => token.toLowerCase().includes(item.toLowerCase()))
    if (match) {
      return (
        <strong key={`${token}-${index}`}>
          {token}
        </strong>
      )
    }
    return <span key={`${token}-${index}`}>{token}</span>
  })
}

export const StatusSidebar = () => {
  const { characterStatus, statusRevealed } = useNavigator()

  const description = useMemo(() => {
    if (!characterStatus?.description) return null
    if (!characterStatus.inventory || characterStatus.inventory.length === 0) {
      return characterStatus.description
    }
    return emphasizeInventory(characterStatus.description, characterStatus.inventory)
  }, [characterStatus?.description, characterStatus?.inventory])

  if (!statusRevealed || !characterStatus) return null

  return (
    <aside className="panel status-panel" data-testid="status-card">
      <header>
        <p className="eyebrow">Status</p>
        <h2>Character card</h2>
      </header>

      <dl className="status__stats">
        <div>
          <dt>Hitpoints</dt>
          <dd>{' '}{characterStatus.hitpoints ?? '—'}</dd>
        </div>
        <div>
          <dt>Spell points</dt>
          <dd>{' '}{characterStatus.spellPoints ?? '—'}</dd>
        </div>
      </dl>

      {description && (
        <div className="status__block">
          <h3>Self description</h3>
          <p>{description}</p>
        </div>
      )}

      {characterStatus.effects && characterStatus.effects.length > 0 && (
        <div className="status__block">
          <h3>Spell effects</h3>
          <ul>
            {characterStatus.effects.map((effect) => (
              <li key={effect}>{effect}</li>
            ))}
          </ul>
        </div>
      )}

      {characterStatus.spellbook && characterStatus.spellbook.length > 0 && (
        <div className="status__block">
          <h3>Spellbook</h3>
          <ul>
            {characterStatus.spellbook.map((spell) => (
              <li key={spell}>{spell}</li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  )
}
