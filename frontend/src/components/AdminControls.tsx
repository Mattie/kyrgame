import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { AdminPlayerRecord, AdminUpdatePayload, GameObject, useNavigator } from '../context/NavigatorContext'

const AVAILABLE_FLAGS = ['FEMALE', 'PEGASU', 'WILLOW', 'BRFSTF']
const FLAG_MASKS: Record<string, number> = {
  FEMALE: 0x00000002,
  BRFSTF: 0x00000008,
  PEGASU: 0x00000020,
  WILLOW: 0x00000040,
}
const MAX_INVENTORY_SLOTS = 6
const BIRTHSTONE_SLOTS = 4
const storageKeys = {
  panelCollapsed: 'kyrgame.navigator.adminPanelCollapsed',
  sections: {
    target: 'kyrgame.navigator.adminSection.target',
    identity: 'kyrgame.navigator.adminSection.identity',
    stats: 'kyrgame.navigator.adminSection.stats',
    inventory: 'kyrgame.navigator.adminSection.inventory',
    gems: 'kyrgame.navigator.adminSection.gems',
    location: 'kyrgame.navigator.adminSection.location',
  },
}

type AdminSectionKey = keyof typeof storageKeys.sections

const sectionLabels: Record<AdminSectionKey, string> = {
  target: 'Target',
  identity: 'Identity',
  stats: 'Stats & caps',
  inventory: 'Inventory',
  gems: 'Gems & stump',
  location: 'Location & spouse',
}

const parseNumber = (value: string): number | undefined => {
  const trimmed = value.trim()
  if (trimmed === '') return undefined
  const parsed = Number(trimmed)
  return Number.isNaN(parsed) ? undefined : parsed
}

const readStoredBool = (key: string) => localStorage.getItem(key) === 'true'

const resolveObjectReference = (
  value: string,
  objectsById: Map<number, GameObject>,
  objectsByName: Map<string, GameObject>
): number | null | undefined => {
  const trimmed = value.trim()
  if (!trimmed) return null
  const numeric = Number(trimmed)
  if (!Number.isNaN(numeric) && objectsById.has(numeric)) {
    return numeric
  }
  const byName = objectsByName.get(trimmed.toLowerCase())
  if (byName) {
    return byName.id
  }
  return undefined
}

export const AdminControls = () => {
  const { session, adminToken, applyAdminUpdate, fetchAdminPlayer, world } = useNavigator()
  const [panelCollapsed, setPanelCollapsed] = useState(() => readStoredBool(storageKeys.panelCollapsed))
  const [sectionCollapsed, setSectionCollapsed] = useState<Record<AdminSectionKey, boolean>>(() => ({
    target: readStoredBool(storageKeys.sections.target),
    identity: readStoredBool(storageKeys.sections.identity),
    stats: readStoredBool(storageKeys.sections.stats),
    inventory: readStoredBool(storageKeys.sections.inventory),
    gems: readStoredBool(storageKeys.sections.gems),
    location: readStoredBool(storageKeys.sections.location),
  }))
  const [playerId, setPlayerId] = useState(session?.playerId ?? '')
  const [alternateName, setAlternateName] = useState('')
  const [attireName, setAttireName] = useState('')
  const [flags, setFlags] = useState<Set<string>>(new Set())
  const [flagsInitialized, setFlagsInitialized] = useState(false)
  const [level, setLevel] = useState('')
  const [gold, setGold] = useState('')
  const [spellPoints, setSpellPoints] = useState('')
  const [hitPoints, setHitPoints] = useState('')
  const [goldCap, setGoldCap] = useState('')
  const [spellCap, setSpellCap] = useState('')
  const [hitCap, setHitCap] = useState('')
  const [inventoryCount, setInventoryCount] = useState('')
  const [inventorySlots, setInventorySlots] = useState<string[]>(
    Array.from({ length: MAX_INVENTORY_SLOTS }, () => '')
  )
  const [gemIndex, setGemIndex] = useState('')
  const [birthstones, setBirthstones] = useState<string[]>(
    Array.from({ length: BIRTHSTONE_SLOTS }, () => '')
  )
  const [stumpIndex, setStumpIndex] = useState('')
  const [location, setLocation] = useState('')
  const [spouse, setSpouse] = useState('')
  const [clearSpouse, setClearSpouse] = useState(false)
  const [loadedPlayerId, setLoadedPlayerId] = useState<string | null>(null)
  const [loadingPlayer, setLoadingPlayer] = useState(false)
  const [loadedPlayer, setLoadedPlayer] = useState<AdminPlayerRecord | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (session?.playerId) {
      setPlayerId(session.playerId)
    }
  }, [session?.playerId])

  const toggleFlag = (flag: string) => {
    setFlagsInitialized(true)
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

  const togglePanel = () => {
    setPanelCollapsed((prev) => {
      const next = !prev
      localStorage.setItem(storageKeys.panelCollapsed, String(next))
      return next
    })
  }

  const toggleSection = (key: AdminSectionKey) => {
    setSectionCollapsed((prev) => {
      const next = { ...prev, [key]: !prev[key] }
      localStorage.setItem(storageKeys.sections[key], String(next[key]))
      return next
    })
  }

  const objectCatalog = useMemo(() => {
    const objects = world?.objects ?? []
    const byId = new Map<number, GameObject>()
    const byName = new Map<string, GameObject>()
    objects.forEach((obj) => {
      byId.set(obj.id, obj)
      byName.set(obj.name.toLowerCase(), obj)
    })
    return { objects, byId, byName }
  }, [world?.objects])

  const disabled = useMemo(() => !adminToken || playerId.trim() === '', [adminToken, playerId])

  const resolveObjectLabel = useCallback(
    (id: number) => objectCatalog.byId.get(id)?.name ?? String(id),
    [objectCatalog.byId]
  )

  const hydrateFromPlayer = useCallback(
    (player: AdminPlayerRecord) => {
      setAlternateName(player.altnam ?? '')
      setAttireName(player.attnam ?? '')
      const nextFlags = new Set(
        AVAILABLE_FLAGS.filter((flag) => (player.flags ?? 0) & (FLAG_MASKS[flag] ?? 0))
      )
      setFlags(nextFlags)
      setFlagsInitialized(true)
      setLevel(String(player.level ?? ''))
      setGold(String(player.gold ?? ''))
      setSpellPoints(String(player.spts ?? ''))
      setHitPoints(String(player.hitpts ?? ''))
      setInventoryCount(String(player.npobjs ?? ''))
      const nextInventorySlots = Array.from({ length: MAX_INVENTORY_SLOTS }, (_, index) =>
        player.gpobjs?.[index] !== undefined ? resolveObjectLabel(player.gpobjs[index]) : ''
      )
      setInventorySlots(nextInventorySlots)
      setGemIndex(player.gemidx === null || player.gemidx === undefined ? '' : String(player.gemidx))
      const nextBirthstones = Array.from({ length: BIRTHSTONE_SLOTS }, (_, index) =>
        player.stones?.[index] !== undefined ? resolveObjectLabel(player.stones[index]) : ''
      )
      setBirthstones(nextBirthstones)
      setStumpIndex(player.stumpi === null || player.stumpi === undefined ? '' : String(player.stumpi))
      setLocation(String(player.gamloc ?? ''))
      setSpouse(player.spouse ?? '')
      setClearSpouse(false)
    },
    [resolveObjectLabel]
  )

  const loadAdminPlayer = useCallback(
    async (overrideId?: string) => {
      const targetId = (overrideId ?? playerId).trim()
      if (!adminToken || targetId === '') {
        setError('Admin token and player id are required to refresh player data')
        return
      }
      setLoadingPlayer(true)
      setStatus(null)
      setError(null)
      try {
        const player = await fetchAdminPlayer(targetId)
        hydrateFromPlayer(player)
        setLoadedPlayer(player)
        setLoadedPlayerId(targetId)
        setStatus('Admin data refreshed')
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to refresh admin data')
      } finally {
        setLoadingPlayer(false)
      }
    },
    [adminToken, fetchAdminPlayer, hydrateFromPlayer, playerId]
  )

  useEffect(() => {
    const trimmed = playerId.trim()
    if (!trimmed || !adminToken) {
      return
    }
    if (loadedPlayerId !== trimmed) {
      loadAdminPlayer(trimmed)
    }
  }, [adminToken, loadAdminPlayer, loadedPlayerId, playerId])

  useEffect(() => {
    if (!loadedPlayer) return
    hydrateFromPlayer(loadedPlayer)
  }, [hydrateFromPlayer, loadedPlayer, objectCatalog.byId])

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
    if (flagsInitialized) payload.flags = Array.from(flags)

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

    const parsedInventoryCount = parseNumber(inventoryCount)
    if (parsedInventoryCount !== undefined) {
      if (parsedInventoryCount < 0 || parsedInventoryCount > MAX_INVENTORY_SLOTS) {
        setError(`Inventory count must be between 0 and ${MAX_INVENTORY_SLOTS}`)
        return
      }
    }

    const hasInventorySlots = inventorySlots.some((slot) => slot.trim() !== '')
    if (hasInventorySlots) {
      const resolvedSlots = inventorySlots.map((slot) =>
        resolveObjectReference(slot, objectCatalog.byId, objectCatalog.byName)
      )
      if (resolvedSlots.some((slot) => slot === undefined)) {
        setError('Inventory slots must match a catalog object name or id.')
        return
      }
      const normalizedSlots = resolvedSlots as Array<number | null>
      let seenEmpty = false
      for (const slot of normalizedSlots) {
        if (slot === null) {
          seenEmpty = true
        } else if (seenEmpty) {
          setError('Inventory slots must be contiguous from slot 1 onward.')
          return
        }
      }
      const filledSlots = normalizedSlots.filter((slot): slot is number => slot !== null)
      if (parsedInventoryCount !== undefined && parsedInventoryCount !== filledSlots.length) {
        setError('Inventory count must match the number of filled slots.')
        return
      }
      payload.gpobjs = normalizedSlots
      payload.npobjs = parsedInventoryCount ?? filledSlots.length
    } else if (parsedInventoryCount !== undefined) {
      payload.npobjs = parsedInventoryCount
    }

    const hasBirthstones = birthstones.some((stone) => stone.trim() !== '')
    if (hasBirthstones) {
      const resolvedStones = birthstones.map((stone) =>
        resolveObjectReference(stone, objectCatalog.byId, objectCatalog.byName)
      )
      if (resolvedStones.some((stone) => stone === undefined)) {
        setError('Birthstones must match a catalog object name or id.')
        return
      }
      if (resolvedStones.some((stone) => stone === null)) {
        setError(`Provide ${BIRTHSTONE_SLOTS} birthstones or leave all blank.`)
        return
      }
      payload.stones = resolvedStones as number[]
    }

    const parsedGemIndex = parseNumber(gemIndex)
    if (parsedGemIndex !== undefined) payload.gemidx = parsedGemIndex

    const parsedStumpIndex = parseNumber(stumpIndex)
    if (parsedStumpIndex !== undefined) payload.stumpi = parsedStumpIndex

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
    <section className={`panel admin-controls ${panelCollapsed ? 'collapsed' : ''}`}>
      <header className="panel-header">
        <div>
          <p className="eyebrow">Admin tools</p>
          <h2>Admin controls</h2>
          <p className="muted">Edit player identity, stats, and placement with legacy-safe caps.</p>
        </div>
        <button
          type="button"
          className="panel-toggle"
          aria-label={`${panelCollapsed ? 'Expand' : 'Collapse'} admin panel`}
          aria-expanded={!panelCollapsed}
          onClick={togglePanel}
        >
          {panelCollapsed ? 'Expand' : 'Collapse'}
        </button>
      </header>
      {!panelCollapsed && (
        <div className="panel-body" data-testid="admin-panel-body">
          {!adminToken && (
            <p className="status error">
              Admin access is locked. Enable an admin session and set KYRGAME_ADMIN_TOKEN in backend/.env.
            </p>
          )}
          <form onSubmit={handleSubmit} className="admin-form">
            <div className="admin-grid">
              <fieldset className={`admin-section ${sectionCollapsed.target ? 'collapsed' : ''}`}>
                <legend>
                  <span>{sectionLabels.target}</span>
                  <button
                    type="button"
                    className="section-toggle"
                    aria-label={`${sectionCollapsed.target ? 'Expand' : 'Collapse'} target section`}
                    aria-expanded={!sectionCollapsed.target}
                    onClick={() => toggleSection('target')}
                  >
                    {sectionCollapsed.target ? 'Expand' : 'Collapse'}
                  </button>
                </legend>
                {!sectionCollapsed.target && (
                  <div className="admin-section-body" data-testid="admin-section-body-target">
                    <div className="field">
                      <label htmlFor="admin-player-id">Target player</label>
                      <input
                        id="admin-player-id"
                        name="admin-player-id"
                        value={playerId}
                        onChange={(event) => setPlayerId(event.target.value)}
                      />
                      <p className="field-hint">Player ID or alias to update.</p>
                    </div>
                  </div>
                )}
              </fieldset>

              <fieldset className={`admin-section ${sectionCollapsed.identity ? 'collapsed' : ''}`}>
                <legend>
                  <span>{sectionLabels.identity}</span>
                  <button
                    type="button"
                    className="section-toggle"
                    aria-label={`${sectionCollapsed.identity ? 'Expand' : 'Collapse'} identity section`}
                    aria-expanded={!sectionCollapsed.identity}
                    onClick={() => toggleSection('identity')}
                  >
                    {sectionCollapsed.identity ? 'Expand' : 'Collapse'}
                  </button>
                </legend>
                {!sectionCollapsed.identity && (
                  <div className="admin-section-body" data-testid="admin-section-body-identity">
                    <div className="admin-fields">
                      <div className="field">
                        <label htmlFor="alternate-name">Alternate name</label>
                        <input
                          id="alternate-name"
                          name="alternate-name"
                          value={alternateName}
                          onChange={(event) => setAlternateName(event.target.value)}
                        />
                        <p className="field-hint">Shown in APPEAR (legacy uppercases).</p>
                      </div>
                      <div className="field">
                        <label htmlFor="attire-name">Attire name</label>
                        <input
                          id="attire-name"
                          name="attire-name"
                          value={attireName}
                          onChange={(event) => setAttireName(event.target.value)}
                        />
                        <p className="field-hint">Used in LOOK descriptions.</p>
                      </div>
                    </div>
                    <div className="admin-flags">
                      <p className="field-label">Appearance flags</p>
                      <div className="flag-grid">
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
                      </div>
                    </div>
                  </div>
                )}
              </fieldset>

              <fieldset className={`admin-section ${sectionCollapsed.stats ? 'collapsed' : ''}`}>
                <legend>
                  <span>{sectionLabels.stats}</span>
                  <button
                    type="button"
                    className="section-toggle"
                    aria-label={`${sectionCollapsed.stats ? 'Expand' : 'Collapse'} stats section`}
                    aria-expanded={!sectionCollapsed.stats}
                    onClick={() => toggleSection('stats')}
                  >
                    {sectionCollapsed.stats ? 'Expand' : 'Collapse'}
                  </button>
                </legend>
                {!sectionCollapsed.stats && (
                  <div className="admin-section-body" data-testid="admin-section-body-stats">
                    <div className="admin-fields">
                      <div className="field">
                        <label htmlFor="level">Level</label>
                        <input
                          id="level"
                          name="level"
                          type="number"
                          value={level}
                          onChange={(event) => setLevel(event.target.value)}
                        />
                        <p className="field-hint">Updates derived HP/SP caps.</p>
                      </div>
                      <div className="field">
                        <label htmlFor="hitpts">Hit points</label>
                        <input
                          id="hitpts"
                          name="hitpts"
                          type="number"
                          value={hitPoints}
                          onChange={(event) => setHitPoints(event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="spts">Spell points</label>
                        <input
                          id="spts"
                          name="spts"
                          type="number"
                          value={spellPoints}
                          onChange={(event) => setSpellPoints(event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="gold">Gold</label>
                        <input
                          id="gold"
                          name="gold"
                          type="number"
                          value={gold}
                          onChange={(event) => setGold(event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="gold-cap">Gold cap</label>
                        <input
                          id="gold-cap"
                          name="gold-cap"
                          type="number"
                          value={goldCap}
                          onChange={(event) => setGoldCap(event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="hp-cap">HP cap</label>
                        <input
                          id="hp-cap"
                          name="hp-cap"
                          type="number"
                          value={hitCap}
                          onChange={(event) => setHitCap(event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="sp-cap">SP cap</label>
                        <input
                          id="sp-cap"
                          name="sp-cap"
                          type="number"
                          value={spellCap}
                          onChange={(event) => setSpellCap(event.target.value)}
                        />
                      </div>
                    </div>
                  </div>
                )}
              </fieldset>

              <fieldset className={`admin-section ${sectionCollapsed.inventory ? 'collapsed' : ''}`}>
                <legend>
                  <span>{sectionLabels.inventory}</span>
                  <button
                    type="button"
                    className="section-toggle"
                    aria-label={`${sectionCollapsed.inventory ? 'Expand' : 'Collapse'} inventory section`}
                    aria-expanded={!sectionCollapsed.inventory}
                    onClick={() => toggleSection('inventory')}
                  >
                    {sectionCollapsed.inventory ? 'Expand' : 'Collapse'}
                  </button>
                </legend>
                {!sectionCollapsed.inventory && (
                  <div className="admin-section-body" data-testid="admin-section-body-inventory">
                    <div className="admin-fields">
                      <div className="field">
                        <label htmlFor="inventory-count">Inventory count</label>
                        <input
                          id="inventory-count"
                          name="inventory-count"
                          type="number"
                          min={0}
                          max={MAX_INVENTORY_SLOTS}
                          value={inventoryCount}
                          onChange={(event) => setInventoryCount(event.target.value)}
                        />
                        <p className="field-hint">Max {MAX_INVENTORY_SLOTS} items (matches MXPOBS).</p>
                      </div>
                    </div>
                    <div className="admin-slot-grid">
                      {inventorySlots.map((slot, index) => (
                        <div className="field" key={`inventory-slot-${index}`}>
                          <label htmlFor={`inventory-slot-${index}`}>Inventory slot {index + 1}</label>
                          <input
                            id={`inventory-slot-${index}`}
                            name={`inventory-slot-${index}`}
                            list="inventory-object-options"
                            value={slot}
                            onChange={(event) =>
                              setInventorySlots((prev) => {
                                const next = [...prev]
                                next[index] = event.target.value
                                return next
                              })
                            }
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </fieldset>

              <fieldset className={`admin-section ${sectionCollapsed.gems ? 'collapsed' : ''}`}>
                <legend>
                  <span>{sectionLabels.gems}</span>
                  <button
                    type="button"
                    className="section-toggle"
                    aria-label={`${sectionCollapsed.gems ? 'Expand' : 'Collapse'} gems section`}
                    aria-expanded={!sectionCollapsed.gems}
                    onClick={() => toggleSection('gems')}
                  >
                    {sectionCollapsed.gems ? 'Expand' : 'Collapse'}
                  </button>
                </legend>
                {!sectionCollapsed.gems && (
                  <div className="admin-section-body" data-testid="admin-section-body-gems">
                    <div className="admin-fields">
                      <div className="field">
                        <label htmlFor="gem-index">Gem index</label>
                        <input
                          id="gem-index"
                          name="gem-index"
                          type="number"
                          min={0}
                          max={BIRTHSTONE_SLOTS}
                          value={gemIndex}
                          onChange={(event) => setGemIndex(event.target.value)}
                        />
                        <p className="field-hint">Birthstone progress (0-{BIRTHSTONE_SLOTS}).</p>
                      </div>
                      <div className="field">
                        <label htmlFor="stump-index">Stump index</label>
                        <input
                          id="stump-index"
                          name="stump-index"
                          type="number"
                          min={0}
                          max={12}
                          value={stumpIndex}
                          onChange={(event) => setStumpIndex(event.target.value)}
                        />
                        <p className="field-hint">Chamber of the Mind progress (0-12).</p>
                      </div>
                    </div>
                    <div className="admin-slot-grid">
                      {birthstones.map((stone, index) => (
                        <div className="field" key={`birthstone-${index}`}>
                          <label htmlFor={`birthstone-${index}`}>Birthstone {index + 1}</label>
                          <input
                            id={`birthstone-${index}`}
                            name={`birthstone-${index}`}
                            list="inventory-object-options"
                            value={stone}
                            onChange={(event) =>
                              setBirthstones((prev) => {
                                const next = [...prev]
                                next[index] = event.target.value
                                return next
                              })
                            }
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </fieldset>

              <fieldset className={`admin-section ${sectionCollapsed.location ? 'collapsed' : ''}`}>
                <legend>
                  <span>{sectionLabels.location}</span>
                  <button
                    type="button"
                    className="section-toggle"
                    aria-label={`${sectionCollapsed.location ? 'Expand' : 'Collapse'} location section`}
                    aria-expanded={!sectionCollapsed.location}
                    onClick={() => toggleSection('location')}
                  >
                    {sectionCollapsed.location ? 'Expand' : 'Collapse'}
                  </button>
                </legend>
                {!sectionCollapsed.location && (
                  <div className="admin-section-body" data-testid="admin-section-body-location">
                    <div className="admin-fields">
                      <div className="field">
                        <label htmlFor="teleport">Teleport room</label>
                        <input
                          id="teleport"
                          name="teleport"
                          type="number"
                          value={location}
                          onChange={(event) => setLocation(event.target.value)}
                        />
                        <p className="field-hint">
                          Updates stored gamloc/pgploc; active sessions must reconnect.
                        </p>
                      </div>
                      <div className="field">
                        <label htmlFor="spouse">Spouse</label>
                        <input
                          id="spouse"
                          name="spouse"
                          value={spouse}
                          onChange={(event) => setSpouse(event.target.value)}
                          disabled={clearSpouse}
                        />
                        <p className="field-hint">Leave blank to keep current spouse.</p>
                      </div>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          name="clear-spouse"
                          checked={clearSpouse}
                          onChange={(event) => setClearSpouse(event.target.checked)}
                        />
                        Clear spouse
                      </label>
                    </div>
                  </div>
                )}
              </fieldset>
            </div>

            <div className="admin-actions">
              <button type="button" onClick={() => loadAdminPlayer()} disabled={disabled || loadingPlayer}>
                {loadingPlayer ? 'Refreshing...' : 'Refresh admin data'}
              </button>
              <button type="submit" disabled={disabled}>
                Apply admin changes
              </button>
            </div>
          </form>
          <datalist id="inventory-object-options">
            {objectCatalog.objects.flatMap((obj) => [
              <option key={`${obj.id}-name`} value={obj.name}>
                {obj.id}
              </option>,
              <option key={`${obj.id}-id`} value={`${obj.id}`}>
                {obj.name}
              </option>,
            ])}
          </datalist>
          {status && <p className="status success">{status}</p>}
          {error && <p className="status error">{error}</p>}
        </div>
      )}
    </section>
  )
}
