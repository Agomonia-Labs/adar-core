// ui/src/scheduling/SchedulingOverview.jsx
// Landing tab for a practice: a few quick numbers (providers, appointment
// types, today's/this week's bookings) plus today's short agenda, so
// logging in lands somewhere more useful than an empty "Providers" table.
// Shown to both admin and practice_staff -- for practice_staff especially,
// this is the first thing they see after signing in, since AdminDashboard.jsx
// routes them straight into the Scheduling tab with nothing else visible.

import { useState, useEffect, useCallback } from 'react'
import { Box, Paper, Typography, Stack, CircularProgress, Alert, Chip } from '@mui/material'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

function startOfDay(d) { const c = new Date(d); c.setHours(0, 0, 0, 0); return c }
function addDays(d, n) { const c = new Date(d); c.setDate(c.getDate() + n); return c }

function StatCard({ label, value }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, flex: '1 1 140px', textAlign: 'center' }}>
      <Typography variant="h4" fontWeight={700}>{value}</Typography>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>{label}</Typography>
    </Paper>
  )
}

export default function SchedulingOverview({ token, practiceId, practiceName, providers, appointmentTypes }) {
  const [bookings, setBookings] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  const load = useCallback(async () => {
    if (!practiceId) return
    setLoading(true); setError('')
    try {
      const start = startOfDay(new Date())
      const end = addDays(start, 7)
      const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/bookings?${params}`,
        { headers: authHeaders(token) },
      )
      setBookings((data.bookings || []).filter(b => b.status !== 'cancelled'))
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load upcoming bookings')
    } finally {
      setLoading(false)
    }
  }, [token, practiceId])

  useEffect(() => { load() }, [load])

  const today = startOfDay(new Date())
  const tomorrow = addDays(today, 1)
  const todays = bookings.filter(b => {
    const t = new Date(b.start_time)
    return t >= today && t < tomorrow
  }).sort((a, b) => a.start_time.localeCompare(b.start_time))
  const upcomingWeek = bookings.length

  if (loading) {
    return <Box sx={{ textAlign: 'center', py: 4 }}><CircularProgress size={24} /></Box>
  }

  return (
    <Box>
      <Typography variant="subtitle1" fontWeight={600} mb={2}>
        {practiceName || 'Practice'} overview
      </Typography>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      <Stack direction="row" spacing={2} flexWrap="wrap" mb={3}>
        <StatCard label="Today's appointments" value={todays.length} />
        <StatCard label="Next 7 days" value={upcomingWeek} />
        <StatCard label="Providers" value={providers.length} />
        <StatCard label="Appointment types" value={appointmentTypes.length} />
      </Stack>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle2" fontWeight={600} mb={1.5}>Today's schedule</Typography>
        {todays.length === 0 ? (
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>Nothing on the books for today.</Typography>
        ) : (
          <Stack spacing={1}>
            {todays.map(b => (
              <Stack key={b.id} direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
                <Chip size="small" label={new Date(b.start_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })} />
                <Typography variant="body2">
                  {b.appointment_type_name} with {b.provider_name} — {b.caller_name}
                </Typography>
              </Stack>
            ))}
          </Stack>
        )}
      </Paper>
    </Box>
  )
}
