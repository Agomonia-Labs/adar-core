// ui/src/scheduling/SchedulingBookingsList.jsx
// Flat, sortable table of a practice's bookings -- the list-view
// counterpart to the month-grid Calendar tab, for staff who just want to
// scan/filter appointments (by status, provider, date range) rather than
// click through a calendar. Same read endpoint as the Calendar tab
// (GET /admin/scheduling/practices/{id}/bookings) and the same cancel
// action (DELETE /admin/scheduling/appointments/{id}).

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, CircularProgress, Alert,
  Table, TableBody, TableCell, TableHead, TableRow, Select, MenuItem,
  FormControl, InputLabel, TextField, Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function addDays(d, n) { const c = new Date(d); c.setDate(c.getDate() + n); return c }

const STATUS_OPTIONS = [
  { value: 'confirmed', label: 'Confirmed' },
  { value: '', label: 'All statuses' },
  { value: 'cancelled', label: 'Cancelled' },
]

export default function SchedulingBookingsList({ token, practiceId, providers }) {
  const [rangeStart, setRangeStart] = useState(() => ymd(addDays(new Date(), -30)))
  const [rangeEnd, setRangeEnd]     = useState(() => ymd(addDays(new Date(), 60)))
  const [providerFilter, setProviderFilter] = useState('')
  const [statusFilter, setStatusFilter]     = useState('confirmed')

  const [bookings, setBookings] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [msg, setMsg]           = useState('')
  const [cancelling, setCancelling] = useState(null)

  const load = useCallback(async () => {
    if (!practiceId) return
    setLoading(true); setError('')
    try {
      const start = new Date(rangeStart + 'T00:00:00')
      const end = addDays(new Date(rangeEnd + 'T00:00:00'), 1) // inclusive of the end date
      const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })
      if (providerFilter) params.set('provider_id', providerFilter)
      if (statusFilter) params.set('status', statusFilter)
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/bookings?${params}`,
        { headers: authHeaders(token) },
      )
      setBookings(data.bookings || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load bookings')
    } finally {
      setLoading(false)
    }
  }, [token, practiceId, rangeStart, rangeEnd, providerFilter, statusFilter])

  useEffect(() => { load() }, [load])

  const sorted = useMemo(
    () => [...bookings].sort((a, b) => (a.start_time || '').localeCompare(b.start_time || '')),
    [bookings],
  )

  const confirmCancel = async () => {
    if (!cancelling) return
    setError('')
    try {
      await axios.delete(
        `${API_URL}/admin/scheduling/appointments/${cancelling.id}`,
        { headers: authHeaders(token), params: { reason: 'Cancelled by staff' } },
      )
      setMsg('✓ Appointment cancelled')
      setCancelling(null); load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to cancel appointment')
      setCancelling(null)
    }
  }

  const statusColor = (s) => (s === 'confirmed' ? 'success' : s === 'cancelled' ? 'default' : 'warning')
  const fmtDate = (iso) => new Date(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  const fmtTime = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={1}>
        <Typography variant="subtitle1" fontWeight={600}>Bookings</Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
          <TextField label="From" type="date" size="small" value={rangeStart}
            InputLabelProps={{ shrink: true }} onChange={(e) => setRangeStart(e.target.value)} sx={{ minWidth: 150 }} />
          <TextField label="To" type="date" size="small" value={rangeEnd}
            InputLabelProps={{ shrink: true }} onChange={(e) => setRangeEnd(e.target.value)} sx={{ minWidth: 150 }} />
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Provider</InputLabel>
            <Select label="Provider" value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
              <MenuItem value="">All providers</MenuItem>
              {providers.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Status</InputLabel>
            <Select label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              {STATUS_OPTIONS.map(o => <MenuItem key={o.value || 'all'} value={o.value}>{o.label}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {loading ? (
        <Box sx={{ textAlign: 'center', py: 3 }}><CircularProgress size={24} /></Box>
      ) : sorted.length === 0 ? (
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>No bookings match these filters.</Typography>
      ) : (
        <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>Time</TableCell>
                <TableCell>Patient / client</TableCell>
                <TableCell>Contact</TableCell>
                <TableCell>Provider</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sorted.map(b => (
                <TableRow key={b.id} hover>
                  <TableCell>{fmtDate(b.start_time)}</TableCell>
                  <TableCell>{fmtTime(b.start_time)}–{fmtTime(b.end_time)}</TableCell>
                  <TableCell>{b.caller_name || '—'}</TableCell>
                  <TableCell sx={{ color: 'text.secondary' }}>
                    {b.caller_phone}{b.caller_phone && b.caller_email ? ' · ' : ''}{b.caller_email}
                  </TableCell>
                  <TableCell>{b.provider_name}</TableCell>
                  <TableCell>{b.appointment_type_name}</TableCell>
                  <TableCell><Chip size="small" label={b.status} color={statusColor(b.status)} /></TableCell>
                  <TableCell align="right">
                    {b.status !== 'cancelled' && (
                      <Button size="small" color="error" sx={{ textTransform: 'none' }} onClick={() => setCancelling(b)}>
                        Cancel
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Dialog open={Boolean(cancelling)} onClose={() => setCancelling(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Cancel this appointment?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {cancelling?.caller_name}'s {cancelling?.appointment_type_name} with {cancelling?.provider_name} will be cancelled.
            {cancelling?.caller_email ? ' They’ll get a cancellation email.' : ''}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCancelling(null)}>Never mind</Button>
          <Button color="error" variant="contained" onClick={confirmCancel}>Cancel appointment</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
