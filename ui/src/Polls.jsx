import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box, Paper, Typography, TextField, Button, IconButton,
  LinearProgress, Chip, Stack, Divider, Alert,
  Tooltip, CircularProgress,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import HowToVoteIcon from '@mui/icons-material/HowToVote'
import PollIcon from '@mui/icons-material/Poll'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import RefreshIcon from '@mui/icons-material/Refresh'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY  = import.meta.env.VITE_API_KEY  || ''

const api = axios.create({
  baseURL: API_URL,
  headers: API_KEY ? { 'X-API-Key': API_KEY } : {},
})

const REFRESH_INTERVAL = 15000  // auto-refresh every 15 seconds

// ── Create Poll Form ──────────────────────────────────────────────────────────

function CreatePollForm({ onCreated }) {
  const [open, setOpen]           = useState(false)
  const [question, setQuestion]   = useState('')
  const [options, setOptions]     = useState(['', ''])
  const [createdBy, setCreatedBy] = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')

  const addOption    = () => { if (options.length < 8) setOptions([...options, '']) }
  const removeOption = (i) => { if (options.length > 2) setOptions(options.filter((_, idx) => idx !== i)) }
  const updateOption = (i, val) => { const n = [...options]; n[i] = val; setOptions(n) }

  const handleSubmit = async () => {
    setError('')
    const valid = options.map(o => o.trim()).filter(Boolean)
    if (!question.trim())     return setError('Please enter a question')
    if (!createdBy.trim())    return setError('Please enter your name')
    if (valid.length < 2)     return setError('Add at least 2 options')

    setLoading(true)
    try {
      const { data } = await api.post('/api/polls', {
        question: question.trim(),
        options: valid,
        created_by: createdBy.trim(),
      })
      onCreated(data)
      setQuestion(''); setOptions(['', '']); setCreatedBy(''); setOpen(false)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to create poll')
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <Button
        variant="outlined"
        startIcon={<PollIcon />}
        onClick={() => setOpen(true)}
        fullWidth
        sx={{ py: 1.5, borderStyle: 'dashed', color: 'primary.dark', borderColor: 'primary.light' }}
      >
        Create New Poll
      </Button>
    )
  }

  return (
    <Paper elevation={0} sx={{ p: 2.5, border: '1px solid', borderColor: 'primary.light', bgcolor: 'rgba(46,184,126,0.03)' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Stack direction="row" spacing={1} alignItems="center">
          <PollIcon sx={{ color: 'primary.main', fontSize: 20 }} />
          <Typography variant="subtitle2" fontWeight={600}>New Poll</Typography>
        </Stack>
        <IconButton size="small" onClick={() => setOpen(false)} sx={{ color: 'text.secondary' }}>
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 1.5, py: 0 }}>{error}</Alert>}

      <Stack spacing={1.5}>
        <TextField label="Your name" value={createdBy} onChange={e => setCreatedBy(e.target.value)}
          size="small" placeholder="e.g. Raj Patel" fullWidth />
        <TextField label="Question" value={question} onChange={e => setQuestion(e.target.value)}
          size="small" placeholder="e.g. Best batter this season?" fullWidth multiline maxRows={2} />

        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', mb: 0.75, display: 'block' }}>
            Options (2–8)
          </Typography>
          <Stack spacing={0.75}>
            {options.map((opt, i) => (
              <Stack key={i} direction="row" spacing={0.5} alignItems="center">
                <TextField size="small" placeholder={`Option ${i + 1}`} value={opt}
                  onChange={e => updateOption(i, e.target.value)} fullWidth />
                {options.length > 2 && (
                  <IconButton size="small" onClick={() => removeOption(i)} sx={{ color: 'text.secondary' }}>
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                )}
              </Stack>
            ))}
            {options.length < 8 && (
              <Button size="small" startIcon={<AddIcon />} onClick={addOption}
                sx={{ alignSelf: 'flex-start', color: 'text.secondary', fontSize: '0.75rem' }}>
                Add option
              </Button>
            )}
          </Stack>
        </Box>

        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button size="small" onClick={() => setOpen(false)} sx={{ color: 'text.secondary' }}>
            Cancel
          </Button>
          <Button variant="contained" size="small" onClick={handleSubmit} disabled={loading} sx={{ px: 2.5 }}>
            {loading ? <CircularProgress size={16} sx={{ color: 'inherit' }} /> : 'Create Poll'}
          </Button>
        </Stack>
      </Stack>
    </Paper>
  )
}

// ── Poll Card ─────────────────────────────────────────────────────────────────

function PollCard({ poll: initialPoll, onUpdate }) {
  const [poll, setPoll]         = useState(initialPoll)
  const [voterName, setVoterName] = useState('')
  const [selected, setSelected]   = useState(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const [voted, setVoted]         = useState(false)
  const [copied, setCopied]       = useState(false)
  const [showVoters, setShowVoters] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // Sync when parent updates the poll (from auto-refresh)
  useEffect(() => {
    if (!voted) setPoll(initialPoll)
  }, [initialPoll, voted])

  const refresh = async (silent = false) => {
    if (!silent) setRefreshing(true)
    try {
      const { data } = await api.get(`/api/polls/${poll.poll_id}`)
      setPoll(data)
      if (onUpdate) onUpdate(data)
    } catch { /* ignore */ }
    finally { setRefreshing(false) }
  }

  const handleVote = async () => {
    if (!voterName.trim())  return setError('Please enter your name')
    if (selected === null)  return setError('Please select an option')
    setError(''); setLoading(true)

    // Optimistic update — apply vote immediately in UI
    const optimistic = {
      ...poll,
      options: poll.options.map((o, i) => ({
        ...o,
        votes: i === selected ? [...o.votes, voterName.trim()] : o.votes,
      })),
      total_votes: poll.total_votes + 1,
    }
    setPoll(optimistic)
    setVoted(true)

    try {
      const { data } = await api.post(`/api/polls/${poll.poll_id}/vote`, {
        voter_name: voterName.trim(),
        option_index: selected,
      })
      // Replace with server truth
      setPoll(data)
      if (onUpdate) onUpdate(data)
    } catch (e) {
      // Rollback optimistic update on error
      setPoll(poll)
      setVoted(false)
      setError(e.response?.data?.detail || 'Failed to submit vote')
    } finally {
      setLoading(false)
    }
  }

  const copyId = () => {
    navigator.clipboard.writeText(poll.poll_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const total   = poll.total_votes
  const pct     = (votes) => total === 0 ? 0 : Math.round((votes.length / total) * 100)
  const maxVotes = Math.max(...poll.options.map(o => o.votes.length))

  return (
    <Paper elevation={0} sx={{ p: 2.5, border: '1px solid', borderColor: 'divider' }}>

      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={1.5}>
        <Box sx={{ flex: 1, pr: 1 }}>
          <Typography variant="subtitle2" fontWeight={600}>{poll.question}</Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            by {poll.created_by} · {total} vote{total !== 1 ? 's' : ''}
          </Typography>
        </Box>
        <Stack direction="row" alignItems="center" spacing={0.5}>
          <Tooltip title="Refresh results">
            <IconButton size="small" onClick={() => refresh(false)} sx={{ color: 'text.secondary' }}>
              {refreshing
                ? <CircularProgress size={14} />
                : <RefreshIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
          <Chip label={poll.poll_id} size="small"
            sx={{ fontSize: '0.65rem', fontFamily: 'monospace', bgcolor: 'rgba(46,184,126,0.08)' }} />
          <Tooltip title={copied ? 'Copied!' : 'Copy poll ID'}>
            <IconButton size="small" onClick={copyId} sx={{ color: 'text.secondary' }}>
              {copied
                ? <CheckIcon fontSize="small" sx={{ color: 'primary.main' }} />
                : <ContentCopyIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      <Divider sx={{ mb: 2 }} />

      {/* Options */}
      <Stack spacing={1.5} mb={2}>
        {poll.options.map((opt, i) => {
          const p         = pct(opt.votes)
          const isSelected = selected === i
          const isWinner  = voted && opt.votes.length === maxVotes && maxVotes > 0

          return (
            <Box key={i}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mb={0.5}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ flex: 1, mr: 1 }}>
                  {!voted && (
                    <Box onClick={() => setSelected(i)} sx={{
                      width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                      border: '2px solid', cursor: 'pointer',
                      borderColor: isSelected ? 'primary.main' : 'divider',
                      bgcolor: isSelected ? 'primary.main' : 'transparent',
                      transition: 'all 0.15s',
                    }} />
                  )}
                  <Typography
                    variant="body2"
                    onClick={() => !voted && setSelected(i)}
                    sx={{
                      cursor: !voted ? 'pointer' : 'default',
                      fontWeight: isWinner ? 600 : 400,
                      color: isWinner ? 'primary.dark' : 'text.primary',
                    }}
                  >
                    {opt.text} {isWinner && '🏆'}
                  </Typography>
                </Stack>
                <Stack direction="row" alignItems="center" spacing={0.5}>
                  <Typography variant="caption" sx={{ color: 'text.secondary', minWidth: 28, textAlign: 'right' }}>
                    {p}%
                  </Typography>
                  {opt.votes.length > 0 && (
                    <Tooltip title={opt.votes.join(', ')}>
                      <Chip
                        label={opt.votes.length}
                        size="small"
                        onClick={() => setShowVoters(showVoters === i ? null : i)}
                        sx={{
                          height: 20, fontSize: '0.65rem', cursor: 'pointer',
                          bgcolor: 'rgba(46,184,126,0.1)', color: 'primary.dark',
                        }}
                      />
                    </Tooltip>
                  )}
                </Stack>
              </Stack>

              <LinearProgress
                variant="determinate"
                value={p}
                sx={{
                  height: 6, borderRadius: 3,
                  bgcolor: 'rgba(46,184,126,0.08)',
                  '& .MuiLinearProgress-bar': {
                    bgcolor: isWinner ? 'primary.main' : 'primary.light',
                    borderRadius: 3,
                    transition: 'transform 0.4s ease',   // smooth bar animation
                  },
                }}
              />

              {showVoters === i && opt.votes.length > 0 && (
                <Typography variant="caption" sx={{ color: 'text.secondary', pl: 0.5, mt: 0.25, display: 'block' }}>
                  {opt.votes.join(' · ')}
                </Typography>
              )}
            </Box>
          )
        })}
      </Stack>

      {/* Vote form */}
      {!voted ? (
        <Box>
          {error && <Alert severity="error" sx={{ mb: 1.5, py: 0 }}>{error}</Alert>}
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <TextField
              size="small" placeholder="Your name" value={voterName}
              onChange={e => setVoterName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleVote()}
              sx={{ flex: 1 }}
            />
            <Button
              variant="contained" size="small"
              onClick={handleVote}
              disabled={loading || selected === null || !voterName.trim()}
              startIcon={loading ? <CircularProgress size={14} sx={{ color: 'inherit' }} /> : <HowToVoteIcon />}
              sx={{ height: 40, whiteSpace: 'nowrap' }}
            >
              Vote
            </Button>
          </Stack>
        </Box>
      ) : (
        <Alert severity="success" sx={{ py: 0.5 }}>
          Voted for <strong>{poll.options[selected]?.text}</strong>.
        </Alert>
      )}
    </Paper>
  )
}

// ── Join Poll ─────────────────────────────────────────────────────────────────

function JoinPoll({ onFound }) {
  const [pollId, setPollId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  const handleJoin = async () => {
    if (!pollId.trim()) return
    setError(''); setLoading(true)
    try {
      const { data } = await api.get(`/api/polls/${pollId.trim().toUpperCase()}`)
      onFound(data); setPollId('')
    } catch {
      setError('Poll not found. Check the ID.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Stack spacing={0.5}>
      <Stack direction="row" spacing={1}>
        <TextField
          size="small" placeholder="Enter poll ID e.g. A3F8C2D1"
          value={pollId}
          onChange={e => setPollId(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && handleJoin()}
          sx={{ flex: 1 }}
          inputProps={{ style: { fontFamily: 'monospace', letterSpacing: 2 } }}
        />
        <Button variant="outlined" size="small" onClick={handleJoin}
          disabled={loading || !pollId.trim()} sx={{ height: 40, whiteSpace: 'nowrap' }}>
          {loading ? <CircularProgress size={16} /> : 'Join'}
        </Button>
      </Stack>
      {error && <Typography variant="caption" sx={{ color: 'error.main' }}>{error}</Typography>}
    </Stack>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PollsPage() {
  const [polls, setPolls]     = useState([])
  const [loading, setLoading] = useState(true)
  const timerRef = useRef(null)

  const loadPolls = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const { data } = await api.get('/api/polls')
      setPolls(data)
    } catch {
      if (!silent) setPolls([])
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPolls()
    // Auto-refresh every 15 seconds silently
    timerRef.current = setInterval(() => loadPolls(true), REFRESH_INTERVAL)
    return () => clearInterval(timerRef.current)
  }, [loadPolls])

  const handleCreated = (poll) => {
    setPolls(prev => [poll, ...prev])
  }

  const handleFound = (poll) => {
    setPolls(prev => {
      if (prev.find(p => p.poll_id === poll.poll_id)) return prev
      return [poll, ...prev]
    })
  }

  const handleUpdate = (updated) => {
    setPolls(prev => prev.map(p => p.poll_id === updated.poll_id ? updated : p))
  }

  return (
    <Box sx={{ maxWidth: 600, mx: 'auto', p: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2.5}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <HowToVoteIcon sx={{ color: 'primary.main', fontSize: 26 }} />
          <Box>
            <Typography variant="subtitle1" fontWeight={600}>ARCL Polls</Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Latest 5 polls · auto-refreshes every 15s
            </Typography>
          </Box>
        </Stack>
        <Tooltip title="Refresh now">
          <IconButton size="small" onClick={() => loadPolls()} sx={{ color: 'text.secondary' }}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      <Stack spacing={2.5}>
        <CreatePollForm onCreated={handleCreated} />

        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', mb: 0.75, display: 'block' }}>
            Have a poll ID? Join directly:
          </Typography>
          <JoinPoll onFound={handleFound} />
        </Box>

        <Divider />

        {loading ? (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : polls.length === 0 ? (
          <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center', py: 4 }}>
            No polls yet — create one above!
          </Typography>
        ) : (
          <Stack spacing={2}>
            {polls.map(poll => (
              <PollCard key={poll.poll_id} poll={poll} onUpdate={handleUpdate} />
            ))}
          </Stack>
        )}
      </Stack>
    </Box>
  )
}