import { useEffect, useRef, useState } from 'react'
import {
  Alert, Box, Button, CircularProgress, Paper, Stack, Typography,
} from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import axios from 'axios'
import tenant from './tenant'

const API_URL = import.meta.env.VITE_API_URL || ''

export default function SubscriptionReturn({ token, onSignInAgain }) {
  const started = useRef(false)
  const [state, setState] = useState({ status: 'verifying', detail: '', result: null })

  useEffect(() => {
    if (started.current) return
    started.current = true

    const params = new URLSearchParams(window.location.search)
    const sessionId = params.get('session_id') || ''
    if (!token || !sessionId) {
      setState({
        status: 'error',
        detail: 'Your payment return could not be verified in this browser. Sign in again to refresh your subscription status.',
        result: null,
      })
      return
    }

    axios.post(
      `${API_URL}/api/payments/activate?session_id=${encodeURIComponent(sessionId)}`,
      {},
      { headers: { Authorization: `Bearer ${token}` } },
    ).then(({ data }) => {
      localStorage.setItem('adar_status', 'active')
      window.history.replaceState({}, '', window.location.pathname)
      setState({ status: 'success', detail: '', result: data })
    }).catch((error) => {
      setState({
        status: 'error',
        detail: error.response?.data?.detail || 'Subscription verification did not complete. Please sign in again or contact support.',
        result: null,
      })
    })
  }, [token])

  const planLabel = state.result?.plan === 'yearly' ? 'Yearly' : 'Monthly'

  return (
    <Box sx={{
      minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      bgcolor: 'background.default', p: 2,
    }}>
      <Paper elevation={0} sx={{
        width: '100%', maxWidth: 460, p: { xs: 3, sm: 4 }, textAlign: 'center',
        border: '1px solid', borderColor: 'divider', borderRadius: 2,
      }}>
        {state.status === 'verifying' && (
          <Stack alignItems="center" spacing={2}>
            <CircularProgress size={44} />
            <Typography variant="h6" fontWeight={700}>Verifying your subscription</Typography>
            <Typography variant="body2" color="text.secondary">
              Confirming your payment and activating {tenant.appTitle}.
            </Typography>
          </Stack>
        )}

        {state.status === 'success' && (
          <Stack alignItems="center" spacing={1.5}>
            <CheckCircleOutlineIcon sx={{ fontSize: 62, color: 'success.main' }} />
            <Typography variant="h5" fontWeight={700}>Subscription is active</Typography>
            <Typography variant="body1">
              Your ADAR Front Desk {planLabel} subscription has been verified and activated.
            </Typography>
            {state.result?.email_sent ? (
              <Alert severity="success" sx={{ width: '100%', textAlign: 'left' }}>
                A confirmation email was sent to {state.result.email}.
              </Alert>
            ) : (
              <Alert severity="warning" sx={{ width: '100%', textAlign: 'left' }}>
                Your subscription is active, but the confirmation email could not be sent. You can still sign in and use Front Desk.
              </Alert>
            )}
            <Typography variant="body2" color="text.secondary">
              Sign in again so your new session includes the active subscription status.
            </Typography>
            <Button variant="contained" fullWidth onClick={onSignInAgain} sx={{ mt: 1, py: 1.25 }}>
              Sign in again
            </Button>
          </Stack>
        )}

        {state.status === 'error' && (
          <Stack spacing={2}>
            <Alert severity="error" sx={{ textAlign: 'left' }}>{state.detail}</Alert>
            <Button variant="contained" fullWidth onClick={onSignInAgain}>
              Return to sign in
            </Button>
          </Stack>
        )}
      </Paper>
    </Box>
  )
}
