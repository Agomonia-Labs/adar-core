import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack,
  Table, TableBody, TableCell, TableHead, TableRow,
  Alert, CircularProgress, IconButton, Tooltip, Divider,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import BlockIcon from '@mui/icons-material/Block'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import LogoutIcon from '@mui/icons-material/Logout'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` }
}

function StatusChip({ status }) {
  const map = {
    active:    { label: 'Active',    color: 'success' },
    pending:   { label: 'Pending',   color: 'warning' },
    suspended: { label: 'Suspended', color: 'error'   },
  }
  const s = map[status] || { label: status, color: 'default' }
  return <Chip label={s.label} color={s.color} size="small" sx={{ fontSize: '0.7rem' }} />
}

export default function AdminDashboard({ token, onLogout }) {
  const [teams, setTeams]     = useState([])
  const [stats, setStats]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg]         = useState('')
  const [error, setError]     = useState('')
  const [activeTab, setActiveTab] = useState('teams')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [teamsRes, statsRes] = await Promise.all([
        axios.get(`${API_URL}/admin/teams`,   { headers: authHeaders(token) }),
        axios.get(`${API_URL}/admin/stats`,   { headers: authHeaders(token) }),
      ])
      setTeams(teamsRes.data.teams || [])
      setStats(statsRes.data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const act = async (url, successMsg) => {
    setMsg(''); setError('')
    try {
      await axios.post(`${API_URL}${url}`, {}, { headers: authHeaders(token) })
      setMsg(successMsg)
      load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Action failed')
    }
  }

  const pending   = teams.filter(t => t.status === 'pending')
  const active    = teams.filter(t => t.status === 'active')
  const suspended = teams.filter(t => t.status === 'suspended')

  return (
    <Box sx={{ maxWidth: 900, mx: 'auto', p: 3 }}>
      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Box sx={{
            width: 40, height: 40, borderRadius: '10px', bgcolor: 'primary.main',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1rem', fontWeight: 700, color: '#fff',
          }}>আদর</Box>
          <Box>
            <Typography variant="h6" fontWeight={600}>Admin Dashboard</Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              ARCL · Team management
            </Typography>
          </Box>
        </Stack>
        <Tooltip title="Sign out">
          <IconButton onClick={onLogout} size="small" sx={{ color: 'text.secondary' }}>
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {/* Stats cards */}
      {stats && (
        <Stack direction="row" spacing={2} mb={3}>
          {[
            { label: 'Total teams', value: stats.total,     color: '#1A3326' },
            { label: 'Active',      value: stats.active||0, color: '#2EB87E' },
            { label: 'Pending',     value: stats.pending||0,color: '#EF9F27' },
            { label: 'Suspended',   value: stats.suspended||0, color: '#E24B4A' },
          ].map(s => (
            <Paper key={s.label} elevation={0} sx={{
              flex: 1, p: 2, border: '1px solid', borderColor: 'divider', textAlign: 'center',
            }}>
              <Typography variant="h4" fontWeight={700} sx={{ color: s.color }}>{s.value}</Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>{s.label}</Typography>
            </Paper>
          ))}
        </Stack>
      )}

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {/* Pending approvals banner */}
      {pending.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {pending.length} team{pending.length > 1 ? 's' : ''} waiting for approval
        </Alert>
      )}

      {/* Refresh */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1.5}>
        <Typography variant="subtitle2" fontWeight={600}>
          All teams ({teams.length})
        </Typography>
        <IconButton size="small" onClick={load} sx={{ color: 'text.secondary' }}>
          <RefreshIcon fontSize="small" />
        </IconButton>
      </Stack>

      {loading ? (
        <Box sx={{ textAlign: 'center', py: 6 }}>
          <CircularProgress size={28} sx={{ color: 'primary.main' }} />
        </Box>
      ) : teams.length === 0 ? (
        <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center', py: 4 }}>
          No teams registered yet.
        </Typography>
      ) : (
        <Paper elevation={0} sx={{ border: '1px solid', borderColor: 'divider', overflow: 'hidden' }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: 'rgba(46,184,126,0.06)' }}>
                <TableCell sx={{ fontWeight: 600, fontSize: '0.75rem' }}>Team</TableCell>
                <TableCell sx={{ fontWeight: 600, fontSize: '0.75rem' }}>Contact</TableCell>
                <TableCell sx={{ fontWeight: 600, fontSize: '0.75rem' }}>Email</TableCell>
                <TableCell sx={{ fontWeight: 600, fontSize: '0.75rem' }}>Registered</TableCell>
                <TableCell sx={{ fontWeight: 600, fontSize: '0.75rem' }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 600, fontSize: '0.75rem' }} align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {teams.map(team => (
                <TableRow key={team.team_id} sx={{ '&:hover': { bgcolor: 'rgba(46,184,126,0.03)' } }}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>{team.team_name}</Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>{team.team_id}</Typography>
                  </TableCell>
                  <TableCell sx={{ fontSize: '0.8rem' }}>{team.contact_person}</TableCell>
                  <TableCell sx={{ fontSize: '0.8rem', color: 'text.secondary' }}>{team.email}</TableCell>
                  <TableCell sx={{ fontSize: '0.75rem', color: 'text.secondary' }}>
                    {team.created_at ? new Date(team.created_at).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell><StatusChip status={team.status} /></TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                      {team.status === 'pending' && (
                        <Tooltip title="Approve">
                          <IconButton size="small" sx={{ color: '#2EB87E' }}
                            onClick={() => act(`/admin/teams/${team.team_id}/approve`, `${team.team_name} approved`)}>
                            <CheckIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {team.status === 'active' && (
                        <Tooltip title="Suspend">
                          <IconButton size="small" sx={{ color: '#E24B4A' }}
                            onClick={() => act(`/admin/teams/${team.team_id}/suspend`, `${team.team_name} suspended`)}>
                            <BlockIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {team.status === 'suspended' && (
                        <Tooltip title="Reactivate">
                          <IconButton size="small" sx={{ color: '#2EB87E' }}
                            onClick={() => act(`/admin/teams/${team.team_id}/activate`, `${team.team_name} reactivated`)}>
                            <PlayArrowIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}
    </Box>
  )
}