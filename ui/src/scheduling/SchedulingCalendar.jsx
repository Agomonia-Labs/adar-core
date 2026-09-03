// ui/src/scheduling/SchedulingCalendar.jsx
// Month-grid calendar of confirmed/cancelled bookings for a practice, with
// a day-agenda panel for full detail. Read-only for now (view bookings);
// booking changes still go through the voice/chat assistant's
// cancel_appointment / reschedule_appointment tools.
//
// No calendar library — plain date math (Monday-start weeks, matching the
// ISO-week convention get_weekly_availability already uses on the backend)
// keeps this self-contained with zero new npm dependencies.

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, CircularProgress, Alert,
  IconButton, Select, MenuItem, FormControl, InputLabel, Divider,
} from '@mui/material'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import TodayIcon from '@mui/icons-material/Today'
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

export default function SchedulingCalendar({ token, practiceId, providers }) {
  const [viewDate, setViewDate]       = useState(() => startOfMonth(new Date()))
  const [selectedDate, setSelectedDate] = useState(() => ymd(new Date()))
  const [bookings, setBookings]       = useState([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState('')
  const [providerFilter, setProviderFilter] = useState('')

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
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Provider</InputLabel>
          <Select label="Provider" value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
            <MenuItem value="">All providers</MenuItem>
            {providers.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
          </Select>
        </FormControl>
      </Stack>

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
                  {b.reason && <Typography variant="caption" sx={{ color: 'text.secondary' }}>Reason: {b.reason}</Typography>}
                </Box>
              ))}
            </Stack>
          )}
        </Paper>
      </Box>
    </Box>
  )
}
