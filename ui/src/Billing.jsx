import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack,
  Divider, Table, TableBody, TableCell, TableHead,
  TableRow, CircularProgress, Alert, Tooltip,
} from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

const STATUS_COLORS = {
  active:    'success',
  trialing:  'info',
  past_due:  'warning',
  canceled:  'error',
  none:      'default',
  inactive:  'default',
}

const STATUS_LABELS = {
  active:   'Active',
  trialing: 'Free trial',
  past_due: 'Payment due',
  canceled: 'Cancelled',
  none:     'No subscription',
  inactive: 'No subscription',
}

export default function Billing({ token, onSubscribe, onBack }) {
  const [billing, setBilling]   = useState(null)
  const [loading, setLoading]   = useState(true)
  const [actionLoading, setActionLoading] = useState('')
  const [msg, setMsg]           = useState('')
  const [error, setError]       = useState('')

  const authHeaders = { Authorization: `Bearer ${token}` }

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get(`${API_URL}/api/payments/billing`, { headers: authHeaders })
      setBilling(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load billing info')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openPortal = async () => {
    setActionLoading('portal')
    try {
      const { data } = await axios.post(`${API_URL}/api/payments/portal`, {}, { headers: authHeaders })
      window.location.href = data.url
    } catch (e) {
      setError('Could not open billing portal')
    } finally {
      setActionLoading('')
    }
  }

  const cancelSubscription = async () => {
    if (!window.confirm('Cancel subscription? You keep access until the end of the billing period.')) return
    setActionLoading('cancel')
    try {
      const { data } = await axios.post(`${API_URL}/api/payments/cancel`, {}, { headers: authHeaders })
      setMsg(data.message)
      load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not cancel')
    } finally {
      setActionLoading('')
    }
  }

  const reactivate = async () => {
    setActionLoading('reactivate')
    try {
      const { data } = await axios.post(`${API_URL}/api/payments/reactivate`, {}, { headers: authHeaders })
      setMsg(data.message)
      load()
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not reactivate')
    } finally {
      setActionLoading('')
    }
  }

  if (loading) return (
    <Box sx={{ textAlign: 'center', py: 6 }}>
      <CircularProgress size={28} sx={{ color: 'primary.main' }} />
    </Box>
  )

  const noSub = !billing || billing.status === 'none'

  return (
    <Box sx={{ maxWidth: 600, mx: 'auto', p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h6" fontWeight={600}>Billing & Subscription</Typography>
        <Typography variant="body2" onClick={onBack}
          sx={{ color: 'text.secondary', cursor: 'pointer', '&:hover': { color: 'primary.main' } }}>
          ← Back
        </Typography>
      </Stack>

      {msg   && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg('')}>{msg}</Alert>}
      {error && <Alert severity="error"   sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {/* Current plan */}
      <Paper elevation={0} sx={{ p: 3, border: '1px solid', borderColor: 'divider', mb: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
          <Box>
            <Typography variant="subtitle2" fontWeight={600} mb={0.5}>
              Current plan
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="h5" fontWeight={700} sx={{ textTransform: 'capitalize' }}>
                {billing?.plan || 'None'}
              </Typography>
              <Chip
                label={STATUS_LABELS[billing?.status] || 'Unknown'}
                color={STATUS_COLORS[billing?.status] || 'default'}
                size="small"
              />
            </Stack>
            {billing?.trial_end_date && billing?.status === 'trialing' && (
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Trial ends {new Date(billing.trial_end_date).toLocaleDateString()}
              </Typography>
            )}
            {billing?.next_billing_date && billing?.status !== 'trialing' && (
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {billing.cancel_at_period_end ? 'Cancels' : 'Renews'} on{' '}
                {new Date(billing.next_billing_date).toLocaleDateString()}
              </Typography>
            )}
          </Box>

          {/* Usage today */}
          <Box sx={{ textAlign: 'right' }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>Today's usage</Typography>
            <Typography variant="h6" fontWeight={600}>
              {billing?.usage_today || 0}
              <Typography component="span" variant="body2" sx={{ color: 'text.secondary' }}>
                /{billing?.daily_quota || 0}
              </Typography>
            </Typography>
          </Box>
        </Stack>

        <Divider sx={{ my: 2 }} />

        <Stack direction="row" spacing={1.5} flexWrap="wrap">
          {noSub ? (
            <Button variant="contained" size="small" onClick={onSubscribe}>
              Subscribe now
            </Button>
          ) : (
            <>
              <Button
                variant="outlined" size="small"
                onClick={openPortal}
                disabled={actionLoading === 'portal'}
                startIcon={actionLoading === 'portal' ? <CircularProgress size={14} /> : null}
              >
                Manage · Update card
              </Button>

              {billing?.cancel_at_period_end ? (
                <Button
                  variant="outlined" size="small" color="success"
                  onClick={reactivate}
                  disabled={actionLoading === 'reactivate'}
                >
                  Reactivate subscription
                </Button>
              ) : (
                <Button
                  variant="outlined" size="small" color="error"
                  onClick={cancelSubscription}
                  disabled={actionLoading === 'cancel'}
                >
                  Cancel subscription
                </Button>
              )}

              <Button variant="outlined" size="small" onClick={onSubscribe}>
                Change plan
              </Button>
            </>
          )}
        </Stack>
      </Paper>

      {/* Invoice history */}
      {billing?.invoices?.length > 0 && (
        <Paper elevation={0} sx={{ border: '1px solid', borderColor: 'divider', overflow: 'hidden' }}>
          <Box sx={{ px: 2.5, py: 1.5, bgcolor: 'rgba(46,184,126,0.04)' }}>
            <Typography variant="subtitle2" fontWeight={600}>Invoice history</Typography>
          </Box>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontSize: '0.75rem', fontWeight: 600 }}>Date</TableCell>
                <TableCell sx={{ fontSize: '0.75rem', fontWeight: 600 }}>Amount</TableCell>
                <TableCell sx={{ fontSize: '0.75rem', fontWeight: 600 }}>Status</TableCell>
                <TableCell sx={{ fontSize: '0.75rem', fontWeight: 600 }} align="right">PDF</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {billing.invoices.map(inv => (
                <TableRow key={inv.id}>
                  <TableCell sx={{ fontSize: '0.8rem' }}>{inv.date}</TableCell>
                  <TableCell sx={{ fontSize: '0.8rem', fontWeight: 500 }}>
                    {inv.amount.toFixed(2)} {inv.currency}
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={inv.status}
                      size="small"
                      color={inv.status === 'paid' ? 'success' : 'default'}
                      sx={{ fontSize: '0.7rem' }}
                    />
                  </TableCell>
                  <TableCell align="right">
                    {inv.pdf_url && (
                      <Tooltip title="Download PDF">
                        <a href={inv.pdf_url} target="_blank" rel="noopener noreferrer">
                          <OpenInNewIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                        </a>
                      </Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', textAlign: 'center', mt: 2 }}>
        Payments processed securely by Stripe · PCI DSS compliant
      </Typography>
    </Box>
  )
}