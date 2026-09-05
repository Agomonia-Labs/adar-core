// ui/src/scheduling/SchedulingAdmin.jsx
// Top-level "Scheduling" admin tab: pick/create a practice, then manage its
// providers, appointment types, and view its bookings calendar. Rendered
// from AdminDashboard.jsx only when tenant.id === 'scheduling'. Every
// change here takes effect immediately for the live voice/chat assistant
// too, since availability is always computed live against current
// Firestore state (see domains/scheduling/tools/availability_tools.py).

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, TextField, CircularProgress,
  Alert, Dialog, DialogTitle, DialogContent, DialogActions, MenuItem, Select,
  FormControl, InputLabel, Switch, FormControlLabel,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import axios from 'axios'
import SchedulingProviders from './SchedulingProviders'
import SchedulingAppointmentTypes from './SchedulingAppointmentTypes'
import SchedulingCalendar from './SchedulingCalendar'
import SchedulingStaff from './SchedulingStaff'
import SchedulingOverview from './SchedulingOverview'
import SchedulingBookingsList from './SchedulingBookingsList'
import SchedulingTraces from './SchedulingTraces'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

const EMPTY_PRACTICE = { name: '', timezone: 'America/New_York', lead_time_minutes: 120, max_advance_days: 60 }

const SUB_TABS = [
  { key: 'overview',          label: '📊 Overview' },
  { key: 'providers',         label: '👥 Providers' },
  { key: 'appointment-types', label: '🏷️ Appointment types' },
  { key: 'calendar',          label: '📅 Calendar' },
  { key: 'bookings',          label: '📋 Bookings' },
  { key: 'traces',            label: '🔍 Traces' },
]

// Staff-login management is admin-only on the backend (get_admin on all
// three .../staff endpoints in scheduling_admin.py) -- a practice_staff
// login would just get 403s, so the tab is hidden for it entirely rather
// than shown-then-erroring.
const STAFF_TAB = { key: 'staff', label: '🔑 Staff logins' }

export default function SchedulingAdmin({ token }) {
  // A practice-scoped scheduling staff login (role="practice_staff" — see
  // api/routes/scheduling_admin.py) can only ever see its own practice_id:
  // list-all (GET /practices) is admin-only on the backend and would 403,
  // so this component fetches just that one practice instead and never
  // offers to create another. Everything below this point (providers,
  // appointment types, calendar) already scopes correctly by practiceId,
  // since those endpoints enforce the same practice_id check server-side.
  const isPracticeStaff = localStorage.getItem('adar_role') === 'practice_staff'
  const myPracticeId    = localStorage.getItem('adar_practice_id') || ''

  const [practices, setPractices]           = useState([])
  const [practicesLoading, setPracticesLoading] = useState(true)
  const [selectedId, setSelectedId]         = useState('')
  const [subTab, setSubTab]                 = useState('overview')
  const [calendarProviderFilter, setCalendarProviderFilter] = useState('')
  const [error, setError]                   = useState('')
  const [msg, setMsg]                       = useState('')

  const [practiceDialog, setPracticeDialog] = useState(null) // null=closed, {}=new, {...}=edit
  const [savingPractice, setSavingPractice] = useState(false)

  // Lightweight read-only lists shared with child tabs (each child also
  // manages its own editable copy for its own CRUD table -- see file header).
  const [providers, setProviders]           = useState([])
  const [appointmentTypes, setAppointmentTypes] = useState([])
  const [sideDataLoading, setSideDataLoading] = useState(false)

  const loadPractices = useCallback(async () => {
    setPracticesLoading(true); setError('')
    try {
      let list
      if (isPracticeStaff) {
        const { data } = await axios.get(`${API_URL}/admin/scheduling/practices/${myPracticeId}`, { headers: authHeaders(token) })
        list = [data]
      } else {
        const { data } = await axios.get(`${API_URL}/admin/scheduling/practices`, { headers: authHeaders(token) })
        list = data.practices || []
      }
      setPractices(list)
      setSelectedId(prev => (prev && list.some(p => p.id === prev)) ? prev : (list[0]?.id || ''))
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load practices')
    } finally {
      setPracticesLoading(false)
    }
  }, [token, isPracticeStaff, myPracticeId])

  useEffect(() => { loadPractices() }, [loadPractices])

  const loadSideData = useCallback(async () => {
    if (!selectedId) { setProviders([]); setAppointmentTypes([]); return }
    setSideDataLoading(true)
    try {
      const [provRes, typeRes] = await Promise.all([
        axios.get(`${API_URL}/admin/scheduling/practices/${selectedId}/providers`, { headers: authHeaders(token) }),
        axios.get(`${API_URL}/admin/scheduling/practices/${selectedId}/appointment-types`, { headers: authHeaders(token) }),
      ])
      setProviders(provRes.data.providers || [])
      setAppointmentTypes(typeRes.data.appointment_types || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load practice data')
    } finally {
      setSideDataLoading(false)
    }
  }, [token, selectedId])

  useEffect(() => { loadSideData() }, [loadSideData, subTab])

  const selectedPractice = practices.find(p => p.id === selectedId)

  const openNewPractice  = () => setPracticeDialog({ ...EMPTY_PRACTICE })
  const openEditPractice = () => selectedPractice && setPracticeDialog({ ...selectedPractice })
  const closePracticeDialog = () => setPracticeDialog(null)

  const savePractice = async () => {
    if (!practiceDialog.name?.trim()) { setError('Practice name is required'); return }
    setSavingPractice(true); setError('')
    try {
      if (practiceDialog.id) {
        await axios.patch(
          `${API_URL}/admin/scheduling/practices/${practiceDialog.id}`,
          {
            name: practiceDialog.name.trim(),
            timezone: practiceDialog.timezone,
            lead_time_minutes: Number(practiceDialog.lead_time_minutes) || 120,
            max_advance_days: Number(practiceDialog.max_advance_days) || 60,
            active: practiceDialog.active !== false,
          },
          { headers: authHeaders(token) },
        )
        setMsg('✓ Practice updated')
      } else {
        const { data } = await axios.post(
          `${API_URL}/admin/scheduling/practices`,
          {
            name: practiceDialog.name.trim(),
            timezone: practiceDialog.timezone,
            lead_time_minutes: Number(practiceDialog.lead_time_minutes) || 120,
            max_advance_days: Number(practiceDialog.max_advance_days) || 60,
          },
          { headers: authHeaders(token) },
        )
        setMsg(`✓ Practice "${practiceDialog.name}" created`)
        setSelectedId(data.id)
      }
      closePracticeDialog(); loadPractices()
    } catch (e) {
      setError(e.response?.data?.detail || 'Save failed')
    } finally {
      setSavingPractice(false)
    }
  }

  if (practicesLoading) {
    return <Box sx={{ textAlign: 'center', py: 4 }}><CircularProgress /></Box>
  }

  return (
    <Box>
      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      <Stack direction="row" spacing={1.5} alignItems="center" mb={2} flexWrap="wrap">
        <FormControl size="small" sx={{ minWidth: 260 }}>
          <InputLabel>Practice</InputLabel>
          <Select label="Practice" value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            {practices.map(p => (
              <MenuItem key={p.id} value={p.id}>
                {p.name}{p.active === false ? '  (hidden)' : ''}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {!isPracticeStaff && (
          <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={openNewPractice}>
            New practice
          </Button>
        )}
        {selectedPractice && (
          <Button size="small" onClick={openEditPractice}>Edit practice settings</Button>
        )}
      </Stack>

      {practices.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography sx={{ color: 'text.secondary', mb: 2 }}>
            {isPracticeStaff ? 'Could not load your practice.' : 'No practices yet. Create one to get started.'}
          </Typography>
          {!isPracticeStaff && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={openNewPractice}>New practice</Button>
          )}
        </Paper>
      ) : (
        <>
          {selectedPractice && (
            <Stack direction="row" spacing={2} mb={2} flexWrap="wrap">
              <Chip size="small" label={selectedPractice.timezone} variant="outlined" />
              <Chip size="small" label={`Lead time: ${selectedPractice.lead_time_minutes} min`} variant="outlined" />
              <Chip size="small" label={`Booking window: ${selectedPractice.max_advance_days} days`} variant="outlined" />
              <Chip size="small" label={selectedPractice.active === false ? 'Hidden from callers' : 'Live'}
                color={selectedPractice.active === false ? 'default' : 'success'} />
            </Stack>
          )}

          <Stack direction="row" spacing={1} mb={2}>
            {(isPracticeStaff ? SUB_TABS : [...SUB_TABS, STAFF_TAB]).map(t => (
              <Button key={t.key} size="small" variant={subTab === t.key ? 'contained' : 'outlined'}
                onClick={() => setSubTab(t.key)}
                sx={{ textTransform: 'none', ...(subTab === t.key ? {} : { borderColor: 'divider', color: 'text.secondary' }) }}>
                {t.label}
              </Button>
            ))}
          </Stack>

          {sideDataLoading ? (
            <Box sx={{ textAlign: 'center', py: 3 }}><CircularProgress size={24} /></Box>
          ) : (
            <>
              {subTab === 'overview' && (
                <SchedulingOverview token={token} practiceId={selectedId} practiceName={selectedPractice?.name}
                  providers={providers} appointmentTypes={appointmentTypes} />
              )}
              {subTab === 'providers' && (
                <SchedulingProviders token={token} practiceId={selectedId} appointmentTypes={appointmentTypes}
                  onViewCalendar={(providerId) => { setCalendarProviderFilter(providerId); setSubTab('calendar') }} />
              )}
              {subTab === 'appointment-types' && (
                <SchedulingAppointmentTypes token={token} practiceId={selectedId} />
              )}
              {subTab === 'calendar' && (
                <SchedulingCalendar token={token} practiceId={selectedId} providers={providers} appointmentTypes={appointmentTypes}
                  providerFilter={calendarProviderFilter} onProviderFilterChange={setCalendarProviderFilter} />
              )}
              {subTab === 'bookings' && (
                <SchedulingBookingsList token={token} practiceId={selectedId} providers={providers} />
              )}
              {subTab === 'traces' && (
                <SchedulingTraces token={token} practiceId={selectedId} />
              )}
              {subTab === 'staff' && !isPracticeStaff && (
                <SchedulingStaff token={token} practiceId={selectedId} practiceName={selectedPractice?.name} practices={practices} />
              )}
            </>
          )}
        </>
      )}

      <Dialog open={Boolean(practiceDialog)} onClose={closePracticeDialog} maxWidth="xs" fullWidth>
        <DialogTitle>{practiceDialog?.id ? 'Edit practice' : 'New practice'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <TextField label="Practice name" size="small" fullWidth value={practiceDialog?.name || ''}
              onChange={(e) => setPracticeDialog({ ...practiceDialog, name: e.target.value })} autoFocus />
            <TextField label="Timezone (IANA)" size="small" fullWidth placeholder="America/New_York"
              value={practiceDialog?.timezone || ''}
              onChange={(e) => setPracticeDialog({ ...practiceDialog, timezone: e.target.value })}
              helperText="e.g. America/New_York, America/Chicago, America/Los_Angeles" />
            <TextField label="Lead time (minutes before a booking is allowed)" type="number" size="small" fullWidth
              value={practiceDialog?.lead_time_minutes ?? 120}
              onChange={(e) => setPracticeDialog({ ...practiceDialog, lead_time_minutes: e.target.value })} />
            <TextField label="Max advance booking (days)" type="number" size="small" fullWidth
              value={practiceDialog?.max_advance_days ?? 60}
              onChange={(e) => setPracticeDialog({ ...practiceDialog, max_advance_days: e.target.value })} />
            {practiceDialog?.id && (
              <FormControlLabel
                control={<Switch checked={practiceDialog.active !== false}
                  onChange={(e) => setPracticeDialog({ ...practiceDialog, active: e.target.checked })} />}
                label="Live (visible to callers — turn off to hide without deleting anything)"
              />
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closePracticeDialog}>Cancel</Button>
          <Button variant="contained" onClick={savePractice} disabled={savingPractice}>
            {savingPractice ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
