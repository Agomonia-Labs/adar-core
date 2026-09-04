// ui/src/scheduling/SchedulingProviders.jsx
// CRUD manager for a practice's providers: name, role, which appointment
// types they offer, weekly working hours, active. Talks to
// /admin/scheduling/... (api/routes/scheduling_admin.py).

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, TextField, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow, Alert, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, Switch, FormControlLabel,
  FormGroup, Checkbox, Divider,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth'
import axios from 'axios'
import WorkingHoursEditor from './WorkingHoursEditor'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

const EMPTY = { name: '', role: '', bio: '', appointment_type_ids: [], working_hours: [] }

export default function SchedulingProviders({ token, practiceId, appointmentTypes, onViewCalendar }) {
  const [providers, setProviders] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [msg, setMsg]             = useState('')
  const [editing, setEditing]     = useState(null)
  const [saving, setSaving]       = useState(false)

  const load = useCallback(async () => {
    if (!practiceId) return
    setLoading(true); setError('')
    try {
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/providers`,
        { headers: authHeaders(token) },
      )
      setProviders(data.providers || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load providers')
    } finally {
      setLoading(false)
    }
  }, [token, practiceId])

  useEffect(() => { load() }, [load])

  const openNew  = () => setEditing({ ...EMPTY })
  const openEdit = (p) => setEditing({ ...p, appointment_type_ids: p.appointment_type_ids || [], working_hours: p.working_hours || [] })
  const close    = () => setEditing(null)

  const toggleType = (typeId) => {
    const ids = editing.appointment_type_ids || []
    setEditing({
      ...editing,
      appointment_type_ids: ids.includes(typeId) ? ids.filter(id => id !== typeId) : [...ids, typeId],
    })
  }

  const save = async () => {
    if (!editing.name?.trim()) { setError('Name is required'); return }
    setSaving(true); setError('')
    try {
      const body = {
        name: editing.name.trim(),
        role: editing.role || '',
        bio: editing.bio || '',
        appointment_type_ids: editing.appointment_type_ids || [],
        working_hours: editing.working_hours || [],
      }
      if (editing.id) {
        await axios.patch(
          `${API_URL}/admin/scheduling/providers/${editing.id}`,
          { ...body, active: editing.active !== false },
          { headers: authHeaders(token) },
        )
        setMsg('✓ Provider updated')
      } else {
        await axios.post(
          `${API_URL}/admin/scheduling/practices/${practiceId}/providers`,
          body, { headers: authHeaders(token) },
        )
        setMsg('✓ Provider created')
      }
      close(); load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (p) => {
    setError('')
    try {
      await axios.patch(
        `${API_URL}/admin/scheduling/providers/${p.id}`,
        { active: !(p.active !== false) },
        { headers: authHeaders(token) },
      )
      load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Update failed')
    }
  }

  const typeName = (id) => appointmentTypes.find(t => t.id === id)?.name || id

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="subtitle1" fontWeight={600}>Providers</Typography>
        <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={openNew}
          disabled={appointmentTypes.length === 0}>
          New provider
        </Button>
      </Stack>
      {appointmentTypes.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>Add at least one appointment type first, so you can assign it to a provider.</Alert>
      )}

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {loading ? (
        <Box sx={{ textAlign: 'center', py: 3 }}><CircularProgress size={24} /></Box>
      ) : providers.length === 0 ? (
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>No providers yet — add one to get started.</Typography>
      ) : (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Appointment types</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {providers.map((p) => (
                <TableRow key={p.id} hover>
                  <TableCell>{p.name}</TableCell>
                  <TableCell>{p.role || '—'}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} flexWrap="wrap">
                      {(p.appointment_type_ids || []).map(id => (
                        <Chip key={id} label={typeName(id)} size="small" variant="outlined" />
                      ))}
                    </Stack>
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={p.active !== false ? 'Active' : 'Hidden'} color={p.active !== false ? 'success' : 'default'} />
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => openEdit(p)} title="Edit"><EditIcon fontSize="small" /></IconButton>
                    {onViewCalendar && (
                      <IconButton size="small" onClick={() => onViewCalendar(p.id)} title="View this provider's calendar">
                        <CalendarMonthIcon fontSize="small" />
                      </IconButton>
                    )}
                    <Switch size="small" checked={p.active !== false} onChange={() => toggleActive(p)} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Dialog open={Boolean(editing)} onClose={close} maxWidth="sm" fullWidth>
        <DialogTitle>{editing?.id ? 'Edit provider' : 'New provider'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <TextField label="Name" size="small" fullWidth value={editing?.name || ''}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })} autoFocus />
            <TextField label="Role (optional)" size="small" fullWidth placeholder="e.g. Family Medicine, Stylist, Attorney"
              value={editing?.role || ''} onChange={(e) => setEditing({ ...editing, role: e.target.value })} />
            <TextField label="Bio (optional)" size="small" fullWidth multiline minRows={3}
              placeholder="Shown to callers browsing the Providers tab — background, focus areas, credentials."
              value={editing?.bio || ''} onChange={(e) => setEditing({ ...editing, bio: e.target.value })} />

            <Box>
              <Typography variant="body2" fontWeight={600} mb={0.5}>Appointment types offered</Typography>
              <FormGroup>
                {appointmentTypes.map(t => (
                  <FormControlLabel key={t.id}
                    control={
                      <Checkbox size="small"
                        checked={(editing?.appointment_type_ids || []).includes(t.id)}
                        onChange={() => toggleType(t.id)} />
                    }
                    label={<Typography variant="body2">{t.name}</Typography>}
                  />
                ))}
              </FormGroup>
            </Box>

            <Divider />

            <Box>
              <Typography variant="body2" fontWeight={600} mb={1}>Working hours</Typography>
              <WorkingHoursEditor
                value={editing?.working_hours || []}
                onChange={(wh) => setEditing({ ...editing, working_hours: wh })}
              />
            </Box>

            {editing?.id && (
              <FormControlLabel
                control={<Switch checked={editing.active !== false} onChange={(e) => setEditing({ ...editing, active: e.target.checked })} />}
                label="Active (bookable by callers)"
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
