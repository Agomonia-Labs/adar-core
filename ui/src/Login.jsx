import { useState } from 'react'
import {
  Box, Paper, Typography, TextField, Button,
  Alert, CircularProgress, Stack, Divider,
} from '@mui/material'
import axios from 'axios'
import tenant from './tenant'

const API_URL = import.meta.env.VITE_API_URL || ''

export default function Login({ onLogin }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [message, setMessage]   = useState('')

  const [mode, setMode] = useState(() => {
    const p = new URLSearchParams(window.location.search)
    return p.get('reset_token') ? 'reset' : 'login'
  })
  const [resetToken] = useState(() =>
    new URLSearchParams(window.location.search).get('reset_token') || ''
  )
  const [forgotEmail, setForgotEmail]         = useState('')
  const [newPassword, setNewPassword]         = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  // MFA / OTP state
  const [mfaToken, setMfaToken]     = useState('')
  const [emailHint, setEmailHint]   = useState('')
  const [otp, setOtp]               = useState('')
  const [resendCooldown, setResendCooldown] = useState(0)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!email.trim() || !password) return
    setLoading(true)
    try {
      const { data } = await axios.post(`${API_URL}/api/auth/login`, {
        email: email.trim().toLowerCase(), password,
      })
      if (data.mfa_required) {
        setMfaToken(data.mfa_token)
        setEmailHint(data.email_hint)
        setMode('otp')
        setError('')
      } else {
        localStorage.setItem('adar_token',     data.access_token)
        localStorage.setItem('adar_team_id',   data.team_id)
        localStorage.setItem('adar_team_name', data.team_name)
        localStorage.setItem('adar_role',      data.role)
        localStorage.setItem('adar_status',    data.status || 'active')
        onLogin(data)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleForgot = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await axios.post(`${API_URL}/api/auth/forgot-password`, { email: forgotEmail })
    } catch { /* always show success */ }
    setMessage('If that email is registered you will receive a reset link shortly.')
    setLoading(false)
  }

  const handleReset = async (e) => {
    e.preventDefault()
    setError('')
    if (newPassword !== confirmPassword) { setError('Passwords do not match'); return }
    if (newPassword.length < 8) { setError('Minimum 8 characters'); return }
    setLoading(true)
    try {
      await axios.post(`${API_URL}/api/auth/reset-password`, {
        token: resetToken, new_password: newPassword,
      })
      setMessage('Password updated! You can now sign in.')
      window.history.replaceState({}, '', window.location.pathname)
      setTimeout(() => { setMode('login'); setMessage('') }, 2500)
    } catch (err) {
      setError(err.response?.data?.detail || 'Reset failed. Link may have expired.')
    } finally {
      setLoading(false)
    }
  }

  const handleVerifyOtp = async (e) => {
    e.preventDefault()
    setError('')
    if (otp.trim().length !== 6) { setError('Enter the 6-digit code.'); return }
    setLoading(true)
    try {
      const { data } = await axios.post(`${API_URL}/api/auth/verify-otp`, {
        mfa_token: mfaToken, otp: otp.trim(),
      })
      localStorage.setItem('adar_token',     data.access_token)
      localStorage.setItem('adar_team_id',   data.team_id)
      localStorage.setItem('adar_team_name', data.team_name)
      localStorage.setItem('adar_role',      data.role)
      localStorage.setItem('adar_status',    data.status || 'active')
      onLogin(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleResendOtp = async () => {
    setError('')
    try {
      await axios.post(`${API_URL}/api/auth/resend-otp`, { mfa_token: mfaToken })
      setMessage('New code sent!')
      setResendCooldown(60)
      const timer = setInterval(() => {
        setResendCooldown(c => {
          if (c <= 1) { clearInterval(timer); return 0 }
          return c - 1
        })
      }, 1000)
      setTimeout(() => setMessage(''), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not resend code.')
    }
  }

  const Logo = () => (
    <Box sx={{
      width:52, height:52, borderRadius:'14px', bgcolor:'primary.main',
      display:'flex', alignItems:'center', justifyContent:'center',
      fontSize:'1.1rem', fontWeight:700, color:'#fff',
    }}>{tenant.logoText}</Box>
  )

  // ── OTP verification ─────────────────────────────────────────────────────────
  if (mode === 'otp') return (
    <Box sx={{ minHeight:'100dvh', display:'flex', alignItems:'center', justifyContent:'center', bgcolor:'background.default', p:2 }}>
      <Box sx={{ width:'100%', maxWidth:400 }}>
        <Stack alignItems="center" spacing={1} mb={3}>
          <Logo />
          <Typography variant="h6" fontWeight={700}>Check your email</Typography>
          <Typography variant="body2" color="text.secondary" textAlign="center">
            We sent a 6-digit login code to<br/>
            <strong>{emailHint}</strong>
          </Typography>
        </Stack>
        <Paper elevation={0} sx={{ p:3, border:'1px solid', borderColor:'divider', borderRadius:3 }}
          component="form" onSubmit={handleVerifyOtp}>
          {error   && <Alert severity="error"   sx={{ mb:2 }}>{error}</Alert>}
          {message && <Alert severity="success" sx={{ mb:2 }}>{message}</Alert>}
          <TextField
            fullWidth label="6-digit code" value={otp}
            onChange={e => setOtp(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
            inputProps={{ inputMode:'numeric', maxLength:6,
              style:{ fontSize:'2rem', fontWeight:700, letterSpacing:'0.5em', textAlign:'center' }
            }}
            sx={{ mb:2 }} autoFocus placeholder="000000"
          />
          <Button fullWidth type="submit" variant="contained" disabled={loading || otp.length !== 6}
            sx={{ py:1.5, fontWeight:700, mb:1.5 }}>
            {loading ? <CircularProgress size={22} color="inherit"/> : 'Verify Code'}
          </Button>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Button size="small" onClick={() => { setMode('login'); setOtp(''); setError('') }}>
              ← Back to login
            </Button>
            <Button size="small" disabled={resendCooldown > 0} onClick={handleResendOtp}>
              {resendCooldown > 0 ? `Resend in ${resendCooldown}s` : 'Resend code'}
            </Button>
          </Stack>
        </Paper>
        <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={2}>
          Code expires in 5 minutes · Do not share this code
        </Typography>
      </Box>
    </Box>
  )

  // ── Forgot password ─────────────────────────────────────────────────────────
  if (mode === 'forgot') return (
    <Box sx={{ minHeight:'100dvh', display:'flex', alignItems:'center', justifyContent:'center', bgcolor:'background.default', p:2 }}>
      <Box sx={{ width:'100%', maxWidth:400 }}>
        <Stack alignItems="center" spacing={1} mb={3}>
          <Logo />
          <Typography variant="h6" fontWeight={600}>Reset your password</Typography>
          <Typography variant="body2" sx={{ color:'text.secondary' }}>
            Enter your email and we'll send a reset link
          </Typography>
        </Stack>
        <Paper elevation={0} sx={{ p:3, border:'1px solid', borderColor:'divider' }}
          component="form" onSubmit={handleForgot}>
          {error   && <Alert severity="error"   sx={{ mb:2 }}>{error}</Alert>}
          {message && <Alert severity="success" sx={{ mb:2 }}>{message}</Alert>}
          {!message && (
            <Stack spacing={2}>
              <TextField label="Email address" type="email" value={forgotEmail}
                onChange={e => setForgotEmail(e.target.value)} fullWidth size="small" required autoFocus />
              <Button type="submit" variant="contained" fullWidth disabled={loading} sx={{ py:1.2 }}>
                {loading ? <CircularProgress size={20} sx={{ color:'inherit' }} /> : 'Send reset link'}
              </Button>
            </Stack>
          )}
        </Paper>
        <Typography variant="body2" sx={{ color:'text.secondary', textAlign:'center', mt:2 }}>
          <Box component="span" onClick={() => { setMode('login'); setError(''); setMessage('') }}
            sx={{ color:'primary.main', cursor:'pointer', '&:hover':{ textDecoration:'underline' } }}>
            ← Back to sign in
          </Box>
        </Typography>
      </Box>
    </Box>
  )

  // ── Reset password ──────────────────────────────────────────────────────────
  if (mode === 'reset') return (
    <Box sx={{ minHeight:'100dvh', display:'flex', alignItems:'center', justifyContent:'center', bgcolor:'background.default', p:2 }}>
      <Box sx={{ width:'100%', maxWidth:400 }}>
        <Stack alignItems="center" spacing={1} mb={3}>
          <Logo />
          <Typography variant="h6" fontWeight={600}>Set new password</Typography>
        </Stack>
        <Paper elevation={0} sx={{ p:3, border:'1px solid', borderColor:'divider' }}
          component="form" onSubmit={handleReset}>
          {error   && <Alert severity="error"   sx={{ mb:2 }}>{error}</Alert>}
          {message && <Alert severity="success" sx={{ mb:2 }}>{message}</Alert>}
          {!message && (
            <Stack spacing={2}>
              <TextField label="New password" type="password" value={newPassword}
                onChange={e => setNewPassword(e.target.value)} fullWidth size="small" required autoFocus
                helperText="Minimum 8 characters" />
              <TextField label="Confirm password" type="password" value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)} fullWidth size="small" required
                error={!!confirmPassword && confirmPassword !== newPassword}
                helperText={confirmPassword && confirmPassword !== newPassword ? "Passwords don't match" : ''} />
              <Button type="submit" variant="contained" fullWidth disabled={loading} sx={{ py:1.2 }}>
                {loading ? <CircularProgress size={20} sx={{ color:'inherit' }} /> : 'Update password'}
              </Button>
            </Stack>
          )}
        </Paper>
      </Box>
    </Box>
  )

  // ── Main login ──────────────────────────────────────────────────────────────
  return (
    <Box sx={{ minHeight:'100dvh', display:'flex', alignItems:'center', justifyContent:'center', bgcolor:'background.default', p:2 }}>
      <Box sx={{ width:'100%', maxWidth:400 }}>
        <Stack alignItems="center" spacing={1} mb={4}>
          <Logo />
          {/* CHANGE: tenant.loginTitle instead of hardcoded "Adar ARCL" */}
          <Typography variant="h5" fontWeight={600}>{tenant.loginTitle}</Typography>
          <Typography variant="body2" sx={{ color:'text.secondary' }}>
            Sign in to your account
          </Typography>
        </Stack>

        <Paper elevation={0} sx={{ p:3, border:'1px solid', borderColor:'divider' }}
          component="form" onSubmit={handleSubmit}>

          {error && <Alert severity="error" sx={{ mb:2 }}>{error}</Alert>}

          <Stack spacing={2}>
            <TextField label="Email address" type="email" value={email}
              onChange={e => setEmail(e.target.value)} fullWidth size="small"
              autoComplete="email" autoFocus required />
            <TextField label="Password" type="password" value={password}
              onChange={e => setPassword(e.target.value)} fullWidth size="small"
              autoComplete="current-password" required />
            <Button type="submit" variant="contained" fullWidth
              disabled={loading || !email.trim() || !password} sx={{ py:1.2 }}>
              {loading ? <CircularProgress size={20} sx={{ color:'inherit' }} /> : 'Sign in'}
            </Button>

            <Box sx={{ textAlign:'right' }}>
              <Box component="span"
                onClick={() => { setMode('forgot'); setError(''); setMessage('') }}
                sx={{ color:'primary.main', fontSize:'0.8rem', cursor:'pointer', '&:hover':{ textDecoration:'underline' } }}>
                Forgot password?
              </Box>
            </Box>
          </Stack>

          <Divider sx={{ my:2 }}>
            <Box component="a"
              href={tenant.id === 'geetabitan' ? '/demo.geetabitan.html' : tenant.id === 'restaurants' ? '/demo.restaurants.html' : '/demo.html'}
              target="_blank" rel="noopener noreferrer"
              sx={{
                display:'inline-flex', alignItems:'center', gap:0.75,
                bgcolor:`${tenant.primaryColor}14`, border:'1px solid',
                borderColor:'primary.main', borderRadius:2,
                px:2, py:0.6, fontSize:'0.8rem', fontWeight:600,
                color:'primary.main', textDecoration:'none',
                '&:hover':{ bgcolor:`${tenant.primaryColor}28` },
              }}>
              ▶ {tenant.id === 'geetabitan' ? 'পরিচিতি দেখুন' : 'Watch demo'}
            </Box>
          </Divider>

          <Typography variant="body2" sx={{ color:'text.secondary', textAlign:'center' }}>
            No account?{' '}
            <Box component="span" onClick={() => onLogin(null, 'register')}
              sx={{ color:'primary.main', cursor:'pointer', '&:hover':{ textDecoration:'underline' } }}>
              {tenant.id === 'geetabitan' ? 'সংগঠন নিবন্ধন করুন' : 'Register your team'}
            </Box>
          </Typography>
        </Paper>

        {/* CHANGE: tenant.loginCaption instead of hardcoded ARCL text */}
        <Typography variant="caption" sx={{ color:'text.secondary', display:'block', textAlign:'center', mt:2 }}>
          {tenant.loginCaption}
        </Typography>
      </Box>
    </Box>
  )
}