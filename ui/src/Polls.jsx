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
import tenant from './tenant'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY  = import.meta.env.VITE_API_KEY  || ''

const api = axios.create({
  baseURL: API_URL,
  headers: API_KEY ? { 'X-API-Key': API_KEY } : {},
})

const REFRESH_INTERVAL = 15000

// ── Tenant strings ────────────────────────────────────────────────────────────

const T = tenant.id === 'geetabitan' ? {
  header:          'গীতবিতান পোল',
  subheader:       'সর্বশেষ ৫টি পোল · প্রতি ১৫ সেকেন্ডে আপডেট',
  newPoll:         'নতুন পোল তৈরি করুন',
  yourName:        'আপনার নাম',
  namePlaceholder: 'যেমন: রাহেলা বেগম',
  question:        'প্রশ্ন',
  questionPlaceholder: 'যেমন: আপনার প্রিয় পর্যায় কোনটি?',
  cancel:          'বাতিল',
  createPoll:      'পোল তৈরি করুন',
  vote:            'ভোট দিন',
  votedFor:        'ভোট দেওয়া হয়েছে',
  joinByID:        'পোল ID দিয়ে যোগ দিন:',
  pollIdPlaceholder: 'পোল ID লিখুন যেমন A3F8C2D1',
  join:            'যোগ দিন',
  pollNotFound:    'পোল পাওয়া যায়নি। ID টি যাচাই করুন।',
  noPolls:         'এখনো কোনো পোল নেই — উপরে তৈরি করুন!',
  errQuestion:     'প্রশ্ন লিখুন',
  errName:         'আপনার নাম লিখুন',
  errOptions:      'কমপক্ষে ২টি বিকল্প দিন',
  errVoteName:     'ভোট দিতে আপনার নাম লিখুন',
  errSelectOption: 'একটি বিকল্প বেছে নিন',
  errCreate:       'পোল তৈরি করা যায়নি',
  errVote:         'ভোট দেওয়া যায়নি',
  addOption:       'বিকল্প যোগ করুন',
  votes:           'ভোট',
  vote1:           'ভোট',
} : {
  header:          'ARCL Polls',
  subheader:       'Latest 5 polls · auto-refreshes every 15s',
  newPoll:         'Create New Poll',
  yourName:        'Your name',
  namePlaceholder: 'e.g. Raj Patel',
  question:        'Question',
  questionPlaceholder: 'e.g. Best batter this season?',
  cancel:          'Cancel',
  createPoll:      'Create Poll',
  vote:            'Vote',
  votedFor:        'Voted for',
  joinByID:        'Have a poll ID? Join directly:',
  pollIdPlaceholder: 'Enter poll ID e.g. A3F8C2D1',
  join:            'Join',
  pollNotFound:    'Poll not found. Check the ID.',
  noPolls:         'No polls yet — create one above!',
  errQuestion:     'Please enter a question',
  errName:         'Please enter your name',
  errOptions:      'Add at least 2 options',
  errVoteName:     'Please enter your name',
  errSelectOption: 'Please select an option',
  errCreate:       'Failed to create poll',
  errVote:         'Failed to submit vote',
  addOption:       'Add option',
  votes:           'votes',
  vote1:           'vote',
}

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
    if (!question.trim())  return setError(T.errQuestion)
    if (!createdBy.trim()) return setError(T.errName)
    if (valid.length < 2)  return setError(T.errOptions)

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
      setError(e.response?.data?.detail || T.errCreate)
    } finally {
      setLoading(false)
    }
  }

  if (!open) return (
    <Button variant="outlined" startIcon={<PollIcon />} onClick={() => setOpen(true)}
      fullWidth sx={{ py:1.5, borderStyle:'dashed', color:'primary.dark', borderColor:'primary.light' }}>
      {T.newPoll}
    </Button>
  )

  return (
    <Paper elevation={0} sx={{ p:2.5, border:'1px solid', borderColor:'primary.light', bgcolor:`${tenant.primaryColor}05` }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Stack direction="row" spacing={1} alignItems="center">
          <PollIcon sx={{ color:'primary.main', fontSize:20 }} />
          <Typography variant="subtitle2" fontWeight={600}>{T.newPoll}</Typography>
        </Stack>
        <IconButton size="small" onClick={() => setOpen(false)} sx={{ color:'text.secondary' }}>
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      </Stack>

      {error && <Alert severity="error" sx={{ mb:1.5, py:0 }}>{error}</Alert>}

      <Stack spacing={1.5}>
        <TextField label={T.yourName} value={createdBy} onChange={e => setCreatedBy(e.target.value)}
          size="small" placeholder={T.namePlaceholder} fullWidth />
        <TextField label={T.question} value={question} onChange={e => setQuestion(e.target.value)}
          size="small" placeholder={T.questionPlaceholder} fullWidth multiline maxRows={2} />

        <Box>
          <Typography variant="caption" sx={{ color:'text.secondary', mb:0.75, display:'block' }}>
            {tenant.id === 'geetabitan' ? 'বিকল্প (২–৮টি)' : 'Options (2–8)'}
          </Typography>
          <Stack spacing={0.75}>
            {options.map((opt, i) => (
              <Stack key={i} direction="row" spacing={0.5} alignItems="center">
                <TextField size="small"
                  placeholder={tenant.id === 'geetabitan' ? `বিকল্প ${i + 1}` : `Option ${i + 1}`}
                  value={opt} onChange={e => updateOption(i, e.target.value)} fullWidth />
                {options.length > 2 && (
                  <IconButton size="small" onClick={() => removeOption(i)} sx={{ color:'text.secondary' }}>
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                )}
              </Stack>
            ))}
            {options.length < 8 && (
              <Button size="small" startIcon={<AddIcon />} onClick={addOption}
                sx={{ alignSelf:'flex-start', color:'text.secondary', fontSize:'0.75rem' }}>
                {T.addOption}
              </Button>
            )}
          </Stack>
        </Box>

        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button size="small" onClick={() => setOpen(false)} sx={{ color:'text.secondary' }}>
            {T.cancel}
          </Button>
          <Button variant="contained" size="small" onClick={handleSubmit} disabled={loading} sx={{ px:2.5 }}>
            {loading ? <CircularProgress size={16} sx={{ color:'inherit' }} /> : T.createPoll}
          </Button>
        </Stack>
      </Stack>
    </Paper>
  )
}

// ── Poll Card ─────────────────────────────────────────────────────────────────

function PollCard({ poll: initialPoll, onUpdate }) {
  const [poll, setPoll]           = useState(initialPoll)
  const [voterName, setVoterName] = useState('')
  const [selected, setSelected]   = useState(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const [voted, setVoted]         = useState(false)
  const [copied, setCopied]       = useState(false)
  const [showVoters, setShowVoters] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => { if (!voted) setPoll(initialPoll) }, [initialPoll, voted])

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
    if (!voterName.trim()) return setError(T.errVoteName)
    if (selected === null) return setError(T.errSelectOption)
    setError(''); setLoading(true)

    const optimistic = {
      ...poll,
      options: poll.options.map((o, i) => ({
        ...o, votes: i === selected ? [...o.votes, voterName.trim()] : o.votes,
      })),
      total_votes: poll.total_votes + 1,
    }
    setPoll(optimistic)
    setVoted(true)

    try {
      const { data } = await api.post(`/api/polls/${poll.poll_id}/vote`, {
        voter_name: voterName.trim(), option_index: selected,
      })
      setPoll(data)
      if (onUpdate) onUpdate(data)
    } catch (e) {
      setPoll(poll); setVoted(false)
      setError(e.response?.data?.detail || T.errVote)
    } finally {
      setLoading(false)
    }
  }

  const copyId = () => {
    navigator.clipboard.writeText(poll.poll_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const total    = poll.total_votes
  const pct      = (votes) => total === 0 ? 0 : Math.round((votes.length / total) * 100)
  const maxVotes = Math.max(...poll.options.map(o => o.votes.length))

  return (
    <Paper elevation={0} sx={{ p:2.5, border:'1px solid', borderColor:'divider' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={1.5}>
        <Box sx={{ flex:1, pr:1 }}>
          <Typography variant="subtitle2" fontWeight={600}>{poll.question}</Typography>
          <Typography variant="caption" sx={{ color:'text.secondary' }}>
            {poll.created_by} · {total} {total !== 1 ? T.votes : T.vote1}
          </Typography>
        </Box>
        <Stack direction="row" alignItems="center" spacing={0.5}>
          {refreshing && <CircularProgress size={14} sx={{ color:'primary.light' }} />}
          <Tooltip title={copied ? 'Copied!' : 'Copy poll ID'}>
            <IconButton size="small" onClick={copyId} sx={{ color:'text.secondary' }}>
              {copied ? <CheckIcon fontSize="small" sx={{ color:'primary.main' }} /> : <ContentCopyIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
          <Tooltip title={tenant.id === 'geetabitan' ? 'আপডেট করুন' : 'Refresh'}>
            <IconButton size="small" onClick={() => refresh()} sx={{ color:'text.secondary' }}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      <Stack spacing={1} mb={2}>
        {poll.options.map((opt, i) => {
          const p        = pct(opt.votes)
          const isWinner = voted && opt.votes.length === maxVotes && opt.votes.length > 0
          return (
            <Box key={i}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mb={0.4}>
                <Stack direction="row" alignItems="center" spacing={0.75}>
                  {!voted && (
                    <Box onClick={() => setSelected(i)} sx={{
                      width:16, height:16, borderRadius:'50%', flexShrink:0, cursor:'pointer',
                      border:`2px solid ${selected === i ? tenant.primaryColor : '#ccc'}`,
                      bgcolor: selected === i ? tenant.primaryColor : 'transparent',
                      transition:'all 0.15s',
                    }} />
                  )}
                  <Typography variant="body2" onClick={() => !voted && setSelected(i)}
                    sx={{
                      cursor: !voted ? 'pointer' : 'default',
                      fontWeight: isWinner ? 600 : 400,
                      color: isWinner ? 'primary.dark' : 'text.primary',
                    }}>
                    {opt.text} {isWinner && '🏆'}
                  </Typography>
                </Stack>
                <Stack direction="row" alignItems="center" spacing={0.5}>
                  <Typography variant="caption" sx={{ color:'text.secondary', minWidth:28, textAlign:'right' }}>
                    {p}%
                  </Typography>
                  {opt.votes.length > 0 && (
                    <Tooltip title={opt.votes.join(', ')}>
                      <Chip label={opt.votes.length} size="small"
                        onClick={() => setShowVoters(showVoters === i ? null : i)}
                        sx={{ height:20, fontSize:'0.65rem', cursor:'pointer',
                              bgcolor:`${tenant.primaryColor}18`, color:'primary.dark' }} />
                    </Tooltip>
                  )}
                </Stack>
              </Stack>

              <LinearProgress variant="determinate" value={p} sx={{
                height:6, borderRadius:3,
                bgcolor:`${tenant.primaryColor}12`,
                '& .MuiLinearProgress-bar': {
                  bgcolor: isWinner ? 'primary.main' : 'primary.light',
                  borderRadius:3, transition:'transform 0.4s ease',
                },
              }} />

              {showVoters === i && opt.votes.length > 0 && (
                <Typography variant="caption" sx={{ color:'text.secondary', pl:0.5, mt:0.25, display:'block' }}>
                  {opt.votes.join(' · ')}
                </Typography>
              )}
            </Box>
          )
        })}
      </Stack>

      {!voted ? (
        <Box>
          {error && <Alert severity="error" sx={{ mb:1.5, py:0 }}>{error}</Alert>}
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <TextField size="small" placeholder={T.namePlaceholder} value={voterName}
              onChange={e => setVoterName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleVote()}
              sx={{ flex:1 }} />
            <Button variant="contained" size="small" onClick={handleVote}
              disabled={loading || selected === null || !voterName.trim()}
              startIcon={loading ? <CircularProgress size={14} sx={{ color:'inherit' }} /> : <HowToVoteIcon />}
              sx={{ height:40, whiteSpace:'nowrap' }}>
              {T.vote}
            </Button>
          </Stack>
        </Box>
      ) : (
        <Alert severity="success" sx={{ py:0.5 }}>
          {T.votedFor} <strong>{poll.options[selected]?.text}</strong>।
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
      setError(T.pollNotFound)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Stack spacing={0.5}>
      <Stack direction="row" spacing={1}>
        <TextField size="small" placeholder={T.pollIdPlaceholder} value={pollId}
          onChange={e => setPollId(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && handleJoin()}
          sx={{ flex:1 }}
          inputProps={{ style:{ fontFamily:'monospace', letterSpacing:2 } }} />
        <Button variant="outlined" size="small" onClick={handleJoin}
          disabled={loading || !pollId.trim()} sx={{ height:40, whiteSpace:'nowrap' }}>
          {loading ? <CircularProgress size={16} /> : T.join}
        </Button>
      </Stack>
      {error && <Typography variant="caption" sx={{ color:'error.main' }}>{error}</Typography>}
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
    timerRef.current = setInterval(() => loadPolls(true), REFRESH_INTERVAL)
    return () => clearInterval(timerRef.current)
  }, [loadPolls])

  const handleCreated = (poll) => setPolls(prev => [poll, ...prev])
  const handleFound   = (poll) => setPolls(prev =>
    prev.find(p => p.poll_id === poll.poll_id) ? prev : [poll, ...prev]
  )
  const handleUpdate  = (updated) => setPolls(prev =>
    prev.map(p => p.poll_id === updated.poll_id ? updated : p)
  )

  return (
    <Box sx={{ maxWidth:600, mx:'auto', p:2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2.5}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <HowToVoteIcon sx={{ color:'primary.main', fontSize:26 }} />
          <Box>
            {/* CHANGE: tenant.id-aware header */}
            <Typography variant="subtitle1" fontWeight={600}>{T.header}</Typography>
            <Typography variant="caption" sx={{ color:'text.secondary' }}>{T.subheader}</Typography>
          </Box>
        </Stack>
        <Tooltip title={tenant.id === 'geetabitan' ? 'আপডেট করুন' : 'Refresh now'}>
          <IconButton size="small" onClick={() => loadPolls()} sx={{ color:'text.secondary' }}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      <Stack spacing={2.5}>
        <CreatePollForm onCreated={handleCreated} />

        <Box>
          <Typography variant="caption" sx={{ color:'text.secondary', mb:0.75, display:'block' }}>
            {T.joinByID}
          </Typography>
          <JoinPoll onFound={handleFound} />
        </Box>

        <Divider />

        {loading ? (
          <Box sx={{ textAlign:'center', py:4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : polls.length === 0 ? (
          <Typography variant="body2" sx={{ color:'text.secondary', textAlign:'center', py:4 }}>
            {T.noPolls}
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