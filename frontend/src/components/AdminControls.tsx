import { FormEvent, useEffect, useMemo, useState } from 'react'

import { AdminUpdatePayload, useNavigator } from '../context/NavigatorContext'

const AVAILABLE_FLAGS = ['FEMALE', 'PEGASU', 'WILLOW', 'BRFSTF']

const parseNumber = (value: string): number | undefined => {
  const trimmed = value.trim()
  if (trimmed === '') return undefined
  const parsed = Number(trimmed)
  return Number.isNaN(parsed) ? undefined : parsed
}

export const AdminControls = () => {
  const { session, adminToken, applyAdminUpdate } = useNavigator()
  const [playerId, setPlayerId] = useState(session?.playerId ?? '')
  const [alternateName, setAlternateName] = useState('')
  const [attireName, setAttireName] = useState('')
  const [flags, setFlags] = useState<Set<string>>(new Set())
  const [level, setLevel] = useState('')
  const [gold, setGold] = useState('')
  const [spellPoints, setSpellPoints] = useState('')
  const [hitPoints, setHitPoints] = useState('')
  const [goldCap, setGoldCap] = useState('')
  const [spellCap, setSpellCap] = useState('')
  const [hitCap, setHitCap] = useState('')
  const [location, setLocation] = useState('')
  const [spouse, setSpouse] = useState('')
  const [clearSpouse, setClearSpouse] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (session?.playerId) {
      setPlayerId(session.playerId)
    }
  }, [session?.playerId])

  const toggleFlag = (flag: string) => {
    setFlags((prev) => {
      const next = new Set(prev)
      if (next.has(flag)) {
        next.delete(flag)
      } else {
        next.add(flag)
      }
      return next
    })
  }

  const disabled = useMemo(() => !adminToken || playerId.trim() === '', [adminToken, playerId])

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setStatus(null)
    setError(null)

    if (disabled) {
      setError('Admin token and player id are required')
      return
    }

    const payload: AdminUpdatePayload = {}
    if (alternateName.trim()) payload.altnam = alternateName.trim()
    if (attireName.trim()) payload.attnam = attireName.trim()
    if (flags.size > 0) payload.flags = Array.from(flags)

    const parsedLevel = parseNumber(level)
    if (parsedLevel !== undefined) payload.level = parsedLevel

    const parsedGold = parseNumber(gold)
    if (parsedGold !== undefined) payload.gold = parsedGold
    const parsedSpellPoints = parseNumber(spellPoints)
    if (parsedSpellPoints !== undefined) payload.spts = parsedSpellPoints
    const parsedHitPoints = parseNumber(hitPoints)
    if (parsedHitPoints !== undefined) payload.hitpts = parsedHitPoints

    const parsedGoldCap = parseNumber(goldCap)
    if (parsedGoldCap !== undefined) payload.cap_gold = parsedGoldCap
    const parsedSpellCap = parseNumber(spellCap)
    if (parsedSpellCap !== undefined) payload.cap_spts = parsedSpellCap
    const parsedHitCap = parseNumber(hitCap)
    if (parsedHitCap !== undefined) payload.cap_hitpts = parsedHitCap

    const parsedLocation = parseNumber(location)
    if (parsedLocation !== undefined) {
      payload.gamloc = parsedLocation
      payload.pgploc = parsedLocation
    }

    if (clearSpouse) {
      payload.clear_spouse = true
    } else if (spouse.trim()) {
      payload.spouse = spouse.trim()
    }

    try {
      await applyAdminUpdate(playerId.trim(), payload)
      setStatus('Admin update saved')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save admin update')
    }
  }

  return (
    <section className="panel admin-controls">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Admin tools</p>
          <h2>Admin controls</h2>
          <p className="muted">Adjust player appearance, stats, and location.</p>
        </div>
      </header>
      <div className="panel-body">
        {!adminToken && <p className="status error">Provide an admin token in the session form to enable edits.</p>}
        <form onSubmit={handleSubmit}>
          <label htmlFor="admin-player-id">Player ID</label>
          <input
            id="admin-player-id"
            name="admin-player-id"
            value={playerId}
            onChange={(event) => setPlayerId(event.target.value)}
            placeholder="Player to edit"
          />

          <label htmlFor="alternate-name">Alternate name</label>
          <input
            id="alternate-name"
            name="alternate-name"
            value={alternateName}
            onChange={(event) => setAlternateName(event.target.value)}
            placeholder="APPEAR name (caps applied by legacy)"
          />

          <label htmlFor="attire-name">Attire name</label>
          <input
            id="attire-name"
            name="attire-name"
            value={attireName}
            onChange={(event) => setAttireName(event.target.value)}
            placeholder="Used by look commands"
          />

          <fieldset>
            <legend>Appearance flags</legend>
            {AVAILABLE_FLAGS.map((flag) => (
              <label className="checkbox" key={flag}>
                <input
                  type="checkbox"
                  name={`flag-${flag}`}
                  checked={flags.has(flag)}
                  onChange={() => toggleFlag(flag)}
                />
                {flag}
              </label>
            ))}
          </fieldset>

          <label htmlFor="level">Level</label>
          <input
            id="level"
            name="level"
            type="number"
            value={level}
            onChange={(event) => setLevel(event.target.value)}
            placeholder="Level sets derived HP/SP caps"
          />

          <label htmlFor="hitpts">Hit points</label>
          <input
            id="hitpts"
            name="hitpts"
            type="number"
            value={hitPoints}
            onChange={(event) => setHitPoints(event.target.value)}
            placeholder="Optional override"
          />

          <label htmlFor="spts">Spell points</label>
          <input
            id="spts"
            name="spts"
            type="number"
            value={spellPoints}
            onChange={(event) => setSpellPoints(event.target.value)}
            placeholder="Optional override"
          />

          <label htmlFor="gold">Gold</label>
          <input
            id="gold"
            name="gold"
            type="number"
            value={gold}
            onChange={(event) => setGold(event.target.value)}
            placeholder="Gold to grant or cap"
          />

          <label htmlFor="gold-cap">Gold cap</label>
          <input
            id="gold-cap"
            name="gold-cap"
            type="number"
            value={goldCap}
            onChange={(event) => setGoldCap(event.target.value)}
            placeholder="Max gold after update"
          />

          <label htmlFor="hp-cap">HP cap</label>
          <input
            id="hp-cap"
            name="hp-cap"
            type="number"
            value={hitCap}
            onChange={(event) => setHitCap(event.target.value)}
            placeholder="Cap HP (also limited by level)"
          />

          <label htmlFor="sp-cap">SP cap</label>
          <input
            id="sp-cap"
            name="sp-cap"
            type="number"
            value={spellCap}
            onChange={(event) => setSpellCap(event.target.value)}
            placeholder="Cap SP (also limited by level)"
          />

          <label htmlFor="teleport">Teleport to location</label>
          <input
            id="teleport"
            name="teleport"
            type="number"
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            placeholder="Sets gamloc/pgploc"
          />

          <label htmlFor="spouse">Spouse</label>
          <input
            id="spouse"
            name="spouse"
            value={spouse}
            onChange={(event) => setSpouse(event.target.value)}
            placeholder="Assign spouse"
            disabled={clearSpouse}
          />
          <label className="checkbox">
            <input
              type="checkbox"
              name="clear-spouse"
              checked={clearSpouse}
              onChange={(event) => setClearSpouse(event.target.checked)}
            />
            Clear spouse
          </label>

          <button type="submit" disabled={disabled}>
            Apply admin update
          </button>
        </form>
        {status && <p className="status success">{status}</p>}
        {error && <p className="status error">{error}</p>}
      </div>
    </section>
  )
}
