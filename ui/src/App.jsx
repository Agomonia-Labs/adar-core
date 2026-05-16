import { useState, useRef, useEffect, useCallback } from 'react'
import {
  ThemeProvider, CssBaseline, Box, Paper, Typography,
  TextField, IconButton, Chip, Avatar, Divider, Button,
  CircularProgress, Tooltip, Stack, Tab, Tabs,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import MicIcon from '@mui/icons-material/Mic'
import MicOffIcon from '@mui/icons-material/MicOff'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import axios from 'axios'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { v4 as uuidv4 } from 'uuid'
import theme from './theme'
import tenant from './tenant'
import { useSpeech } from './hooks/useSpeech'
import PollsPage from './Polls'
import Login from './Login'
import Checkout from './Checkout'
import Billing from './Billing'
import Register from './Register'
import AdminDashboard from './AdminDashboard'


// ── Handle Stripe payment return BEFORE React mounts ─────────────────────────
// This runs synchronously so adar_status is correct when useState initialises.
;(function handlePaymentReturn() {
  try {
    const p = new URLSearchParams(window.location.search)
    if (p.get('payment') === 'success') {
      localStorage.setItem('adar_status', 'active')
      window.history.replaceState({}, '', window.location.pathname)
      // Fire activate to backend (non-blocking, best-effort)
      const token   = localStorage.getItem('adar_token')
      const apiUrl  = import.meta.env.VITE_API_URL || ''
      const apiKey  = import.meta.env.VITE_API_KEY  || ''
      if (token) {
        const headers = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }
        if (apiKey) headers['X-API-Key'] = apiKey
        fetch(apiUrl + '/api/payments/activate', { method: 'POST', headers })
          .then(r => r.json())
          .then(d => console.log('[Payment] Activated:', d))
          .catch(e => console.warn('[Payment] Activate error (non-fatal):', e))
      }
    }
    if (p.get('payment') === 'cancelled') {
      window.history.replaceState({}, '', window.location.pathname)
    }
  } catch (e) { /* never crash */ }
})()


const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

// ── Set page title from tenant ────────────────────────────────────────────────
document.title = `আদর · ${tenant.appTitle}`

// ── Suggested questions from tenant ──────────────────────────────────────────
// Pick 6 random suggested questions each session so users discover the full scope
const SUGGESTED_QUESTIONS = (() => {
  const all = [...(tenant.suggestedQuestions || [])]
  for (let i = all.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [all[i], all[j]] = [all[j], all[i]]
  }
  return all.slice(0, 6)
})()


function useChartData(content, hint = '') {
  const text = content || ''
  const result = { bat: null, bowl: null }
  const lines = text.split('\n')
  let tableLines = []
  const processTable = () => {
    if (tableLines.length < 3) { tableLines = []; return }
    const hdrs = tableLines[0].split('|').map(s => s.trim()).filter(Boolean)
    const rows  = tableLines.slice(2)
      .map(l => l.split('|').map(s => s.trim()).filter(Boolean))
      .filter(r => r.length > 1)
    if (!rows.length) { tableLines = []; return }
    const h  = hdrs.map(x => x.toLowerCase()).join(' ')
    const ni = hdrs.findIndex(x => /player|name/i.test(x))
    if (ni < 0) { tableLines = []; return }
    const extract = (...kws) => {
      const vi = hdrs.findIndex(x => kws.some(k => x.toLowerCase().includes(k)))
      if (vi < 0) return null
      return rows.map(r => ({
        name: (r[ni]||'').replace(/[*†]/g,'').trim().split(' ').slice(0,2).join(' '),
        v: parseFloat(r[vi])||0
      })).filter(d => d.name && d.v > 0).sort((a,b)=>b.v-a.v).slice(0,10)
    }
    if (!result.bat && /run/.test(h) && /(ball|sr|inning|four)/.test(h)) {
      const h2 = hint.toLowerCase()
      if (/(strike.?rate|\bsr\b)/.test(h2))       result.bat = extract('strike rate','sr')
      else if (/\bball/.test(h2))                  result.bat = extract('ball')
      else if (/\bfour/.test(h2))                  result.bat = extract('four')
      else if (/\bsix/.test(h2))                   result.bat = extract('six','sixs')
      else if (/\binning/.test(h2))                result.bat = extract('inning')
      else                                          result.bat = extract('run','total_run')
    }
    if (!result.bowl && /(wicket|wkt)/.test(h) && /over/.test(h)) {
      const h2 = hint.toLowerCase()
      if (/eco/.test(h2))                           result.bowl = extract('eco rate','economy','eco')
      else if (/average|avg/.test(h2))              result.bowl = extract('average','avg')
      else if (/over/.test(h2))                     result.bowl = extract('over')
      else                                          result.bowl = extract('wicket','wkt')
    }
    tableLines = []
  }
  for (const line of lines) {
    if (line.includes('|')) {
      tableLines.push(line)
    } else {
      if (tableLines.length) processTable()
    }
  }
  if (tableLines.length) processTable()
  return result
}

function CSSBarChart({ data, color, unit = '' }) {
  const max = Math.max(...data.map(d => d.v))
  return (
    <Box sx={{ mt: 0.5 }}>
      {data.map((d, i) => (
        <Box key={i} sx={{ display:'flex', alignItems:'center', mb:'3px', gap:1 }}>
          <Box sx={{ width:110, fontSize:'0.72rem', textAlign:'right', color:'text.primary', flexShrink:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
            {d.name}
          </Box>
          <Box sx={{ flex:1, bgcolor:'rgba(0,0,0,0.06)', borderRadius:1, height:16, overflow:'hidden' }}>
            <Box sx={{ width:`${Math.round(d.v/max*100)}%`, height:'100%', bgcolor:color, borderRadius:1, transition:'width 0.4s ease', minWidth:2 }}/>
          </Box>
          <Box sx={{ width:44, fontSize:'0.7rem', color:'text.secondary', flexShrink:0 }}>{d.v}{unit?' '+unit:''}</Box>
        </Box>
      ))}
    </Box>
  )
}

function StatsCharts({ content, autoShow, hint = '' }) {
  const [mode, setMode] = useState(autoShow ? 'bat' : null)
  const { bat, bowl }   = useChartData(content, hint)
  if (!bat && !bowl) return null
  return (
    <Box sx={{ mt:0.75 }}>
      <Box sx={{ display:'flex', gap:0.75, mb: mode ? 1 : 0 }}>
        {bat && (
          <Box component="span" onClick={() => setMode(m => m==='bat' ? null : 'bat')}
            sx={{ cursor:'pointer', px:1, py:0.25, borderRadius:1, fontSize:'0.68rem',
                  border:`1px solid ${tenant.primaryColor}66`,
                  bgcolor: mode==='bat' ? `${tenant.primaryColor}22` : 'transparent',
                  color: tenant.primaryDark,
                  userSelect:'none', '&:hover':{ bgcolor:`${tenant.primaryColor}18` } }}>
            📊 Batting
          </Box>
        )}
        {bowl && (
          <Box component="span" onClick={() => setMode(m => m==='bowl' ? null : 'bowl')}
            sx={{ cursor:'pointer', px:1, py:0.25, borderRadius:1, fontSize:'0.68rem',
                  border:`1px solid ${tenant.accentColor}66`,
                  bgcolor: mode==='bowl' ? `${tenant.accentColor}22` : 'transparent',
                  color: tenant.accentDark,
                  userSelect:'none', '&:hover':{ bgcolor:`${tenant.accentColor}18` } }}>
            📊 Bowling
          </Box>
        )}
      </Box>
      {mode==='bat'  && bat  && <CSSBarChart data={bat}  color={tenant.primaryColor}/>}
      {mode==='bowl' && bowl && <CSSBarChart data={bowl} color={tenant.accentColor}/>}
    </Box>
  )
}


function MessageBubble({ msg, prevContent = '' }) {
  const isUser = msg.role === 'user'
  return (
    <Box sx={{ display:'flex', flexDirection: isUser ? 'row-reverse' : 'row', gap:1.5, alignItems:'flex-start', mb:2 }}>
      <Avatar sx={{ width:32, height:32, flexShrink:0, bgcolor: isUser ? 'secondary.main' : 'primary.main' }}>
        {isUser ? <PersonOutlineIcon sx={{ fontSize:18 }} /> : <SmartToyOutlinedIcon sx={{ fontSize:18 }} />}
      </Avatar>

      <Paper elevation={0} sx={{
        px:2, py:1.5, maxWidth:'78%',
        background: isUser ? `${tenant.accentColor}14` : `${tenant.primaryColor}12`,
        border: '1px solid',
        borderColor: isUser ? `${tenant.accentColor}40` : `${tenant.primaryColor}40`,
        borderRadius: isUser ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
      }}>
        <Box sx={{
          fontSize:'0.875rem', lineHeight:1.7, color:'text.primary',
          '& p': { margin:'0 0 6px 0' },
          '& p:last-child': { margin:0 },
          '& table': { borderCollapse:'collapse', width:'100%', fontSize:'0.8rem', my:1 },
          '& th': { bgcolor:`${tenant.primaryColor}20`, color:'primary.dark', fontWeight:600,
                    padding:'5px 10px', border:'1px solid', borderColor:`${tenant.primaryColor}40`, textAlign:'left' },
          '& td': { padding:'4px 10px', border:'1px solid', borderColor:'divider' },
          '& tr:nth-of-type(even) td': { bgcolor:`${tenant.primaryColor}08` },
          '& strong': { color:'primary.dark', fontWeight:600 },
          '& code': { fontFamily:'monospace', bgcolor:`${tenant.primaryColor}14`, px:'4px', borderRadius:'3px', fontSize:'0.8rem' },
          '& ul, & ol': { pl:2.5, my:0.5 },
          '& li': { mb:0.25 },
        }}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer"
                   style={{ color: tenant.primaryDark }}>
                  {children}
                </a>
              )
            }}
          >{msg.content}</ReactMarkdown>
        </Box>

        <StatsCharts content={msg.content} autoShow={/chart|graph|bar|visual|plot/i.test(prevContent)} hint={prevContent} />

        {msg.eval && (
          <Box sx={{ mt:0.75, display:'flex', alignItems:'center', gap:0.75, flexWrap:'wrap' }}>
            {[
              { label:'যথার্থতা',  val: msg.eval.scores?.accuracy },
              { label:'সম্পূর্ণতা', val: msg.eval.scores?.completeness },
              { label:'প্রাসঙ্গিক', val: msg.eval.scores?.relevance },
              { label:'বিন্যাস',    val: msg.eval.scores?.format },
            ].map(({ label, val }) => (
              <Box key={label} sx={{
                px:0.75, py:0.2, borderRadius:0.75, fontSize:'0.62rem', fontWeight:600,
                bgcolor: val>=4?`${tenant.primaryColor}18`:val>=3?`${tenant.accentColor}18`:'rgba(226,75,74,0.1)',
                color:   val>=4?tenant.primaryDark:val>=3?tenant.accentDark:'#C62828',
                border:'1px solid',
                borderColor: val>=4?`${tenant.primaryColor}50`:val>=3?`${tenant.accentColor}50`:'rgba(226,75,74,0.3)',
              }}>
                {label} {val}/৫
              </Box>
            ))}
            <Box sx={{ px:0.75, py:0.2, borderRadius:0.75, fontSize:'0.62rem', fontWeight:700,
                       bgcolor:`${tenant.primaryColor}25`, color:tenant.primaryDark,
                       border:`1px solid ${tenant.primaryColor}60` }}>
              সামগ্রিক {msg.eval.scores?.overall}/৫
            </Box>
            {msg.eval.explanation && (
              <Box component="span" sx={{ fontSize:'0.62rem', color:'text.secondary', ml:0.5 }}>
                — {msg.eval.explanation}
              </Box>
            )}
          </Box>
        )}
        <Typography variant="caption" sx={{ color:'text.secondary', mt:0.5, display:'block' }}>
          {new Date(msg.timestamp).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })}
        </Typography>
      </Paper>
    </Box>
  )
}

function TypingIndicator() {
  return (
    <Box sx={{ display:'flex', gap:1.5, alignItems:'flex-start', mb:2 }}>
      <Avatar sx={{ width:32, height:32, bgcolor:'primary.main', flexShrink:0 }}>
        <SmartToyOutlinedIcon sx={{ fontSize:18 }} />
      </Avatar>
      <Paper elevation={0} sx={{
        px:2, py:1.5,
        background: `${tenant.primaryColor}12`,
        border: `1px solid ${tenant.primaryColor}40`,
        borderRadius:'4px 16px 16px 16px',
        display:'flex', alignItems:'center', gap:1,
      }}>
        <CircularProgress size={12} thickness={5} sx={{ color:'primary.main' }} />
        <Typography variant="caption" sx={{ color:'text.secondary' }}>
          {tenant.typingText}
        </Typography>
      </Paper>
    </Box>
  )
}

function ChatTab() {
  // ── Speech to text ──────────────────────────────────────────────────────
  const { listening, supported, startListening, stopListening } = useSpeech({
    lang:     'bn-IN',
    onResult: (text) => {
      if (text.trim()) sendMessage(text.trim())
    },
    onError: (e) => {
      console.warn('Speech error:', e)
      // Show error briefly in input field so user knows what happened
      setInput('⚠ ' + e)
      setTimeout(() => setInput(''), 3000)
    },
  })
  const [messages, setMessages] = useState([{
    role:'assistant',
    content: tenant.welcomeMessage,
    timestamp: Date.now(),
  }])
  const [input, setInput]         = useState('')
  const [loading, setLoading]     = useState(false)
  const sendingRef                = useRef(false)
  const [sessionId, setSessionId] = useState(null)
  const [userId]                  = useState(() => `user_${uuidv4().slice(0,8)}`)
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior:'smooth' }) }, [messages, loading])

  const sendMessage = useCallback(async (text) => {
    const message = text || input.trim()
    if (!message || loading || sendingRef.current) return
    sendingRef.current = true
    setInput('')
    setMessages(prev => [...prev, { role:'user', content:message, timestamp:Date.now() }])
    setLoading(true)
    try {
      const token = localStorage.getItem('adar_token') || ''
      const headers = {}
      if (API_KEY) headers['X-API-Key']     = API_KEY
      if (token)   headers['Authorization'] = `Bearer ${token}`
      const { data } = await axios.post(
        `${API_URL}/api/chat`,
        { message, user_id:userId, session_id:sessionId },
        { headers },
      )
      setSessionId(data.session_id)
      setMessages(prev => [...prev, {
        role:'assistant', content:data.response, timestamp:Date.now(), eval:data.eval||null,
      }])
      setUsage(prev => prev ? { ...prev, used_today:(prev.used_today||0)+1 } : prev)
    } catch (err) {
      console.error('Chat error:', err)
      setMessages(prev => {
        const last = prev[prev.length-1]
        if (last && last.role==='assistant' && last.content !== 'Sorry, I encountered an error. Please try again.')
          return prev
        return [...prev, { role:'assistant', content:'Sorry, I encountered an error. Please try again.', timestamp:Date.now() }]
      })
    } finally {
      setLoading(false)
      sendingRef.current = false
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [input, loading, sessionId, userId])

  const handleKeyDown = (e) => {
    if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const clearSession = async () => {
    if (sessionId) {
      try {
        await axios.delete(`${API_URL}/api/sessions/${sessionId}?user_id=${userId}`,
          { headers: API_KEY ? { 'X-API-Key':API_KEY } : {} })
      } catch { /* ignore */ }
    }
    setSessionId(null)
    setMessages([{ role:'assistant', content:tenant.clearMessage, timestamp:Date.now() }])
  }

  return (
    <>
      <Box sx={{ flex:1, overflowY:'auto', px:2.5, py:2 }}>
        {messages.map((msg,i) => <MessageBubble key={i} msg={msg} prevContent={messages[i-1]?.content||''} />)}
        {loading && <TypingIndicator />}
        <div ref={bottomRef} />
      </Box>

      {messages.length <= 1 && (
        <Box sx={{ px:2.5, pb:1.5 }}>
          <Typography variant="caption" sx={{ color:'text.secondary', mb:1, display:'block' }}>
            Try asking:
          </Typography>
          <Box sx={{ display:'flex', flexWrap:'wrap', gap:1 }}>
            {SUGGESTED_QUESTIONS.map(q => (
              <Chip key={q} label={q} size="small" variant="outlined"
                onClick={() => sendMessage(q)}
                sx={{
                  cursor:'pointer', fontSize:'0.72rem',
                  borderColor:tenant.divider, color:'text.secondary', bgcolor:tenant.bgDefault,
                  '&:hover':{ borderColor:'primary.main', color:'primary.dark', bgcolor:`${tenant.primaryColor}20` },
                }}
              />
            ))}
          </Box>
        </Box>
      )}

      <Divider />

      {sessionId && (
        <Box sx={{ px:2.5, pt:1, display:'flex', justifyContent:'flex-end' }}>
          <Tooltip title="Clear session">
            <IconButton size="small" onClick={clearSession} sx={{ color:'text.secondary' }}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      )}

      <Box sx={{ px:2.5, py:2, bgcolor:'background.paper' }}>
        <Box sx={{ display:'flex', gap:1.5, alignItems:'flex-end' }}>
          <TextField
            inputRef={inputRef} fullWidth multiline maxRows={4} variant="outlined"
            placeholder={tenant.placeholder}
            value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown} disabled={loading} size="small"
            sx={{
              '& .MuiOutlinedInput-root': {
                bgcolor:'background.default',
                '& fieldset':            { borderColor:tenant.divider },
                '&:hover fieldset':      { borderColor:'primary.light' },
                '&.Mui-focused fieldset':{ borderColor:'primary.main' },
              },
            }}
          />
          {supported && (
            <IconButton
              onClick={listening ? stopListening : startListening}
              title={listening ? 'থামুন' : 'বাংলায় বলুন'}
              sx={{
                color:     listening ? 'error.main' : 'primary.main',
                flexShrink: 0,
                animation: listening ? 'micPulse 1s ease-in-out infinite' : 'none',
                '@keyframes micPulse': {
                  '0%,100%': { opacity: 1 },
                  '50%':     { opacity: 0.3 },
                },
              }}>
              {listening ? <MicOffIcon /> : <MicIcon />}
            </IconButton>
          )}
          <IconButton onClick={() => sendMessage()} disabled={!input.trim()||loading}
            sx={{
              bgcolor:'primary.main', color:'#fff', width:40, height:40, flexShrink:0,
              '&:hover':{ bgcolor:'primary.dark' },
              '&.Mui-disabled':{ bgcolor:tenant.divider, color:tenant.textSecondary },
            }}>
            <SendIcon fontSize="small" />
          </IconButton>
        </Box>
        <Typography variant="caption" sx={{ color:'text.secondary', mt:0.75, display:'block', textAlign:'center' }}>
          {tenant.footerText}
        </Typography>
      </Box>
    </>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState(0)
  const [page, setPage]           = useState(() => {
    const token  = localStorage.getItem('adar_token')
    const role   = localStorage.getItem('adar_role')
    const status = localStorage.getItem('adar_status')
    if (token) {
      if (role === 'admin') return 'admin'
      if (status === 'pending_payment') return 'checkout'
      return 'chat'
    }
    return 'login'
  })
  const [token, setToken]       = useState(() => localStorage.getItem('adar_token') || '')
  const [usage, setUsage]       = useState(null)
  const [ingestStatus, setIngestStatus] = useState(null)
  const [teamName, setTeamName] = useState(() => localStorage.getItem('adar_team_name') || '')

  // Auto-logout after 30 minutes
  useEffect(() => {
    if (page !== 'chat' && page !== 'admin') return
    const THIRTY_MIN = 30 * 60 * 1000
    const timer = setTimeout(() => {
      handleLogout()
      alert('Your session has expired after 30 minutes. Please log in again.')
    }, THIRTY_MIN)
    return () => clearTimeout(timer)
  }, [page])

  // Stripe return handled by handlePaymentReturn() above (runs before React mounts)
  // If page is still 'checkout' but status is 'active', correct it
  useEffect(() => {
    if (page === 'checkout' && localStorage.getItem('adar_status') === 'active') {
      setPage('chat')
    }
  }, [])

  const handleLogin = (data, redirect) => {
    if (redirect === 'register') { setPage('register'); return }
    if (!data) return
    setToken(data.access_token)
    setTeamName(data.team_name)
    // Always sync adar_status from server so localStorage matches Firestore
    if (data.status) localStorage.setItem('adar_status', data.status)
    setTimeout(fetchUsage, 500)
    if (data.status === 'pending_payment') {
      setPage('checkout')
    } else {
      setPage(data.role === 'admin' ? 'admin' : 'chat')
    }
  }

  // Poll ingestion status
  useEffect(() => {
    const role = localStorage.getItem('adar_role')
    if (page !== 'chat' || role === 'admin') return
    const checkIngest = async () => {
      try {
        const t = localStorage.getItem('adar_token')
        if (!t) return
        const headers = { Authorization:`Bearer ${t}` }
        if (API_KEY) headers['X-API-Key'] = API_KEY
        const res = await fetch(`${API_URL}/api/ingestion/status`, { headers })
        if (res.ok) {
          const data = await res.json()
          setIngestStatus(data.status === 'complete' ? null : data)
        }
      } catch { /* non-fatal */ }
    }
    checkIngest()
    const interval = setInterval(checkIngest, 30 * 1000)
    return () => clearInterval(interval)
  }, [page])

  // Poll usage every 2 minutes
  useEffect(() => {
    const role = localStorage.getItem('adar_role')
    if (page !== 'chat' || role === 'admin') return
    fetchUsage()
    const interval = setInterval(fetchUsage, 2 * 60 * 1000)
    return () => clearInterval(interval)
  }, [page])

  const fetchUsage = async () => {
    const t    = localStorage.getItem('adar_token')
    const role = localStorage.getItem('adar_role')
    if (!t || role === 'admin') return
    try {
      const headers = { Authorization:`Bearer ${t}` }
      if (API_KEY) headers['X-API-Key'] = API_KEY
      const res = await fetch(`${API_URL}/api/usage`, { headers })
      if (res.ok) { const data = await res.json(); setUsage(data) }
    } catch (e) { console.error('Usage fetch error:', e) }
  }

  const handleLogout = () => {
    localStorage.removeItem('adar_token')
    localStorage.removeItem('adar_team_id')
    localStorage.removeItem('adar_team_name')
    localStorage.removeItem('adar_role')
    localStorage.removeItem('adar_status')
    localStorage.removeItem('adar_login_time')
    setToken(''); setTeamName(''); setPage('login')
  }

  // Subscription wall
  if (page === 'chat' && localStorage.getItem('adar_status') === 'pending_payment') {
    return (
      <ThemeProvider theme={theme}><CssBaseline />
        <Box sx={{
          minHeight:'100vh', background:'linear-gradient(145deg,#0d1f15,#060f0a)',
          display:'flex', alignItems:'center', justifyContent:'center',
          flexDirection:'column', gap:2, textAlign:'center', p:3
        }}>
          <Box sx={{ width:60, height:60, background:tenant.primaryColor, borderRadius:3,
            display:'flex', alignItems:'center', justifyContent:'center',
            fontSize:'1.3rem', fontWeight:700, color:'#fff', mb:1 }}>আদর</Box>
          <Typography variant="h6" sx={{ color:'#fff', fontWeight:600 }}>Subscription required</Typography>
          <Typography sx={{ color:'rgba(255,255,255,0.5)', fontSize:'0.9rem', maxWidth:340 }}>
            Please complete your subscription to start using Adar.
            Your 14-day free trial begins immediately after subscribing.
          </Typography>
          <Button variant="contained" onClick={() => setPage('checkout')}
            sx={{ background:tenant.primaryColor, '&:hover':{ background:tenant.primaryDark }, mt:1 }}>
            Subscribe now — free trial
          </Button>
          <Button onClick={handleLogout} sx={{ color:'rgba(255,255,255,0.4)', fontSize:'0.8rem' }}>Sign out</Button>
        </Box>
      </ThemeProvider>
    )
  }

  if (page === 'login')    return <ThemeProvider theme={theme}><CssBaseline /><Login onLogin={handleLogin} /></ThemeProvider>
  if (page === 'register') return <ThemeProvider theme={theme}><CssBaseline /><Register onBack={() => setPage('login')} /></ThemeProvider>
  if (page === 'admin')    return <ThemeProvider theme={theme}><CssBaseline /><AdminDashboard token={token} onLogout={handleLogout} /></ThemeProvider>
  if (page === 'checkout') return <ThemeProvider theme={theme}><CssBaseline /><Checkout token={token} onBack={() => setPage('chat')} onSuccess={() => { localStorage.setItem('adar_status','active'); setPage('chat') }} /></ThemeProvider>
  if (page === 'billing')  return <ThemeProvider theme={theme}><CssBaseline /><Billing token={token} onSubscribe={() => setPage('checkout')} onBack={() => setPage('chat')} /></ThemeProvider>

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ height:'100dvh', display:'flex', flexDirection:'column', bgcolor:'background.default', maxWidth:800, mx:'auto' }}>

        {/* Header */}
        <Paper elevation={0} sx={{ px:2.5, py:1.5, borderRadius:0, borderBottom:'1px solid', borderColor:'divider', display:'flex', alignItems:'center', bgcolor:'background.paper' }}>
          <Stack direction="row" alignItems="center" spacing={1.5} sx={{ flex:1 }}>
            <Box sx={{
              width:36, height:36, borderRadius:'10px', bgcolor:'primary.main',
              display:'flex', alignItems:'center', justifyContent:'center',
              fontSize:'0.8rem', fontWeight:700, color:'#fff', letterSpacing:'-0.5px', userSelect:'none',
            }}>
              {tenant.logoText}
            </Box>
            <Box sx={{ flex:1 }}>
              <Typography variant="subtitle1" fontWeight={600} lineHeight={1.2} sx={{ color:'text.primary' }}>
                {tenant.appTitle}
              </Typography>
              <Typography variant="caption" sx={{ color:'text.secondary' }}>
                {teamName || tenant.subtitle}
              </Typography>
            </Box>
            <Box onClick={() => setPage('billing')} sx={{
              cursor:'pointer', px:1.5, py:0.5, borderRadius:1.5,
              border:'1px solid', borderColor:'divider', fontSize:'0.82rem',
              fontWeight:600, color:'text.secondary', userSelect:'none',
              display:'flex', alignItems:'center', gap:0.5,
              '&:hover':{ borderColor:'primary.main', color:'primary.main', bgcolor:`${tenant.primaryColor}10` },
            }}>
              <span style={{ fontSize:'1rem' }}>💳</span> Billing
            </Box>
            {usage !== null && (
              <Box sx={{
                px:1.2, py:0.3, borderRadius:2, border:'1px solid',
                borderColor:(usage.used_today||0)>=usage.daily_quota?'error.main':(usage.used_today||0)>=usage.daily_quota*0.8?'warning.main':'primary.main',
                fontSize:'0.7rem', fontWeight:600, lineHeight:1.4, whiteSpace:'nowrap',
                color:(usage.used_today||0)>=usage.daily_quota?'error.main':(usage.used_today||0)>=usage.daily_quota*0.8?'warning.main':'primary.main',
              }}>
                {usage.used_today||0}/{usage.daily_quota} msgs
              </Box>
            )}
            <Tooltip title="Sign out">
              <IconButton size="small" onClick={handleLogout}
                sx={{ color:'text.secondary', '&:hover':{ color:'error.main', bgcolor:'rgba(211,47,47,0.08)' } }}>
                <LogoutIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Paper>

        {/* Tabs */}
        <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)} sx={{
          borderBottom:'1px solid', borderColor:'divider', bgcolor:'background.paper', minHeight:42,
          '& .MuiTab-root':{ minHeight:42, fontSize:'0.8rem', textTransform:'none', fontWeight:500 },
        }}>
          <Tab label="💬 Chat" />
          <Tab label="📊 Polls" />
        </Tabs>

        {activeTab === 0 ? (
          <Box sx={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
            <ChatTab />
          </Box>
        ) : (
          <Box sx={{ flex:1, overflowY:'auto' }}>
            <PollsPage />
          </Box>
        )}
      </Box>
    </ThemeProvider>
  )
}