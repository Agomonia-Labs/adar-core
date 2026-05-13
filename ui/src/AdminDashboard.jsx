import { useState, useEffect, useRef } from 'react'
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
import tenant from './tenant'   // CHANGE: import tenant

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

function StatusChip({ status }) {
  const map = {
    active:    { label:'Active',    color:'success' },
    pending:   { label:'Pending',   color:'warning' },
    suspended: { label:'Suspended', color:'error'   },
  }
  const s = map[status] || { label:status, color:'default' }
  return <Chip label={s.label} color={s.color} size="small" sx={{ fontSize:'0.7rem' }} />
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
  const [evalFilter, setEvalFilter] = useState({team:'',minScore:'',maxScore:'',dateFrom:'',dateTo:''})
  const evalFilterRef = useRef({team:'',minScore:'',maxScore:'',dateFrom:'',dateTo:''})
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating]     = useState(false)
  const [newTeam, setNewTeam] = useState({
    team_name:'', email:'', password:'', contact_person:'',
    plan:'complimentary', status:'active', note:''
  })

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [teamsRes, statsRes] = await Promise.all([
        axios.get(`${API_URL}/admin/teams`, { headers:authHeaders(token) }),
        axios.get(`${API_URL}/admin/stats`, { headers:authHeaders(token) }),
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
      await axios.post(`${API_URL}${url}`, {}, { headers:authHeaders(token) })
      setMsg(successMsg); load()
    } catch (e) { setError(e.response?.data?.detail || 'Action failed') }
  }

  const pending   = teams.filter(t => t.status === 'pending')
  const active    = teams.filter(t => t.status === 'active')
  const suspended = teams.filter(t => t.status === 'suspended')

  const fetchEvals = async (filters) => {
    setEvalsLoading(true)
    let url = `${API_URL}/admin/evals`
    if (filters) {
      const p = []
      if (filters.team)     p.push(`team_id=${filters.team}`)
      if (filters.minScore) p.push(`min_score=${filters.minScore}`)
      if (filters.maxScore) p.push(`max_score=${filters.maxScore}`)
      if (filters.dateFrom) p.push(`date_from=${filters.dateFrom}`)
      if (filters.dateTo)   p.push(`date_to=${filters.dateTo}`)
      if (p.length) url += '?' + p.join('&')
    }
    try {
      const res = await fetch(url, { headers:authHeaders(token) })
      const data = await res.json()
      setEvals(data)
    } catch(e) { setError('Failed to load eval data') }
    finally { setEvalsLoading(false) }
  }

  const handleDelete = async (team) => {
    const label = team.team_name || team.email || team.team_id || 'this incomplete record'
    if (!window.confirm(`Permanently delete "${label}"? This cannot be undone.`)) return
    const docId = team.team_id || team.id
    if (!docId) { setError('Cannot delete: record has no ID. Delete it directly from Firestore.'); return }
    try {
      const res = await fetch(`${API_URL}/admin/teams/${team.team_id}`, {
        method:'DELETE', headers:authHeaders(token),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to delete')
      setMsg(`✓ ${data.message}`); load()
    } catch (e) { setError(e.message) }
  }

  const handleCreateTeam = async () => {
    if (!newTeam.team_name?.trim()) { setError('Team name is required'); return }
    if (!newTeam.email?.trim() || !newTeam.email.includes('@')) { setError('Valid email is required'); return }
    if (!newTeam.password || newTeam.password.length < 6) { setError('Password must be at least 6 characters'); return }
    setCreating(true); setError(''); setMsg('')
    try {
      const res = await fetch(`${API_URL}/admin/teams/create`, {
        method:'POST',
        headers:{ 'Content-Type':'application/json', ...authHeaders(token) },
        body:JSON.stringify(newTeam),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to create team')
      setMsg(`✓ Team '${data.team_name || newTeam.team_name}' created. Team ID: ${data.team_id}`)
      setShowCreate(false)
      setNewTeam({ team_name:'', email:'', password:'', contact_person:'', plan:'complimentary', status:'active', note:'' })
      load()
    } catch (e) { setError(e.message) }
    finally { setCreating(false) }
  }

  return (
    <Box sx={{ maxWidth:900, mx:'auto', p:3 }}>
      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Box sx={{
            width:40, height:40, borderRadius:'10px', bgcolor:'primary.main',
            display:'flex', alignItems:'center', justifyContent:'center',
            fontSize:'1rem', fontWeight:700, color:'#fff',
          }}>{tenant.logoText}</Box>
          <Box>
            <Typography variant="h6" fontWeight={600}>Admin Dashboard</Typography>
            {/* CHANGE: tenant.shortName instead of hardcoded "ARCL" */}
            <Typography variant="caption" sx={{ color:'text.secondary' }}>
              {tenant.shortName} · Team management
            </Typography>
          </Box>
        </Stack>
        <Tooltip title="Sign out">
          <IconButton onClick={onLogout} size="small" sx={{ color:'text.secondary' }}>
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {msg   && <Alert severity="success" sx={{ mb:2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb:2 }} onClose={() => setError('')}>{error}</Alert>}

      {loading ? (
        <Box sx={{ textAlign:'center', py:4 }}><CircularProgress sx={{ color:'primary.main' }} /></Box>
      ) : (
        <>
          {/* Stats */}
          {stats && (
            <Stack direction="row" spacing={2} mb={3} flexWrap="wrap">
              {[
                { label:'Total',     val: teams.length },
                { label:'Active',    val: active.length },
                { label:'Pending',   val: pending.length },
                { label:'Suspended', val: suspended.length },
              ].map(({ label, val }) => (
                <Paper key={label} elevation={0} sx={{ p:1.5, border:'1px solid', borderColor:'divider', textAlign:'center', minWidth:80 }}>
                  <Typography variant="h6" fontWeight={700} sx={{ color:'primary.main' }}>{val}</Typography>
                  <Typography variant="caption" sx={{ color:'text.secondary' }}>{label}</Typography>
                </Paper>
              ))}
            </Stack>
          )}

          {/* Tab nav */}
          <Stack direction="row" spacing={1} mb={2}>
            {['teams','evals'].map(t => (
              <Button key={t} size="small" variant={activeTab===t?'contained':'outlined'}
                onClick={() => { setActiveTab(t); if(t==='evals' && !evals) fetchEvals() }}
                sx={{
                  textTransform:'capitalize',
                  ...(activeTab===t ? {} : { borderColor:'divider', color:'text.secondary' })
                }}>
                {t === 'teams' ? '👥 Teams' : '📊 Evals'}
              </Button>
            ))}
          </Stack>

          {/* Teams tab */}
          {activeTab === 'teams' && (
            <Box>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1.5}>
                <Typography variant="subtitle2" fontWeight={600}>All teams ({teams.length})</Typography>
                <Stack direction="row" spacing={1}>
                  <Button size="small" startIcon={<RefreshIcon />} onClick={load}
                    sx={{ borderColor:'divider', color:'text.secondary' }} variant="outlined">
                    Refresh
                  </Button>
                  <Button size="small" variant="contained" onClick={() => setShowCreate(s => !s)}>
                    {showCreate ? 'Cancel' : '+ Add team'}
                  </Button>
                </Stack>
              </Stack>

              {/* Create team form */}
              {showCreate && (
                <Paper elevation={0} sx={{ p:2, mb:2, border:'1px solid', borderColor:'divider' }}>
                  <Typography variant="subtitle2" fontWeight={600} mb={1.5}>Create team</Typography>
                  <Stack spacing={1.5}>
                    {[
                      ['team_name','Team name','text'],
                      ['email','Email','email'],
                      ['contact_person','Contact person','text'],
                      ['password','Password (min 6 chars)','password'],
                    ].map(([field, label, type]) => (
                      <TextField key={field} label={label} type={type} size="small" fullWidth
                        value={newTeam[field]}
                        onChange={e => setNewTeam(t => ({ ...t, [field]:e.target.value }))} />
                    ))}
                    <Stack direction="row" spacing={1}>
                      {['complimentary','basic','standard','unlimited'].map(p => (
                        <Chip key={p} label={p} size="small" clickable
                          onClick={() => setNewTeam(t => ({ ...t, plan:p }))}
                          sx={{ bgcolor: newTeam.plan===p ? 'primary.main' : undefined,
                                color:   newTeam.plan===p ? '#fff' : undefined }} />
                      ))}
                    </Stack>
                    <TextField label="Note (optional)" size="small" fullWidth
                      value={newTeam.note} onChange={e => setNewTeam(t => ({ ...t, note:e.target.value }))} />
                    <Button variant="contained" onClick={handleCreateTeam} disabled={creating}>
                      {creating ? <CircularProgress size={18} sx={{ color:'inherit' }} /> : 'Create team'}
                    </Button>
                  </Stack>
                </Paper>
              )}

              {/* Teams table */}
              <Paper elevation={0} sx={{ border:'1px solid', borderColor:'divider', overflow:'hidden' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{ bgcolor:`rgba(46,184,126,0.06)` }}>
                      {['Team','Email','Contact','Status','Plan','Actions'].map(h => (
                        <TableCell key={h} sx={{ fontWeight:600, fontSize:'0.75rem' }}>{h}</TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {teams.map((team, i) => (
                      <TableRow key={i} sx={{ '&:hover':{ bgcolor:'rgba(46,184,126,0.02)' } }}>
                        <TableCell sx={{ fontSize:'0.8rem', fontWeight:500 }}>{team.team_name}</TableCell>
                        <TableCell sx={{ fontSize:'0.75rem', color:'text.secondary' }}>{team.email}</TableCell>
                        <TableCell sx={{ fontSize:'0.75rem', color:'text.secondary' }}>{team.contact_person}</TableCell>
                        <TableCell><StatusChip status={team.status} /></TableCell>
                        <TableCell sx={{ fontSize:'0.72rem', color:'text.secondary' }}>{team.subscription_plan || '—'}</TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={0.5}>
                            {team.status !== 'active' && (
                              <Tooltip title="Approve">
                                <IconButton size="small" sx={{ color:'success.main' }}
                                  onClick={() => act(`/admin/teams/${team.team_id}/approve`, `✓ ${team.team_name} approved`)}>
                                  <CheckIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            {team.status !== 'suspended' && (
                              <Tooltip title="Suspend">
                                <IconButton size="small" sx={{ color:'error.main' }}
                                  onClick={() => act(`/admin/teams/${team.team_id}/suspend`, `⊘ ${team.team_name} suspended`)}>
                                  <BlockIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            <Tooltip title="Trigger ingestion">
                              <IconButton size="small" sx={{ color:'text.secondary' }}
                                onClick={() => act(`/admin/teams/${team.team_id}/ingest`, `▶ Ingestion started for ${team.team_name}`)}>
                                <PlayArrowIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Delete team">
                              <IconButton size="small" sx={{ color:'error.light', '&:hover':{ color:'error.main' } }}
                                onClick={() => handleDelete(team)}>
                                <span style={{ fontSize:'0.9rem' }}>🗑</span>
                              </IconButton>
                            </Tooltip>
                          </Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Paper>
            </Box>
          )}

          {/* Evals tab */}
          {activeTab === 'evals' && (
            <Box>
              {/* Filters */}
              <Stack direction="row" spacing={1} mb={2} flexWrap="wrap" alignItems="flex-end">
                {[
                  { id:'ef-team', label:'Team ID',   type:'text' },
                  { id:'ef-min',  label:'Min score', type:'number' },
                  { id:'ef-max',  label:'Max score', type:'number' },
                  { id:'ef-from', label:'Date from', type:'date' },
                  { id:'ef-to',   label:'Date to',   type:'date' },
                ].map(({ id, label, type }) => (
                  <TextField key={id} id={id} label={label} type={type} size="small"
                    InputLabelProps={type==='date'?{shrink:true}:undefined}
                    sx={{ width:120 }} />
                ))}
                <Button size="small" variant="contained"
                  onClick={() => {
                    const f = {
                      team:     document.getElementById('ef-team')?.value || '',
                      minScore: document.getElementById('ef-min')?.value  || '',
                      maxScore: document.getElementById('ef-max')?.value  || '',
                      dateFrom: document.getElementById('ef-from')?.value || '',
                      dateTo:   document.getElementById('ef-to')?.value   || '',
                    }
                    fetchEvals(f)
                  }}
                  sx={{ background:'primary.main', mt:2.2 }}>
                  Apply
                </Button>
                <Button size="small" variant="outlined"
                  onClick={() => {
                    ['ef-team','ef-min','ef-max','ef-from','ef-to'].forEach(id => {
                      const el = document.getElementById(id)
                      if (el) el.value = ''
                    })
                    fetchEvals({team:'',minScore:'',maxScore:'',dateFrom:'',dateTo:''})
                  }}
                  sx={{ borderColor:'divider', color:'text.secondary', mt:2.2 }}>
                  Clear
                </Button>
              </Stack>

              {evalsLoading && <Box sx={{ textAlign:'center', py:4 }}><CircularProgress size={24} sx={{ color:'primary.main' }} /></Box>}

              {evals && !evalsLoading && (
                <>
                  <Stack direction="row" spacing={1.5} mb={3} flexWrap="wrap">
                    {Object.entries(evals.averages||{}).map(([k,v]) => (
                      <Paper key={k} elevation={0} sx={{ p:1.5, border:'1px solid', borderColor:'divider', textAlign:'center', minWidth:90 }}>
                        <Typography variant="h6" fontWeight={700}
                          sx={{ color:v>=4?'#2EB87E':v>=3?'#EF9F27':'#E24B4A' }}>{v}</Typography>
                        <Typography variant="caption" sx={{ color:'text.secondary', textTransform:'capitalize' }}>{k}</Typography>
                      </Paper>
                    ))}
                    <Paper elevation={0} sx={{ p:1.5, border:'1px solid', borderColor:'divider', textAlign:'center', minWidth:90 }}>
                      <Typography variant="h6" fontWeight={700} sx={{ color:'text.secondary' }}>{evals.total||0}</Typography>
                      <Typography variant="caption" sx={{ color:'text.secondary' }}>Total</Typography>
                    </Paper>
                  </Stack>

                  {evals.low_scoring?.length > 0 && (
                    <Alert severity="warning" sx={{ mb:2 }}>
                      ⚠ {evals.low_scoring.length} response{evals.low_scoring.length>1?'s':''} scored below 3.0
                    </Alert>
                  )}

                  <Paper elevation={0} sx={{ border:'1px solid', borderColor:'divider', overflow:'hidden' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow sx={{ bgcolor:'rgba(46,184,126,0.06)' }}>
                          {['Question','Overall','A/C/R/F','Team','Date','Flag'].map(h => (
                            <TableCell key={h} sx={{ fontWeight:600, fontSize:'0.75rem' }}>{h}</TableCell>
                          ))}
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(evals.recent||[]).map((e,i) => (
                          <TableRow key={i} sx={{ '&:hover':{ bgcolor:'rgba(46,184,126,0.02)' },
                            bgcolor:e.flagged?'rgba(226,75,74,0.04)':'inherit' }}>
                            <TableCell sx={{ maxWidth:260 }}>
                              <Tooltip title={e.explanation||''} placement="top">
                                <Typography variant="body2" sx={{ fontSize:'0.78rem', overflow:'hidden',
                                  textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:250, cursor:'help' }}>
                                  {e.question}
                                </Typography>
                              </Tooltip>
                            </TableCell>
                            <TableCell>
                              <Chip label={e.overall} size="small" sx={{
                                background:e.overall>=4?'rgba(46,184,126,0.1)':e.overall>=3?'rgba(239,159,39,0.1)':'rgba(226,75,74,0.1)',
                                color:e.overall>=4?'#1A8A5A':e.overall>=3?'#BA7517':'#C62828',
                                fontWeight:600, fontSize:'0.75rem' }} />
                            </TableCell>
                            <TableCell sx={{ fontSize:'0.72rem', color:'text.secondary', whiteSpace:'nowrap' }}>
                              {[e.scores?.accuracy,e.scores?.completeness,e.scores?.relevance,e.scores?.format].join('/')}
                            </TableCell>
                            <TableCell sx={{ fontSize:'0.75rem', color:'text.secondary' }}>{e.team_id}</TableCell>
                            <TableCell sx={{ fontSize:'0.75rem', color:'text.secondary' }}>{e.created_at}</TableCell>
                            <TableCell>
                              <Tooltip title={e.flagged?'Remove flag':'Flag for review'}>
                                <IconButton size="small"
                                  sx={{ color:e.flagged?'#E24B4A':'#ccc', '&:hover':{ color:'#E24B4A' } }}
                                  onClick={async () => {
                                    await fetch(`${API_URL}/admin/evals/${e.eval_id}/${e.flagged?'unflag':'flag'}`,
                                      { method:'POST', headers:authHeaders(token) })
                                    fetchEvals()
                                  }}>
                                  <span style={{ fontSize:'0.9rem' }}>⚑</span>
                                </IconButton>
                              </Tooltip>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Paper>
                </>
              )}

              {!evals && !evalsLoading && (
                <Box sx={{ textAlign:'center', py:4 }}>
                  <Button variant="outlined" onClick={fetchEvals} sx={{ borderColor:'divider', color:'text.secondary' }}>
                    Load eval scores
                  </Button>
                </Box>
              )}
            </Box>
          )}
        </>
      )}
    </Box>
  )
}
