import { FormEvent, useEffect, useMemo, useState } from 'react'

import type { AdminRoomObjectEntry } from '../context/NavigatorContext'
import { useNavigator } from '../context/NavigatorContext'

export const AdminDropItemPanel = () => {
  const {
    adminToken,
    currentRoom,
    deleteAdminRoomObject,
    dropAdminItem,
    fetchAdminRoomObjects,
    session,
    world,
  } = useNavigator()
  const defaultRoom = currentRoom ?? session?.roomId ?? 0
  const [roomId, setRoomId] = useState(String(defaultRoom))
  const [objectRef, setObjectRef] = useState('')
  const [dropping, setDropping] = useState(false)
  const [deletingSlot, setDeletingSlot] = useState<number | null>(null)
  const [loadingRoomObjects, setLoadingRoomObjects] = useState(false)
  const [roomObjects, setRoomObjects] = useState<AdminRoomObjectEntry[]>([])
  const [fetchedRoom, setFetchedRoom] = useState<{ id: number; name?: string | null } | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const objects = useMemo(() => world?.objects ?? [], [world?.objects])
  const locations = useMemo(() => world?.locations ?? [], [world?.locations])
  const parsedRoom = Number(roomId)
  const selectedRoomId =
    roomId.trim() !== '' && Number.isInteger(parsedRoom) ? parsedRoom : null
  const selectedLocation = useMemo(
    () => locations.find((location) => location.id === selectedRoomId) ?? null,
    [locations, selectedRoomId]
  )
  const selectedRoomName =
    fetchedRoom?.id === selectedRoomId ? fetchedRoom.name : selectedLocation?.brfdes
  const objectNamesById = useMemo(
    () => new Map(objects.map((obj) => [obj.id, obj.name])),
    [objects]
  )

  useEffect(() => {
    setRoomId(String(defaultRoom))
  }, [defaultRoom])

  useEffect(() => {
    if (objects.length === 0) {
      setObjectRef('')
      return
    }
    if (!objects.some((obj) => String(obj.id) === objectRef)) {
      setObjectRef(String(objects[0].id))
    }
  }, [objectRef, objects])

  useEffect(() => {
    if (!adminToken || selectedRoomId === null) {
      setRoomObjects([])
      setFetchedRoom(null)
      return
    }

    let cancelled = false
    setLoadingRoomObjects(true)
    fetchAdminRoomObjects(selectedRoomId)
      .then((result) => {
        if (cancelled) return
        setFetchedRoom(result.room)
        setRoomObjects(result.room_objects)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setRoomObjects([])
        setError(err instanceof Error ? err.message : 'Unable to load room items')
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingRoomObjects(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [adminToken, fetchAdminRoomObjects, selectedRoomId])

  if (!adminToken) return null

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const trimmedRoomId = roomId.trim()
    const parsedObject = Number(objectRef)
    if (!trimmedRoomId || selectedRoomId === null) {
      setError('Room ID must be a whole number')
      setStatus(null)
      return
    }
    if (!Number.isInteger(parsedObject)) {
      setError('Select an item to drop')
      setStatus(null)
      return
    }

    setDropping(true)
    setError(null)
    setStatus(null)
    try {
      const result = await dropAdminItem(selectedRoomId, parsedObject)
      setRoomObjects(result.room_objects.map((obj) => (
        typeof obj === 'number' ? { id: obj, name: objectNamesById.get(obj) } : obj
      )))
      setStatus(`Dropped ${result.object.name} in room ${result.room_id}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to drop item')
    } finally {
      setDropping(false)
    }
  }

  const handleDelete = async (slotIndex: number, expectedObjectId: number) => {
    if (selectedRoomId === null) {
      setError('Room ID must be a whole number')
      setStatus(null)
      return
    }

    setDeletingSlot(slotIndex)
    setError(null)
    setStatus(null)
    try {
      const result = await deleteAdminRoomObject(selectedRoomId, slotIndex, expectedObjectId)
      setRoomObjects(result.room_objects)
      setStatus(`Removed ${result.object.name} from room ${result.room_id}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to remove room item')
    } finally {
      setDeletingSlot(null)
    }
  }

  return (
    <section className="panel admin-drop-panel">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Admin only</p>
          <h2>Item drop</h2>
          <p className="muted">Place a catalog item into a live room.</p>
        </div>
      </header>

      <form className="admin-drop-form" onSubmit={handleSubmit}>
        <div className="admin-fields">
          <div className="field">
            <label htmlFor="admin-drop-item">Item</label>
            <select
              id="admin-drop-item"
              name="admin-drop-item"
              value={objectRef}
              onChange={(event) => setObjectRef(event.target.value)}
            >
              {objects.map((obj) => (
                <option key={obj.id} value={obj.id}>
                  {obj.name} ({obj.id})
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="admin-drop-room">
              Room ID{selectedRoomName ? ` (${selectedRoomName})` : ''}
            </label>
            <input
              id="admin-drop-room"
              name="admin-drop-room"
              list="admin-drop-room-options"
              type="number"
              value={roomId}
              onChange={(event) => setRoomId(event.target.value)}
            />
            <datalist id="admin-drop-room-options">
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.brfdes}
                </option>
              ))}
            </datalist>
          </div>
        </div>
        <div className="admin-drop-actions">
          <button type="submit" disabled={dropping || objects.length === 0}>
            {dropping ? 'Dropping...' : 'Drop item'}
          </button>
        </div>
      </form>

      <div className="admin-room-objects" aria-live="polite">
        <h3>Current room items</h3>
        {loadingRoomObjects ? (
          <p className="muted">Loading room items...</p>
        ) : roomObjects.length === 0 ? (
          <p className="muted">No items in this room.</p>
        ) : (
          <ul>
            {roomObjects.map((obj, index) => {
              const name = obj.name ?? objectNamesById.get(obj.id) ?? `object ${obj.id}`
              return (
                <li key={`${obj.id}-${index}`}>
                  <span>
                    {name} ({obj.id})
                  </span>
                  <button
                    type="button"
                    className="admin-room-object-remove"
                    aria-label={`Delete ${name} from room slot ${index + 1}`}
                    disabled={deletingSlot !== null}
                    onClick={() => void handleDelete(index, obj.id)}
                  >
                    Delete
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {status && <p className="status success">{status}</p>}
      {error && <p className="status error">{error}</p>}
    </section>
  )
}
