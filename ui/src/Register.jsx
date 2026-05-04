import { useState } from 'react'
import {
  Box, Paper, Typography, TextField, Button,
  Alert, CircularProgress, Stack,
} from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

export default function Register({ onBack }) {
  const [form, setForm] = useState({
    team_name: '', email: '', contact_person: '', password: '', confirm: '',
  })
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [success, setSuccess]   = useState(false)

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm) {
      setError('Passwords do not match')
      return
    }
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
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

  if (success) {
    return (
      <Box sx={{
        minHeight: '100dvh', display: 'flex', alignItems: 'center',
        justifyContent: 'center', bgcolor: 'background.default', p: 2,
      }}>
        <Box sx={{ width: '100%', maxWidth: 400, textAlign: 'center' }}>
          <CheckCircleOutlineIcon sx={{ fontSize: 56, color: 'primary.main', mb: 2 }} />
          <Typography variant="h6" fontWeight={600} mb={1}>Registration submitted</Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', mb: 3 }}>
            Your team registration is pending admin approval. You'll be able to log in
            once the ARCL admin reviews and approves your request.
          </Typography>
          <Button variant="outlined" onClick={onBack}>Back to login</Button>
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{
      minHeight: '100dvh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', bgcolor: 'background.default', p: 2,
    }}>
      <Box sx={{ width: '100%', maxWidth: 440 }}>
        {/* Logo */}
        <Stack alignItems="center" spacing={1} mb={3}>
          <Box sx={{
            width: 56, height: 56, borderRadius: '16px',
            bgcolor: 'primary.main',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.4rem', fontWeight: 700, color: '#fff',
          }}>
            আদর
          </Box>
          <Typography variant="h5" fontWeight={600}>Register your team</Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            ARCL teams only · Admin approval required
          </Typography>
        </Stack>

        <Paper elevation={0} sx={{ p: 3, border: '1px solid', borderColor: 'divider' }}
          component="form" onSubmit={handleSubmit}>

          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          <Stack spacing={2}>
            <TextField
              label="Team name"
              value={form.team_name}
              onChange={set('team_name')}
              fullWidth size="small" required autoFocus
              placeholder="e.g. Agomoni Tigers"
            />
            <TextField
              label="Contact person (captain)"
              value={form.contact_person}
              onChange={set('contact_person')}
              fullWidth size="small" required
              placeholder="Your full name"
            />
            <TextField
              label="Email address"
              type="email"
              value={form.email}
              onChange={set('email')}
              fullWidth size="small" required
              placeholder="team@example.com"
            />
            <TextField
              label="Password"
              type="password"
              value={form.password}
              onChange={set('password')}
              fullWidth size="small" required
              helperText="Minimum 8 characters"
            />
            <TextField
              label="Confirm password"
              type="password"
              value={form.confirm}
              onChange={set('confirm')}
              fullWidth size="small" required
              error={!!form.confirm && form.confirm !== form.password}
              helperText={form.confirm && form.confirm !== form.password ? "Passwords don't match" : ''}
            />
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || !form.team_name || !form.email || !form.password || !form.confirm}
              sx={{ py: 1.2 }}
            >
              {loading ? <CircularProgress size={20} sx={{ color: 'inherit' }} /> : 'Submit registration'}
            </Button>
          </Stack>
        </Paper>

        <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center', mt: 2 }}>
          Already registered?{' '}
          <Box component="span" onClick={onBack}
            sx={{ color: 'primary.main', cursor: 'pointer', '&:hover': { textDecoration: 'underline' } }}>
            Sign in
          </Box>
        </Typography>
      </Box>
    </Box>
  )
}