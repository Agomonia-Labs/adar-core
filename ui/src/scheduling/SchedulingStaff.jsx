// ui/src/scheduling/SchedulingStaff.jsx
// Admin-only manager for a practice's front-desk staff logins
// (role="practice_staff" — see api/routes/scheduling_admin.py's
// create_staff_account/list_staff_accounts/delete_staff_account, all
// gated by get_admin). Not rendered for a practice_staff login itself —
// those endpoints would 403 for it, since only the platform admin can
// provision or remove another login. A created account can sign in right
// away through the normal /api/auth/login + /verify-otp flow with the
// email/password set here; its JWT then carries role="practice_staff" and
// this practice's practice_id, which is what scopes it everywhere else.

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Typography, Button, Stack, TextField, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow, Alert, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, Tooltip,
  Select, MenuItem, FormControl, InputLabel,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

const EMPTY = { email: '', password: '', name: '', practice_id: '' }

function genPassword() {
  // Not security-critical to generate client-side — it's shown once to the
  // admin to hand off, and the staff member can change it after first
  // login if/when a change-password flow exists. Just needs to be usable.
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
  let out = ''
  for (let i = 0; i < 12; i++) out += chars[Math.floor(Math.random() * chars.length)]
  return out
}

export default function SchedulingStaff({ token, practiceId, practiceName, practices = [] }) {
  const [staff, setStaff]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [msg, setMsg]         = useState('')
  const [creating, setCreating] = useState(null) // null = closed, {} = open
  const [saving, setSaving]   = useState(false)
  const [created, setCreated] = useState(null)   // { email, password } — shown once after create
  const [deleting, setDeleting] = useState(null) // { team_id, email } pending confirm

  const load = useCallback(async () => {
    if (!practiceId) return
    setLoading(true); setError('')
    try {
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/staff`,
        { headers: authHeaders(token) },
      )
      setStaff(data.staff || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load staff accounts')
    } finally {
      setLoading(false)
    }
  }, [token, practiceId])

  useEffect(() => { load() }, [load])

  // Defaults to whichever practice is currently open, but any practice the
  // admin can see is selectable -- so it's explicit which practice a new
  // login belongs to, rather than implied by whatever tab happens to be open.
  const openNew = () => setCreating({ ...EMPTY, practice_id: practiceId, password: genPassword() })
  const close   = () => setCreating(null)

  const targetPracticeName = (id) => practices.find(p => p.id === id)?.name || (id === practiceId ? practiceName : '') || ''

  const save = async () => {
    const email = creating.email.trim().toLowerCase()
    if (!creating.practice_id) { setError('Choose a practice'); return }
    if (!email) { setError('Email is required'); return }
    if (!creating.password || creating.password.length < 8) { setError('Password must be at least 8 characters'); return }
    setSaving(true); setError('')
    try {
      await axios.post(
        `${API_URL}/admin/scheduling/practices/${creating.practice_id}/staff`,
        { email, password: creating.password, name: creating.name.trim() },
        { headers: authHeaders(token) },
      )
      setCreated({ email, password: creating.password, practiceName: targetPracticeName(creating.practice_id) })
      close()
      // The table below only ever shows staff for the practice currently
      // open -- only reload it if that's the practice this login was just
      // created for, otherwise leave it alone.
      if (creating.practice_id === practiceId) load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to create staff account')
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    setError('')
    try {
      await axios.delete(
        `${API_URL}/admin/scheduling/practices/${practiceId}/staff/${deleting.team_id}`,
        { headers: authHeaders(token) },
      )
      setMsg(`✓ Removed ${deleting.email}`)
      setDeleting(null); load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to remove staff account')
      setDeleting(null)
    }
  }

  const copy = (text) => { navigator.clipboard?.writeText(text) }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="subtitle1" fontWeight={600}>
          Front-desk staff logins{practiceName ? ` — ${practiceName}` : ''}
        </Typography>
        <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={openNew}>
          New staff login
        </Button>
      </Stack>

      <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
        Each login here can only see and manage this one practice — providers, appointment types, and bookings.
        It signs in the same way any account does, at the regular login screen.
      </Typography>

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {loading ? (
        <Box sx={{ textAlign: 'center', py: 3 }}><CircularProgress size={24} /></Box>
      ) : staff.length === 0 ? (
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          No staff logins yet for this practice — create one to let their front desk manage bookings directly.
        </Typography>
      ) : (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Email</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {staff.map((s) => (
                <TableRow key={s.team_id} hover>
                  <TableCell>{s.team_name || '—'}</TableCell>
                  <TableCell>{s.email}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Remove this login">
                      <IconButton size="small" onClick={() => setDeleting({ team_id: s.team_id, email: s.email })}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      {/* Create dialog */}
      <Dialog open={Boolean(creating)} onClose={close} maxWidth="xs" fullWidth>
        <DialogTitle>New staff login</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <FormControl size="small" fullWidth>
              <InputLabel>Practice</InputLabel>
              <Select label="Practice" value={creating?.practice_id || ''}
                onChange={(e) => setCreating({ ...creating, practice_id: e.target.value })}>
                {practices.length > 0 ? practices.map(p => (
                  <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>
                )) : (
                  // Fallback for the (unusual) case this renders with no
                  // practices list passed in -- still offer the practice
                  // currently open so creation isn't blocked.
                  practiceId && <MenuItem value={practiceId}>{practiceName || practiceId}</MenuItem>
                )}
              </Select>
            </FormControl>
            <TextField label="Staff / front-desk name (optional)" size="small" fullWidth
              value={creating?.name || ''}
              onChange={(e) => setCreating({ ...creating, name: e.target.value })} autoFocus />
            <TextField label="Email" type="email" size="small" fullWidth value={creating?.email || ''}
              onChange={(e) => setCreating({ ...creating, email: e.target.value })} />
            <TextField label="Password" size="small" fullWidth value={creating?.password || ''}
              onChange={(e) => setCreating({ ...creating, password: e.target.value })}
              helperText="Pre-filled with a random password — edit it, or hand this one off as-is."
              InputProps={{
                endAdornment: (
                  <Tooltip title="Copy">
                    <IconButton size="small" onClick={() => copy(creating?.password || '')}>
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                ),
              }} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={close}>Cancel</Button>
          <Button variant="contained" onClick={save} disabled={saving}>
            {saving ? 'Creating…' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Post-create credentials (shown once — password is never retrievable again) */}
      <Dialog open={Boolean(created)} onClose={() => setCreated(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Staff login created</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            Save or share this password now — it won't be shown again.
          </Alert>
          {created?.practiceName && (
            <Typography variant="body2" sx={{ mb: 2 }}>
              This login can only access <strong>{created.practiceName}</strong> — no other practice.
            </Typography>
          )}
          <Stack spacing={1.5}>
            <TextField label="Email" size="small" fullWidth value={created?.email || ''}
              InputProps={{ readOnly: true }} />
            <TextField label="Password" size="small" fullWidth value={created?.password || ''}
              InputProps={{
                readOnly: true,
                endAdornment: (
                  <Tooltip title="Copy">
                    <IconButton size="small" onClick={() => copy(created?.password || '')}>
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                ),
              }} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={() => setCreated(null)}>Done</Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirm */}
      <Dialog open={Boolean(deleting)} onClose={() => setDeleting(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Remove staff login?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {deleting?.email} will no longer be able to sign in or manage this practice. This can't be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDelete}>Remove</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
