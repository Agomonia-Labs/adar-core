// ui/src/scheduling/SchedulingCalendar.jsx
// Month-grid calendar of confirmed/cancelled bookings for a practice, with
// a day-agenda panel for full detail. Staff/admin can also add a manual
// entry directly here (walk-in, phone call handled without the assistant)
// via POST /admin/scheduling/practices/{id}/bookings, and cancel an
// existing one via DELETE /admin/scheduling/appointments/{id} -- both new,
// admin-console-only actions (api/routes/scheduling_admin.py's
// create_booking/cancel_booking). The voice/chat assistant's own
// hold_slot/confirm_booking/cancel_appointment tools are unaffected and
// keep working the same way for callers.
//
// No calendar library — plain date math (Monday-start weeks, matching the
// ISO-week convention get_weekly_availability already uses on the backend)
// keeps this self-contained with zero new npm dependencies.

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, CircularProgress, Alert,
  IconButton, Select, MenuItem, FormControl, InputLabel, Divider, TextField,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import TodayIcon from '@mui/icons-material/Today'
import AddIcon from '@mui/icons-material/Add'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''
const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1) }
function addDays(d, n) { const c = new Date(d); c.setDate(c.getDate() + n); return c }
function addMonths(d, n) { return new Date(d.getFullYear(), d.getMonth() + n, 1) }

// Monday-start grid: the Monday on/before the 1st, through the Sunday on/after the last day.
function monthGridRange(viewDate) {
  const first = startOfMonth(viewDate)
  const firstWeekday = (first.getDay() + 6) % 7 // Mon=0..Sun=6
  const gridStart = addDays(first, -firstWeekday)
  const gridDays = []
  for (let i = 0; i < 42; i++) gridDays.push(addDays(gridStart, i))
  return gridDays
}

// datetime-local input <-> ISO with the browser's own offset (so "2pm" typed
// by the staff member means 2pm in whatever timezone their browser is in;
// the backend accepts any ISO offset and stores it tz-aware).
function localInputToIso(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toISOString()
}

const EMPTY_BOOKING = { provider_id: '', appointment_type_id: '', when: '', caller_name: '', caller_phone: '', caller_email: '', reason: '' }

export default function SchedulingCalendar({ token, practiceId, providers, appointmentTypes = [], providerFilter = '', onProviderFilterChange }) {
  const [viewDate, setViewDate]       = useState(() => startOfMonth(new Date()))
  const [selectedDate, setSelectedDate] = useState(() => ymd(new Date()))
  const [bookings, setBookings]       = useState([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState('')

  const [newBooking, setNewBooking]   = useState(null) // null=closed, {} = open
  const [savingBooking, setSavingBooking] = useState(false)
  const [cancelling, setCancelling]   = useState(null) // booking pending cancel confirm
  const [msg, setMsg]                 = useState('')

  const gridDays = useMemo(() => monthGridRange(viewDate), [viewDate])

  const load = useCallback(async () => {
    if (!practiceId) return
    setLoading(true); setError('')
    try {
      const start = gridDays[0]
      const end = addDays(gridDays[gridDays.length - 1], 1)
      const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })
      if (providerFilter) params.set('provider_id', providerFilter)
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
  }, [token, practiceId, gridDays, providerFilter])

  useEffect(() => { load() }, [load])

  const byDay = useMemo(() => {
    const map = {}
    for (const b of bookings) {
      if (!b.start_time) continue
      const key = ymd(new Date(b.start_time))
      ;(map[key] = map[key] || []).push(b)
    }
    Object.values(map).forEach(list => list.sort((a, b) => a.start_time.localeCompare(b.start_time)))
    return map
  }, [bookings])

  const today = ymd(new Date())
  const monthLabel = viewDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const selectedBookings = byDay[selectedDate] || []

  const statusColor = (s) => (s === 'confirmed' ? 'success' : s === 'cancelled' ? 'default' : 'warning')

  const openNewBooking = () => {
    // Default the picker to 9am on whatever day is currently selected, so
    // staff usually just need to adjust the hour, not re-pick the date.
    const defaultWhen = `${selectedDate}T09:00`
    setNewBooking({
      ...EMPTY_BOOKING,
      when: defaultWhen,
      provider_id: providers[0]?.id || '',
      appointment_type_id: appointmentTypes[0]?.id || '',
    })
  }
  const closeNewBooking = () => setNewBooking(null)

  const saveNewBooking = async () => {
    if (!newBooking.provider_id) { setError('Choose a provider'); return }
    if (!newBooking.appointment_type_id) { setError('Choose an appointment type'); return }
    if (!newBooking.caller_name.trim()) { setError('Patient/client name is required'); return }
    const iso = localInputToIso(newBooking.when)
    if (!iso) { setError('Choose a valid date and time'); return }
    setSavingBooking(true); setError('')
    try {
      await axios.post(
        `${API_URL}/admin/scheduling/practices/${practiceId}/bookings`,
        {
          provider_id: newBooking.provider_id,
          appointment_type_id: newBooking.appointment_type_id,
          start_time: iso,
          caller_name: newBooking.caller_name.trim(),
          caller_phone: newBooking.caller_phone.trim(),
          caller_email: newBooking.caller_email.trim(),
          reason: newBooking.reason.trim(),
        },
        { headers: authHeaders(token) },
      )
      setMsg('✓ Appointment added')
      closeNewBooking(); load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to add appointment')
    } finally {
      setSavingBooking(false)
    }
  }

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

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={1}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <IconButton size="small" onClick={() => setViewDate(addMonths(viewDate, -1))}><ChevronLeftIcon /></IconButton>
          <Typography variant="subtitle1" fontWeight={600} sx={{ minWidth: 160, textAlign: 'center' }}>{monthLabel}</Typography>
          <IconButton size="small" onClick={() => setViewDate(addMonths(viewDate, 1))}><ChevronRightIcon /></IconButton>
          <Button size="small" startIcon={<TodayIcon />} onClick={() => { setViewDate(startOfMonth(new Date())); setSelectedDate(today) }}>
            Today
          </Button>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center">
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Provider</InputLabel>
            <Select label="Provider" value={providerFilter} onChange={(e) => onProviderFilterChange?.(e.target.value)}>
              <MenuItem value="">All providers</MenuItem>
              {providers.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
            </Select>
          </FormControl>
          <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={openNewBooking}
            disabled={providers.length === 0 || appointmentTypes.length === 0}>
            New appointment
          </Button>
        </Stack>
      </Stack>

      {(providers.length === 0 || appointmentTypes.length === 0) && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Add at least one provider and one appointment type before you can add a manual booking.
        </Alert>
      )}

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Paper variant="outlined" sx={{ flex: '1 1 520px', position: 'relative', minHeight: 420 }}>
          {loading && (
            <Box sx={{ position: 'absolute', inset: 0, bgcolor: 'rgba(255,255,255,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1 }}>
              <CircularProgress size={24} />
            </Box>
          )}
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', borderBottom: '1px solid', borderColor: 'divider' }}>
            {DAY_LABELS.map(d => (
              <Box key={d} sx={{ py: 0.75, textAlign: 'center' }}>
                <Typography variant="caption" fontWeight={600} sx={{ color: 'text.secondary' }}>{d}</Typography>
              </Box>
            ))}
          </Box>
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)' }}>
            {gridDays.map((d) => {
              const key = ymd(d)
              const inMonth = d.getMonth() === viewDate.getMonth()
              const dayBookings = byDay[key] || []
              const isToday = key === today
              const isSelected = key === selectedDate
              return (
                <Box
                  key={key}
                  onClick={() => setSelectedDate(key)}
                  sx={{
                    minHeight: 84, p: 0.75, cursor: 'pointer',
                    border: '1px solid', borderColor: 'divider',
                    bgcolor: isSelected ? 'primary.main' : inMonth ? 'background.paper' : 'action.hover',
                    color: isSelected ? '#fff' : inMonth ? 'text.primary' : 'text.disabled',
                    '&:hover': { bgcolor: isSelected ? 'primary.dark' : 'action.selected' },
                  }}
                >
                  <Typography variant="caption" fontWeight={isToday ? 800 : 400}
                    sx={{ textDecoration: isToday ? 'underline' : 'none' }}>
                    {d.getDate()}
                  </Typography>
                  <Stack spacing={0.25} mt={0.25}>
                    {dayBookings.slice(0, 3).map(b => (
                      <Typography key={b.id} variant="caption" noWrap sx={{
                        fontSize: '0.65rem', bgcolor: isSelected ? 'rgba(255,255,255,0.2)' : 'action.selected',
                        borderRadius: 0.5, px: 0.5, display: 'block',
                        textDecoration: b.status === 'cancelled' ? 'line-through' : 'none',
                      }}>
                        {new Date(b.start_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })} {b.provider_name}
                      </Typography>
                    ))}
                    {dayBookings.length > 3 && (
                      <Typography variant="caption" sx={{ fontSize: '0.65rem', opacity: 0.8 }}>+{dayBookings.length - 3} more</Typography>
                    )}
                  </Stack>
                </Box>
              )
            })}
          </Box>
        </Paper>

        <Paper variant="outlined" sx={{ flex: '1 1 280px', p: 2, minHeight: 420 }}>
          <Typography variant="subtitle2" fontWeight={600} mb={1.5}>
            {new Date(selectedDate + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
          </Typography>
          {selectedBookings.length === 0 ? (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>No bookings this day.</Typography>
          ) : (
            <Stack spacing={1.5} divider={<Divider />}>
              {selectedBookings.map(b => (
                <Box key={b.id}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Typography variant="body2" fontWeight={600}>
                      {new Date(b.start_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
                      {' – '}
                      {new Date(b.end_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
                    </Typography>
                    <Chip size="small" label={b.status} color={statusColor(b.status)} />
                  </Stack>
                  <Typography variant="body2">{b.appointment_type_name} with {b.provider_name}</Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    {b.caller_name} · {b.caller_phone}{b.caller_email ? ` · ${b.caller_email}` : ''}
                  </Typography>
                  {b.reason && <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>Reason: {b.reason}</Typography>}
                  {b.status !== 'cancelled' && (
                    <Button size="small" color="error" sx={{ mt: 0.5, textTransform: 'none' }} onClick={() => setCancelling(b)}>
                      Cancel appointment
                    </Button>
                  )}
                </Box>
              ))}
            </Stack>
          )}
        </Paper>
      </Box>

      {/* New manual appointment */}
      <Dialog open={Boolean(newBooking)} onClose={closeNewBooking} maxWidth="xs" fullWidth>
        <DialogTitle>New appointment</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <FormControl size="small" fullWidth>
              <InputLabel>Provider</InputLabel>
              <Select label="Provider" value={newBooking?.provider_id || ''}
                onChange={(e) => setNewBooking({ ...newBooking, provider_id: e.target.value })}>
                {providers.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Appointment type</InputLabel>
              <Select label="Appointment type" value={newBooking?.appointment_type_id || ''}
                onChange={(e) => setNewBooking({ ...newBooking, appointment_type_id: e.target.value })}>
                {appointmentTypes.map(t => <MenuItem key={t.id} value={t.id}>{t.name} ({t.duration_minutes} min)</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="Date & time" type="datetime-local" size="small" fullWidth
              InputLabelProps={{ shrink: true }}
              value={newBooking?.when || ''}
              onChange={(e) => setNewBooking({ ...newBooking, when: e.target.value })} />
            <TextField label="Patient / client name" size="small" fullWidth value={newBooking?.caller_name || ''}
              onChange={(e) => setNewBooking({ ...newBooking, caller_name: e.target.value })} />
            <TextField label="Phone (optional)" size="small" fullWidth value={newBooking?.caller_phone || ''}
              onChange={(e) => setNewBooking({ ...newBooking, caller_phone: e.target.value })} />
            <TextField label="Email (optional — sends a confirmation)" size="small" fullWidth value={newBooking?.caller_email || ''}
              onChange={(e) => setNewBooking({ ...newBooking, caller_email: e.target.value })} />
            <TextField label="Reason / notes (optional)" size="small" fullWidth multiline minRows={2}
              value={newBooking?.reason || ''}
              onChange={(e) => setNewBooking({ ...newBooking, reason: e.target.value })} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeNewBooking}>Cancel</Button>
          <Button variant="contained" onClick={saveNewBooking} disabled={savingBooking}>
            {savingBooking ? 'Adding…' : 'Add appointment'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Cancel confirm */}
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
