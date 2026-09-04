// ui/src/scheduling/SchedulingDirectory.jsx
// Read-only practice/provider directory for the customer-facing app's
// "Providers" tab (App.jsx, scheduling tenant only). Lets a caller browse
// what they could ask the assistant about -- which practice, which
// providers, what each one offers, and when they work -- as a page
// instead of a chat round trip. Talks to GET /api/scheduling/directory
// (api/routes/scheduling_directory.py), a read-only, any-logged-in-caller
// endpoint distinct from the admin CRUD routes.

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Typography, Avatar, Chip, Stack, CircularProgress, Alert,
  Paper, FormControl, InputLabel, Select, MenuItem,
} from '@mui/material'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const DAYS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Deterministic "dummy pic": a colored initials avatar, no real photo or
// external image service needed -- same name always renders the same
// initials + color, so it reads as a real per-provider identity rather
// than a generic silhouette.
const AVATAR_COLORS = ['#1B4B73', '#0F766E', '#B45309', '#7C3AED', '#BE185D', '#166534', '#B91C1C', '#1E40AF']

function initials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function avatarColor(name) {
  let hash = 0
  for (const ch of (name || '')) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[hash % AVATAR_COLORS.length]
}

function to12h(hhmm) {
  const [h, m] = (hhmm || '0:0').split(':').map(Number)
  const period = h >= 12 ? 'PM' : 'AM'
  const h12 = h % 12 === 0 ? 12 : h % 12
  return `${h12}:${String(m).padStart(2, '0')} ${period}`
}

// Groups working_hours [{weekday, start, end}] into a compact string like
// "Mon–Fri 9:00 AM–5:00 PM · Sat 10:00 AM–2:00 PM", merging consecutive
// days that share the exact same single range.
function formatWorkingHours(workingHours) {
  if (!workingHours || workingHours.length === 0) return 'Hours not listed'
  const byDay = Array.from({ length: 7 }, () => [])
  for (const wh of workingHours) {
    if (wh.weekday >= 0 && wh.weekday <= 6) byDay[wh.weekday].push(`${to12h(wh.start)}–${to12h(wh.end)}`)
  }
  const dayRanges = byDay.map(ranges => (ranges.length ? ranges.join(', ') : null))

  const groups = []
  let i = 0
  while (i < 7) {
    if (!dayRanges[i]) { i++; continue }
    let j = i
    while (j + 1 < 7 && dayRanges[j + 1] === dayRanges[i]) j++
    const label = j > i ? `${DAYS_SHORT[i]}–${DAYS_SHORT[j]}` : DAYS_SHORT[i]
    groups.push(`${label} ${dayRanges[i]}`)
    i = j + 1
  }
  return groups.length ? groups.join(' · ') : 'Hours not listed'
}

function ProviderCard({ provider }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, display: 'flex', gap: 2 }}>
      <Avatar sx={{ bgcolor: avatarColor(provider.name), width: 52, height: 52, fontWeight: 700, flexShrink: 0 }}>
        {initials(provider.name)}
      </Avatar>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography variant="subtitle1" fontWeight={600} noWrap>{provider.name}</Typography>
        {provider.role && (
          <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.75 }}>{provider.role}</Typography>
        )}
        {provider.bio && (
          <Typography variant="body2" sx={{ mb: 1, lineHeight: 1.5 }}>{provider.bio}</Typography>
        )}
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 0.75 }}>
          {(provider.appointment_types || []).map(t => (
            <Chip key={t.id} size="small" variant="outlined"
              label={t.duration_minutes ? `${t.name} · ${t.duration_minutes} min` : t.name} />
          ))}
          {(provider.appointment_types || []).length === 0 && (
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>No appointment types assigned</Typography>
          )}
        </Stack>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {formatWorkingHours(provider.working_hours)}
        </Typography>
      </Box>
    </Paper>
  )
}

export default function SchedulingDirectory({ token }) {
  const [practices, setPractices] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const { data } = await axios.get(`${API_URL}/api/scheduling/directory`, { headers: authHeaders(token) })
      const list = data.practices || []
      setPractices(list)
      setSelectedId(prev => (prev && list.some(p => p.id === prev)) ? prev : (list[0]?.id || ''))
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load providers')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <Box sx={{ textAlign: 'center', py: 4 }}><CircularProgress size={28} /></Box>
  }
  if (error) {
    return <Alert severity="error" sx={{ m: 2 }}>{error}</Alert>
  }
  if (practices.length === 0) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography sx={{ color: 'text.secondary' }}>No practices available right now.</Typography>
      </Box>
    )
  }

  const practice = practices.find(p => p.id === selectedId) || practices[0]

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2.5 }, maxWidth: 720, mx: 'auto' }}>
      {practices.length > 1 ? (
        <FormControl size="small" fullWidth sx={{ mb: 2 }}>
          <InputLabel>Practice</InputLabel>
          <Select label="Practice" value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            {practices.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
          </Select>
        </FormControl>
      ) : (
        <Typography variant="h6" fontWeight={600} sx={{ mb: 0.25 }}>{practice.name}</Typography>
      )}
      {practice.timezone && (
        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 2 }}>
          {practice.timezone}
        </Typography>
      )}

      {practice.providers.length === 0 ? (
        <Typography sx={{ color: 'text.secondary' }}>No providers listed for this practice yet.</Typography>
      ) : (
        <Stack spacing={1.5}>
          {practice.providers.map(p => <ProviderCard key={p.id} provider={p} />)}
        </Stack>
      )}
    </Box>
  )
}
