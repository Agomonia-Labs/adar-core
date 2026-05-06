import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, TextField, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow,
  Alert, IconButton, Tooltip, Divider,
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
  const [evals, setEvals]         = useState(null)
  const [evalsLoading, setEvalsLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating]     = useState(false)
  const [newTeam, setNewTeam] = useState({
    team_name: '', email: '', password: '', contact_person: '',
    plan: 'complimentary', status: 'active', note: ''
  })

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

  const fetchEvals = async () => {
    setEvalsLoading(true)
    try {
      const res = await fetch(`${API_URL}/admin/evals`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      const data = await res.json()
      setEvals(data)
    } catch(e) { setError('Failed to load eval data') }
    finally { setEvalsLoading(false) }
  }

  const handleDelete = async (team) => {
    if (!window.confirm(`Permanently delete "${team.team_name}"? This cannot be undone.`)) return
    try {
      const res = await fetch(`${API_URL}/admin/teams/${team.team_id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to delete')
      setMsg(`✓ ${data.message}`)
      load()
    } catch (e) { setError(e.message) }
  }

  const handleCreateTeam = async () => {
    if (!newTeam.team_name || !newTeam.email || !newTeam.password) {
      setError('Team name, email and password are required'); return
    }
    setCreating(true); setError(''); setMsg('')
    try {
      const res = await fetch(`${API_URL}/admin/teams/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(newTeam),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to create team')
      setMsg(`✓ Team '${data.team_name || newTeam.team_name}' created. Team ID: ${data.team_id}`)
      setShowCreate(false)
      setNewTeam({ team_name: '', email: '', password: '', contact_person: '', plan: 'complimentary', status: 'active', note: '' })
      load()
    } catch (e) { setError(e.message) }
    finally { setCreating(false) }
  }

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

      {/* Tabs */}
      <Stack direction="row" spacing={1} mb={2}>
        {['teams','evals'].map(tab => (
          <Button key={tab} size="small" variant={activeTab===tab?'contained':'outlined'}
            onClick={() => { setActiveTab(tab); if(tab==='evals' && !evals) fetchEvals() }}
            sx={activeTab===tab
              ? {background:'#2EB87E','&:hover':{background:'#1A8A5A'},textTransform:'capitalize'}
              : {borderColor:'#C8E8D8',color:'text.secondary',textTransform:'capitalize'}}>
            {tab === 'teams' ? `Teams (${teams.length})` : 'Eval Scores'}
          </Button>
        ))}
      </Stack>

      {/* Teams tab */}
      {activeTab === 'teams' && (<>

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
        <>
          {/* Create Team Button */}
          <Box sx={{ display:'flex', justifyContent:'flex-end', mb:2 }}>
            <Button variant="contained" size="small" onClick={() => setShowCreate(!showCreate)}
              sx={{ background:'#2EB87E','&:hover':{background:'#1A8A5A'} }}>
              {showCreate ? 'Cancel' : '+ Create team account'}
            </Button>
          </Box>

          {/* Create Team Form */}
          {showCreate && (
            <Box sx={{ background:'#f5fbf7', border:'1px solid #C8E8D8', borderRadius:2, p:3, mb:3 }}>
              <Typography variant="subtitle1" fontWeight={600} mb={2}>Create new team account</Typography>
              <Box sx={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:2, mb:2 }}>
                <TextField label="Team name *" size="small" value={newTeam.team_name}
                  onChange={e => setNewTeam({...newTeam, team_name:e.target.value})} />
                <TextField label="Email *" size="small" type="email" value={newTeam.email}
                  onChange={e => setNewTeam({...newTeam, email:e.target.value})} />
                <TextField label="Temp password *" size="small" value={newTeam.password}
                  onChange={e => setNewTeam({...newTeam, password:e.target.value})} />
                <TextField label="Contact person" size="small" value={newTeam.contact_person}
                  onChange={e => setNewTeam({...newTeam, contact_person:e.target.value})} />
                <TextField select label="Plan" size="small" value={newTeam.plan}
                  onChange={e => setNewTeam({...newTeam, plan:e.target.value})}
                  SelectProps={{native:true}}>
                  <option value="complimentary">Complimentary — No charge · 200 msgs/day</option>
                  <option value="none">No subscription — access only</option>
                  <option value="basic">Basic — $10/mo · 50 msgs/day</option>
                  <option value="standard">Standard — $15/mo · 200 msgs/day</option>
                  <option value="unlimited">Unlimited — $30/mo · 1000 msgs/day</option>
                </TextField>
                <TextField select label="Status" size="small" value={newTeam.status}
                  onChange={e => setNewTeam({...newTeam, status:e.target.value})}
                  SelectProps={{native:true}}>
                  <option value="active">Active — ready to use immediately</option>
                  <option value="pending_payment">Pending payment</option>
                </TextField>
              </Box>
              <TextField label="Admin note (optional)" size="small" fullWidth value={newTeam.note}
                onChange={e => setNewTeam({...newTeam, note:e.target.value})} sx={{mb:2}} />
              <Box sx={{display:'flex',gap:1}}>
                <Button variant="contained" size="small" onClick={handleCreateTeam} disabled={creating}
                  sx={{background:'#2EB87E','&:hover':{background:'#1A8A5A'}}}>
                  {creating ? 'Creating...' : 'Create team'}
                </Button>
                <Button variant="outlined" size="small" onClick={()=>setShowCreate(false)}>Cancel</Button>
              </Box>
            </Box>
          )}

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
                      <Tooltip title="Delete team">
                        <IconButton size="small" sx={{ color: '#999','&:hover':{color:'#E24B4A'} }}
                          onClick={() => handleDelete(team)}>
                          <span style={{fontSize:'0.85rem'}}>🗑</span>
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
        </>
      )}

      </>)}

      {/* Evals tab */}
      {activeTab === 'evals' && (
        <Box>
          <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
            <Typography variant="subtitle2" fontWeight={600}>Response Quality Scores</Typography>
            <IconButton size="small" onClick={fetchEvals} sx={{ color: 'text.secondary' }}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Stack>
          {evalsLoading && <Box sx={{textAlign:'center',py:4}}><CircularProgress size={24} sx={{color:'#2EB87E'}}/></Box>}
          {evals && !evalsLoading && (
            <>
              {/* Averages */}
              <Stack direction="row" spacing={1.5} mb={3} flexWrap="wrap">
                {Object.entries(evals.averages||{}).map(([k,v]) => (
                  <Paper key={k} elevation={0} sx={{p:1.5,border:'1px solid',borderColor:'divider',textAlign:'center',minWidth:80}}>
                    <Typography variant="h6" fontWeight={700}
                      sx={{color: v>=4?'#2EB87E':v>=3?'#EF9F27':'#E24B4A'}}>
                      {v}
                    </Typography>
                    <Typography variant="caption" sx={{color:'text.secondary',textTransform:'capitalize'}}>{k}</Typography>
                  </Paper>
                ))}
                <Paper elevation={0} sx={{p:1.5,border:'1px solid',borderColor:'divider',textAlign:'center',minWidth:80}}>
                  <Typography variant="h6" fontWeight={700} sx={{color:'text.secondary'}}>{evals.total||0}</Typography>
                  <Typography variant="caption" sx={{color:'text.secondary'}}>Total evals</Typography>
                </Paper>
              </Stack>

              {/* Low scoring */}
              {evals.low_scoring?.length > 0 && (
                <Alert severity="warning" sx={{mb:2}}>
                  ⚠ {evals.low_scoring.length} response{evals.low_scoring.length>1?'s':''} scored below 3.0
                </Alert>
              )}

              {/* Recent evals table */}
              <Paper elevation={0} sx={{border:'1px solid',borderColor:'divider',overflow:'hidden'}}>
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{bgcolor:'rgba(46,184,126,0.06)'}}>
                      <TableCell sx={{fontWeight:600,fontSize:'0.75rem'}}>Question</TableCell>
                      <TableCell sx={{fontWeight:600,fontSize:'0.75rem'}}>Overall</TableCell>
                      <TableCell sx={{fontWeight:600,fontSize:'0.75rem'}}>Team</TableCell>
                      <TableCell sx={{fontWeight:600,fontSize:'0.75rem'}}>Date</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(evals.recent||[]).map((e,i) => (
                      <TableRow key={i} sx={{'&:hover':{bgcolor:'rgba(46,184,126,0.02)'}}}>
                        <TableCell sx={{fontSize:'0.8rem',maxWidth:300}}>
                          <Typography variant="body2" sx={{fontSize:'0.8rem',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',maxWidth:280}}>
                            {e.question}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip label={e.overall}
                            size="small"
                            sx={{
                              background: e.overall>=4?'rgba(46,184,126,0.1)':e.overall>=3?'rgba(239,159,39,0.1)':'rgba(226,75,74,0.1)',
                              color: e.overall>=4?'#1A8A5A':e.overall>=3?'#BA7517':'#C62828',
                              fontWeight:600,fontSize:'0.75rem',
                            }}
                          />
                        </TableCell>
                        <TableCell sx={{fontSize:'0.78rem',color:'text.secondary'}}>{e.team_id}</TableCell>
                        <TableCell sx={{fontSize:'0.78rem',color:'text.secondary'}}>{e.created_at}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Paper>
            </>
          )}
          {!evals && !evalsLoading && (
            <Box sx={{textAlign:'center',py:4}}>
              <Button variant="outlined" onClick={fetchEvals} sx={{borderColor:'#C8E8D8',color:'text.secondary'}}>
                Load eval scores
              </Button>
            </Box>
          )}
        </Box>
      )}

    </Box>
  )
}