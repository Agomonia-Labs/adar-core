import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, Button, Chip, Stack, Divider,
  CircularProgress, Alert,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

const PLAN_COLORS = {
  basic:     { border: '#C8E8D8', badge: '#EBF7F1', text: '#1A8A5A' },
  standard:  { border: '#2EB87E', badge: '#2EB87E', text: '#fff'    },
  unlimited: { border: '#EF9F27', badge: '#FFF3E0', text: '#BA7517' },
}

export default function Checkout({ token, onBack, onSuccess }) {
  const [plans, setPlans]         = useState([])
  const [selected, setSelected]   = useState('standard')
  const [loading, setLoading]     = useState(false)
  const [redirecting, setRedirecting] = useState(false)
  const [plansLoading, setPlansLoading] = useState(true)
  const [error, setError]         = useState('')

  useEffect(() => {
    axios.get(`${API_URL}/api/payments/plans`)
      .then(({ data }) => setPlans(data.plans || []))
      .catch(() => setError('Could not load plans'))
      .finally(() => setPlansLoading(false))
  }, [])

  const handleSubscribe = async () => {
    setError(''); setLoading(true)
    try {
      const { data } = await axios.post(
        `${API_URL}/api/payments/create-checkout`,
        { plan: selected },
        { headers: { Authorization: `Bearer ${token}` } },
      )
      // Redirect to Stripe hosted checkout page
      // Show branded redirect screen then go to Stripe
      setRedirecting(true)
      await new Promise(r => setTimeout(r, 1400))
      window.location.href = data.checkout_url
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to start checkout')
      setLoading(false)
    }
  }

  const formatAmount = (amount, currency) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount / 100)

  if (redirecting) return (
    <Box sx={{
      minHeight:'100vh',background:'linear-gradient(145deg,#0d1f15 0%,#060f0a 100%)',
      display:'flex',alignItems:'center',justifyContent:'center',
      flexDirection:'column',gap:2,textAlign:'center',p:3
    }}>
      <Box sx={{width:60,height:60,background:'#2EB87E',borderRadius:3,
        display:'flex',alignItems:'center',justifyContent:'center',
        fontSize:'1.3rem',fontWeight:700,color:'#fff',
        boxShadow:'0 0 50px rgba(46,184,126,0.45)',mb:1}}>
        আদর
      </Box>
      <Typography variant="h6" sx={{color:'#fff',fontWeight:600}}>
        Starting your free trial...
      </Typography>
      <Typography sx={{color:'rgba(255,255,255,0.45)',fontSize:'0.88rem',maxWidth:320}}>
        Setting up your 14-day free trial. Taking you to our secure payment page.
      </Typography>
      <CircularProgress sx={{color:'#2EB87E',mt:1}} />
      <Typography sx={{color:'rgba(255,255,255,0.3)',fontSize:'0.74rem',mt:1}}>
        Powered by Stripe · PCI DSS compliant
      </Typography>
    </Box>
  )

  return (
    <Box sx={{ maxWidth: 560, mx: 'auto', p: 3 }}>
      <Stack alignItems="center" spacing={1} mb={4}>
        <Box sx={{
          width: 48, height: 48, borderRadius: '14px',
          bgcolor: 'primary.main',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '1.1rem', fontWeight: 700, color: '#fff',
        }}>আদর</Box>
        <Typography variant="h5" fontWeight={600}>Choose your plan</Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          14-day free trial · Cancel anytime · Auto-renews monthly
        </Typography>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {plansLoading ? (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <CircularProgress size={24} sx={{ color: 'primary.main' }} />
        </Box>
      ) : (
        <Stack spacing={1.5} mb={3}>
          {plans.map(plan => {
            const colors  = PLAN_COLORS[plan.id] || PLAN_COLORS.basic
            const isSelected = selected === plan.id
            const isPopular  = plan.id === 'standard'

            return (
              <Paper
                key={plan.id}
                elevation={0}
                onClick={() => setSelected(plan.id)}
                sx={{
                  p: 2.5, cursor: 'pointer',
                  border: '2px solid',
                  borderColor: isSelected ? colors.border : 'divider',
                  borderRadius: 2,
                  bgcolor: isSelected ? 'rgba(46,184,126,0.03)' : 'background.paper',
                  transition: 'all 0.15s',
                  '&:hover': { borderColor: colors.border },
                  position: 'relative',
                }}
              >
                {isPopular && (
                  <Chip
                    label="Most popular"
                    size="small"
                    sx={{
                      position: 'absolute', top: -12, right: 16,
                      bgcolor: colors.badge, color: colors.text,
                      fontWeight: 600, fontSize: '0.7rem',
                    }}
                  />
                )}

                <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                  <Box>
                    <Stack direction="row" alignItems="center" spacing={1} mb={0.5}>
                      <Box sx={{
                        width: 18, height: 18, borderRadius: '50%',
                        border: '2px solid',
                        borderColor: isSelected ? 'primary.main' : 'divider',
                        bgcolor: isSelected ? 'primary.main' : 'transparent',
                        transition: 'all 0.15s', flexShrink: 0,
                      }} />
                      <Typography variant="subtitle2" fontWeight={600}>
                        {plan.name}
                      </Typography>
                    </Stack>
                    <Typography variant="caption" sx={{ color: 'text.secondary', pl: 3.5 }}>
                      {plan.description}
                    </Typography>
                  </Box>
                  <Box sx={{ textAlign: 'right', flexShrink: 0, pl: 2 }}>
                    <Typography variant="h6" fontWeight={700} sx={{ color: 'text.primary' }}>
                      {formatAmount(plan.amount, plan.currency)}
                    </Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      per {plan.interval}
                    </Typography>
                  </Box>
                </Stack>
              </Paper>
            )
          })}
        </Stack>
      )}

      {/* What's included */}
      <Paper elevation={0} sx={{ p: 2, border: '1px solid', borderColor: 'divider', mb: 3 }}>
        <Typography variant="caption" fontWeight={600} sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
          All plans include:
        </Typography>
        <Stack spacing={0.5}>
          {[
            'Player stats and career history',
            'Team schedules and scorecards',
            'Dismissal analysis',
            'ARCL rules and umpiring guide',
            'Community polls',
            'Auto-renews · Cancel anytime',
          ].map(item => (
            <Stack key={item} direction="row" spacing={1} alignItems="center">
              <CheckIcon sx={{ fontSize: 14, color: 'primary.main' }} />
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>{item}</Typography>
            </Stack>
          ))}
        </Stack>
      </Paper>

      <Button
        variant="contained"
        fullWidth
        onClick={handleSubscribe}
        disabled={loading || plansLoading}
        sx={{ py: 1.5, fontSize: '1rem' }}
      >
        {loading
          ? <CircularProgress size={20} sx={{ color: 'inherit' }} />
          : 'Start free trial · Subscribe'}
      </Button>

      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', textAlign: 'center', mt: 1.5 }}>
        Your card won't be charged during the 14-day trial.
        Cancel before the trial ends and you pay nothing.
      </Typography>

      <Box sx={{ textAlign: 'center', mt: 2 }}>
        <Typography
          variant="body2"
          onClick={onBack}
          sx={{ color: 'text.secondary', cursor: 'pointer', '&:hover': { color: 'primary.main' } }}
        >
          Back
        </Typography>
      </Box>
    </Box>
  )
}