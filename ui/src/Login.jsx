import { useState } from 'react'
import {
  Box, Paper, Typography, TextField, Button,
  Alert, CircularProgress, Stack, Divider,
} from '@mui/material'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

export default function Login({ onLogin }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!email.trim() || !password) return
    setLoading(true)
    try {
      const { data } = await axios.post(`${API_URL}/api/auth/login`, {
        email: email.trim().toLowerCase(),
        password,
      })
      // Store JWT and team info
      localStorage.setItem('adar_token',     data.access_token)
      localStorage.setItem('adar_team_id',   data.team_id)
      localStorage.setItem('adar_team_name', data.team_name)
      localStorage.setItem('adar_role',      data.role)
      onLogin(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{
      minHeight: '100dvh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', bgcolor: 'background.default', p: 2,
    }}>
      <Box sx={{ width: '100%', maxWidth: 400 }}>
        {/* Logo */}
        <Stack alignItems="center" spacing={1} mb={4}>
          <Box sx={{
            width: 56, height: 56, borderRadius: '16px',
            bgcolor: 'primary.main',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.4rem', fontWeight: 700, color: '#fff',
          }}>
            আদর
          </Box>
          <Typography variant="h5" fontWeight={600} sx={{ color: 'text.primary' }}>
            Adar ARCL
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            Sign in to your team account
          </Typography>
        </Stack>

        <Paper elevation={0} sx={{ p: 3, border: '1px solid', borderColor: 'divider' }}
          component="form" onSubmit={handleSubmit}>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
          )}

          <Stack spacing={2}>
            <TextField
              label="Email address"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              fullWidth
              size="small"
              autoComplete="email"
              autoFocus
              required
            />
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              fullWidth
              size="small"
              autoComplete="current-password"
              required
            />
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || !email.trim() || !password}
              sx={{ py: 1.2 }}
            >
              {loading ? <CircularProgress size={20} sx={{ color: 'inherit' }} /> : 'Sign in'}
            </Button>
          </Stack>

          <Divider sx={{ my: 2 }} />

          <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center' }}>
            No account?{' '}
            <Box
              component="span"
              onClick={() => onLogin(null, 'register')}
              sx={{ color: 'primary.main', cursor: 'pointer', '&:hover': { textDecoration: 'underline' } }}
            >
              Register your team
            </Box>
          </Typography>
        </Paper>

        <Box sx={{ textAlign: 'center', mt: 2 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Powered by Adar · American Recreational Cricket League
          </Typography>
          <Box sx={{ mt: 1 }}>
            <Box
              component="a"
              href="/demo.html"
              target="_blank"
              rel="noopener noreferrer"
              sx={{
                display: 'inline-flex', alignItems: 'center', gap: 0.5,
                color: 'primary.main', fontSize: '0.78rem', fontWeight: 600,
                textDecoration: 'none',
                '&:hover': { textDecoration: 'underline' },
              }}
            >
              ▶ Watch product demo
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  )
}