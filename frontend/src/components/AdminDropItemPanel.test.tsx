import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AdminDropItemPanel } from './AdminDropItemPanel'

const deleteAdminRoomObject = vi.fn()
const dropAdminItem = vi.fn()
const fetchAdminRoomObjects = vi.fn()

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => ({
    adminToken: 'dev-admin',
    currentRoom: null,
    deleteAdminRoomObject,
    dropAdminItem,
    fetchAdminRoomObjects,
    session: { playerId: 'hero', roomId: 7, token: 'session-token' },
    world: {
      locations: [
        { id: 7, brfdes: 'at the village temple', objects: [51, 52] },
        { id: 186, brfdes: 'in a dark cave', objects: [51] },
      ],
      objects: [
        { id: 0, name: 'ruby' },
        { id: 1, name: 'emerald' },
        { id: 51, name: 'machine' },
        { id: 52, name: 'dragon' },
      ],
    },
  }),
}))

describe('AdminDropItemPanel', () => {
  beforeEach(() => {
    deleteAdminRoomObject.mockReset()
    dropAdminItem.mockReset()
    fetchAdminRoomObjects.mockReset()
    fetchAdminRoomObjects.mockResolvedValue({
      room_id: 7,
      room: { id: 7, name: 'at the village temple' },
      room_objects: [
        { id: 51, name: 'machine' },
        { id: 52, name: 'dragon' },
      ],
    })
    deleteAdminRoomObject.mockResolvedValue({
      status: 'deleted',
      room_id: 7,
      slot_index: 1,
      object: { id: 52, name: 'dragon' },
      room_objects: [{ id: 51, name: 'machine' }],
      announcement: {
        message_id: null,
        modeled_after_spell: 'mower',
        text: '***\rThe dragon at the village temple vanishes!\r',
      },
    })
    dropAdminItem.mockResolvedValue({
      status: 'dropped',
      room_id: 7,
      object: { id: 1, name: 'emerald' },
      room_objects: [{ id: 1, name: 'emerald' }],
      announcement: {
        message_id: null,
        modeled_after_message_id: 'ASHM01',
        text: '***\r\nAn emerald suddenly appears near the altar!',
      },
    })
  })

  it('defaults to the session room and drops the selected item', async () => {
    const user = userEvent.setup()
    render(<AdminDropItemPanel />)

    expect(screen.getByLabelText(/room id/i)).toHaveValue(7)
    expect(
      await screen.findByRole('spinbutton', { name: /room id \(at the village temple\)/i })
    ).toBeInTheDocument()
    const machineDelete = await screen.findByRole('button', {
      name: /delete machine from room slot 1/i,
    })
    expect(machineDelete).toHaveTextContent(/^delete$/i)
    expect(
      await screen.findByRole('button', { name: /delete dragon from room slot 2/i })
    ).toBeInTheDocument()

    await act(async () => {
      await user.selectOptions(screen.getByLabelText(/item/i), '1')
      await user.click(screen.getByRole('button', { name: /drop item/i }))
    })

    await waitFor(() => expect(dropAdminItem).toHaveBeenCalledWith(7, 1))
    expect(await screen.findByText(/dropped emerald in room 7/i)).toBeInTheDocument()
  })

  it('shows admin drop errors without clearing the selected room', async () => {
    dropAdminItem.mockRejectedValueOnce(new Error('Room is full'))
    const user = userEvent.setup()
    render(<AdminDropItemPanel />)

    await act(async () => {
      await user.selectOptions(screen.getByLabelText(/item/i), '1')
      await user.click(screen.getByRole('button', { name: /drop item/i }))
    })

    expect(await screen.findByText(/room is full/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/room id/i)).toHaveValue(7)
  })

  it('deletes one listed room object by slot', async () => {
    const user = userEvent.setup()
    render(<AdminDropItemPanel />)

    await screen.findByRole('button', { name: /delete dragon from room slot 2/i })

    await act(async () => {
      await user.click(screen.getByRole('button', { name: /delete dragon from room slot 2/i }))
    })

    await waitFor(() => expect(deleteAdminRoomObject).toHaveBeenCalledWith(7, 1, 52))
    expect(await screen.findByText(/removed dragon from room 7/i)).toBeInTheDocument()
  })

  it('updates the room name and object list while the room id changes', async () => {
    fetchAdminRoomObjects.mockResolvedValueOnce({
      room_id: 7,
      room: { id: 7, name: 'at the village temple' },
      room_objects: [
        { id: 51, name: 'machine' },
        { id: 52, name: 'dragon' },
      ],
    }).mockResolvedValueOnce({
      room_id: 186,
      room: { id: 186, name: 'in a dark cave' },
      room_objects: [{ id: 51, name: 'machine' }],
    })
    const user = userEvent.setup()
    render(<AdminDropItemPanel />)

    await screen.findByRole('spinbutton', { name: /room id \(at the village temple\)/i })

    await act(async () => {
      await user.clear(screen.getByLabelText(/room id/i))
      await user.type(screen.getByLabelText(/room id/i), '186')
    })

    expect(
      await screen.findByRole('spinbutton', { name: /room id \(in a dark cave\)/i })
    ).toBeInTheDocument()
    await waitFor(() => expect(fetchAdminRoomObjects).toHaveBeenCalledWith(186))
  })

  it('requires a room id before submitting', async () => {
    const user = userEvent.setup()
    render(<AdminDropItemPanel />)

    await act(async () => {
      await user.clear(screen.getByLabelText(/room id/i))
      await user.click(screen.getByRole('button', { name: /drop item/i }))
    })

    expect(await screen.findByText(/room id must be a whole number/i)).toBeInTheDocument()
    expect(dropAdminItem).not.toHaveBeenCalled()
  })
})
