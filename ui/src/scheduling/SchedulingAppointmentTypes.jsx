// ui/src/scheduling/SchedulingAppointmentTypes.jsx
// CRUD manager for a practice's appointment types (name, duration, buffer,
// description, active). Talks to /admin/scheduling/... (api/routes/scheduling_admin.py).

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, TextField, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow, Alert, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, Switch, FormControlLabel,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

const EMPTY = { name: '', duration_minutes: 30, buffer_minutes: 0, description: '' }

export default function SchedulingAppointmentTypes({ token, practiceId }) {
  const [types, setTypes]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [msg, setMsg]         = useState('')
  const [editing, setEditing] = useState(null) // null = closed, {} = new, {...} = edit
  const [saving, setSaving]   = useState(false)

  const load = useCallback(async () => {
    if (!practiceId) return
    setLoading(true); setError('')
    try {
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/appointment-types`,
        { headers: authHeaders(token) },
      )
      setTypes(data.appointment_types || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load appointment types')
    } finally {
      setLoading(false)
    }
  }, [token, practiceId])

  useEffect(() => { load() }, [load])

  const openNew  = () => setEditing({ ...EMPTY })
  const openEdit = (t) => setEditing({ ...t })
  const close    = () => setEditing(null)

  const save = async () => {
    if (!editing.name?.trim()) { setError('Name is required'); return }
    setSaving(true); setError('')
    try {
      const body = {
        name: editing.name.trim(),
        duration_minutes: Number(editing.duration_minutes) || 30,
        buffer_minutes: Number(editing.buffer_minutes) || 0,
        description: editing.description || '',
      }
      if (editing.id) {
        await axios.patch(
          `${API_URL}/admin/scheduling/appointment-types/${editing.id}`,
          { ...body, active: editing.active !== false },
          { headers: authHeaders(token) },
        )
        setMsg('✓ Appointment type updated')
      } else {
        await axios.post(
          `${API_URL}/admin/scheduling/practices/${practiceId}/appointment-types`,
          body, { headers: authHeaders(token) },
        )
        setMsg('✓ Appointment type created')
      }
      close(); load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (t) => {
    setError('')
    try {
      await axios.patch(
        `${API_URL}/admin/scheduling/appointment-types/${t.id}`,
        { active: !(t.active !== false) },
        { headers: authHeaders(token) },
      )
      load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Update failed')
    }
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="subtitle1" fontWeight={600}>Appointment types</Typography>
        <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New type
        </Button>
      </Stack>

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {loading ? (
        <Box sx={{ textAlign: 'center', py: 3 }}><CircularProgress size={24} /></Box>
      ) : types.length === 0 ? (
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>No appointment types yet — add one to get started.</Typography>
      ) : (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Duration</TableCell>
                <TableCell>Buffer</TableCell>
                <TableCell>Description</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {types.map((t) => (
                <TableRow key={t.id} hover>
                  <TableCell>{t.name}</TableCell>
                  <TableCell>{t.duration_minutes} min</TableCell>
                  <TableCell>{t.buffer_minutes || 0} min</TableCell>
                  <TableCell sx={{ maxWidth: 240, color: 'text.secondary' }}>{t.description || '—'}</TableCell>
                  <TableCell>
                    <Chip size="small" label={t.active !== false ? 'Active' : 'Hidden'} color={t.active !== false ? 'success' : 'default'} />
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => openEdit(t)}><EditIcon fontSize="small" /></IconButton>
                    <Switch size="small" checked={t.active !== false} onChange={() => toggleActive(t)} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Dialog open={Boolean(editing)} onClose={close} maxWidth="xs" fullWidth>
        <DialogTitle>{editing?.id ? 'Edit appointment type' : 'New appointment type'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <TextField label="Name" size="small" fullWidth value={editing?.name || ''}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })} autoFocus />
            <TextField label="Duration (minutes)" type="number" size="small" fullWidth
              value={editing?.duration_minutes ?? 30}
              onChange={(e) => setEditing({ ...editing, duration_minutes: e.target.value })} />
            <TextField label="Buffer after (minutes)" type="number" size="small" fullWidth
              value={editing?.buffer_minutes ?? 0}
              onChange={(e) => setEditing({ ...editing, buffer_minutes: e.target.value })} />
            <TextField label="Description (optional)" size="small" fullWidth multiline minRows={2}
              value={editing?.description || ''}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
            {editing?.id && (
              <FormControlLabel
                control={<Switch checked={editing.active !== false} onChange={(e) => setEditing({ ...editing, active: e.target.checked })} />}
                label="Active (visible to callers)"
              />
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={close}>Cancel</Button>
          <Button variant="contained" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
