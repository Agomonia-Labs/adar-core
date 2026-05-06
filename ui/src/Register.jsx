import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, TextField, Button,
  Alert, CircularProgress, Stack, Autocomplete,
  LinearProgress,
} from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

function passwordStrength(pw) {
  if (!pw) return { score: 0, label: '', color: 'grey.300' }
  let score = 0
  if (pw.length >= 8)  score++
  if (pw.length >= 12) score++
  if (/[A-Z]/.test(pw)) score++
  if (/[0-9]/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  if (score <= 1) return { score: 20, label: 'Weak',   color: '#E24B4A' }
  if (score <= 2) return { score: 50, label: 'Fair',   color: '#EF9F27' }
  if (score <= 3) return { score: 75, label: 'Good',   color: '#2EB87E' }
  return              { score: 100, label: 'Strong', color: '#1A8A5A' }
}

export default function Register({ onBack }) {
  const [form, setForm] = useState({
    team_name: '', email: '', contact_person: '', password: '', confirm: '',
  })
  const [teams, setTeams]             = useState([])
  const [teamsLoading, setTeamsLoading] = useState(true)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState('')
  const [success, setSuccess]         = useState(false)

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))
  const pwStr = passwordStrength(form.password)

  useEffect(() => {
    axios.get(`${API_URL}/api/arcl/teams?season=69`)
      .then(r => setTeams((r.data.teams || []).map(t => t.name)))
      .catch(() => setTeams([]))
      .finally(() => setTeamsLoading(false))
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm) { setError('Passwords do not match'); return }
    if (form.password.length < 8)       { setError('Password must be at least 8 characters'); return }
    setLoading(true)
    try {
      await axios.post(`${API_URL}/api/auth/register`, {
        team_name:      form.team_name.trim(),
        email:          form.email.trim().toLowerCase(),
        contact_person: form.contact_person.trim(),
        password:       form.password,
      })
      setSuccess(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) return (
    <Box sx={{ minHeight:'100dvh', display:'flex', alignItems:'center', justifyContent:'center', bgcolor:'background.default', p:2 }}>
      <Box sx={{ width:'100%', maxWidth:420, textAlign:'center' }}>
        <CheckCircleOutlineIcon sx={{ fontSize:56, color:'primary.main', mb:2 }} />
        <Typography variant="h6" fontWeight={600} mb={1}>Registration successful!</Typography>
        <Typography variant="body2" sx={{ color:'text.secondary', mb:1 }}>
          Welcome to Adar, <strong>{form.team_name}</strong>!
        </Typography>
        <Typography variant="body2" sx={{ color:'text.secondary', mb:3 }}>
          Next: subscribe to start your <strong>14-day free trial</strong>. No charge during trial. Cancel anytime.
        </Typography>
        <Button variant="contained" fullWidth sx={{ py:1.2, mb:1.5 }} onClick={onBack}>
          Sign in to subscribe →
        </Button>
        <Typography variant="caption" sx={{ color:'text.secondary' }}>
          Powered by Stripe · PCI DSS compliant
        </Typography>
      </Box>
    </Box>
  )

  return (
    <Box sx={{ minHeight:'100dvh', display:'flex', alignItems:'center', justifyContent:'center', bgcolor:'background.default', p:2 }}>
      <Box sx={{ width:'100%', maxWidth:460 }}>
        <Stack alignItems="center" spacing={1} mb={3}>
          <Box sx={{ width:56, height:56, borderRadius:'16px', bgcolor:'primary.main', display:'flex', alignItems:'center', justifyContent:'center', fontSize:'1.4rem', fontWeight:700, color:'#fff' }}>আদর</Box>
          <Typography variant="h5" fontWeight={600}>Register your team</Typography>
          <Typography variant="body2" sx={{ color:'text.secondary' }}>
            ARCL teams · 14-day free trial · No credit card until trial ends
          </Typography>
        </Stack>

        <Paper elevation={0} sx={{ p:3, border:'1px solid', borderColor:'divider' }} component="form" onSubmit={handleSubmit}>
          {error && <Alert severity="error" sx={{ mb:2 }}>{error}</Alert>}
          <Stack spacing={2}>

            <Autocomplete
              options={teamsLoading ? [] : teams}
              loading={teamsLoading}
              value={form.team_name}
              onChange={(_, val) => setForm(f => ({ ...f, team_name: val || '' }))}
              onInputChange={(_, val) => setForm(f => ({ ...f, team_name: val }))}
              freeSolo
              renderInput={(params) => (
                <TextField {...params} label="Your ARCL team" size="small" required
                  placeholder="Start typing to search..."
                  helperText="Select your team or type if not found"
                  InputProps={{ ...params.InputProps, endAdornment: (<>{teamsLoading ? <CircularProgress size={16} /> : null}{params.InputProps.endAdornment}</>) }}
                />
              )}
            />

            <TextField label="Contact person (captain)" value={form.contact_person} onChange={set('contact_person')} fullWidth size="small" required placeholder="Your full name" />
            <TextField label="Email address" type="email" value={form.email} onChange={set('email')} fullWidth size="small" required placeholder="team@example.com" />

            <Box>
              <TextField label="Password" type="password" value={form.password} onChange={set('password')} fullWidth size="small" required />
              {form.password && (
                <Box sx={{ mt:0.75 }}>
                  <LinearProgress variant="determinate" value={pwStr.score}
                    sx={{ height:4, borderRadius:2, bgcolor:'grey.200', '& .MuiLinearProgress-bar': { bgcolor: pwStr.color, borderRadius:2 } }} />
                  <Typography variant="caption" sx={{ color: pwStr.color }}>{pwStr.label}</Typography>
                </Box>
              )}
            </Box>

            <TextField label="Confirm password" type="password" value={form.confirm} onChange={set('confirm')} fullWidth size="small" required
              error={!!form.confirm && form.confirm !== form.password}
              helperText={form.confirm && form.confirm !== form.password ? "Passwords don't match" : ''} />

            <Button type="submit" variant="contained" fullWidth
              disabled={loading || !form.team_name || !form.email || !form.password || !form.confirm}
              sx={{ py:1.2 }}>
              {loading ? <CircularProgress size={20} sx={{ color:'inherit' }} /> : 'Register & start free trial'}
            </Button>
          </Stack>
        </Paper>

        <Typography variant="body2" sx={{ color:'text.secondary', textAlign:'center', mt:2 }}>
          Already registered?{' '}
          <Box component="span" onClick={onBack} sx={{ color:'primary.main', cursor:'pointer', '&:hover':{ textDecoration:'underline' } }}>Sign in</Box>
        </Typography>
      </Box>
    </Box>
  )
}