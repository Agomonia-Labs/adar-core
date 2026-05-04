import { useState, useRef, useEffect, useCallback } from 'react'
import {
  ThemeProvider, CssBaseline, Box, Paper, Typography,
  TextField, IconButton, Chip, Avatar, Divider,
  CircularProgress, Tooltip, Stack, Tab, Tabs,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import SportsCricketIcon from '@mui/icons-material/SportsCricket'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import LogoutIcon from '@mui/icons-material/Logout'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import axios from 'axios'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { v4 as uuidv4 } from 'uuid'
import theme from './theme'
import PollsPage from './Polls'
import Login from './Login'
import Checkout from './Checkout'
import Billing from './Billing'
import Register from './Register'
import AdminDashboard from './AdminDashboard'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

const SUGGESTED_QUESTIONS = [
  'What is the wide rule in ARCL?',
  'Can a player play for two teams in the same season?',
  'Show Agomoni Tigers players in Spring 2026',
  'Show Agomoni Tigers schedule in Spring 2026',
  'How does the points table work?',
  'Who scored the most runs in Div H?',
]


function useChartData(content, hint = '') {
  const text = content || ''
  const result = { bat: null, bowl: null }
  // Collect all consecutive lines that contain | as one table block
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
            sx={{ cursor:'pointer', px:1, py:0.25, borderRadius:1, fontSize:'0.68rem', border:'1px solid rgba(46,184,126,0.4)',
                  bgcolor: mode==='bat' ? 'rgba(46,184,126,0.12)' : 'transparent', color:'#1A8A5A',
                  userSelect:'none', '&:hover':{ bgcolor:'rgba(46,184,126,0.1)' } }}>
            📊 Batting
          </Box>
        )}
        {bowl && (
          <Box component="span" onClick={() => setMode(m => m==='bowl' ? null : 'bowl')}
            sx={{ cursor:'pointer', px:1, py:0.25, borderRadius:1, fontSize:'0.68rem', border:'1px solid rgba(239,159,39,0.4)',
                  bgcolor: mode==='bowl' ? 'rgba(239,159,39,0.12)' : 'transparent', color:'#BA7517',
                  userSelect:'none', '&:hover':{ bgcolor:'rgba(239,159,39,0.1)' } }}>
            📊 Bowling
          </Box>
        )}
      </Box>
      {mode==='bat'  && bat  && <CSSBarChart data={bat}  color="#2EB87E"/>}
      {mode==='bowl' && bowl && <CSSBarChart data={bowl} color="#EF9F27"/>}
    </Box>
  )
}


function MessageBubble({ msg, prevContent = '' }) {
  const isUser = msg.role === 'user'
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        gap: 1.5,
        alignItems: 'flex-start',
        mb: 2,
      }}
    >
      <Avatar
        sx={{
          width: 32, height: 32, flexShrink: 0,
          bgcolor: isUser ? 'secondary.main' : 'primary.main',
        }}
      >
        {isUser
          ? <PersonOutlineIcon sx={{ fontSize: 18 }} />
          : <SmartToyOutlinedIcon sx={{ fontSize: 18 }} />}
      </Avatar>

      <Paper
        elevation={0}
        sx={{
          px: 2, py: 1.5,
          maxWidth: '78%',
          background: isUser ? 'rgba(239,159,39,0.08)' : 'rgba(46,184,126,0.07)',
          border: '1px solid',
          borderColor: isUser ? 'rgba(239,159,39,0.25)' : 'rgba(46,184,126,0.25)',
          borderRadius: isUser ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
        }}
      >
        <Box sx={{
          fontSize: '0.875rem',
          lineHeight: 1.7,
          color: 'text.primary',
          '& p': { margin: '0 0 6px 0' },
          '& p:last-child': { margin: 0 },
          '& table': {
            borderCollapse: 'collapse',
            width: '100%',
            fontSize: '0.8rem',
            my: 1,
          },
          '& th': {
            bgcolor: 'rgba(46,184,126,0.12)',
            color: 'primary.dark',
            fontWeight: 600,
            padding: '5px 10px',
            border: '1px solid',
            borderColor: 'rgba(46,184,126,0.25)',
            textAlign: 'left',
          },
          '& td': {
            padding: '4px 10px',
            border: '1px solid',
            borderColor: 'divider',
          },
          '& tr:nth-of-type(even) td': {
            bgcolor: 'rgba(46,184,126,0.04)',
          },
          '& strong': { color: 'primary.dark', fontWeight: 600 },
          '& code': {
            fontFamily: 'monospace',
            bgcolor: 'rgba(46,184,126,0.08)',
            px: '4px',
            borderRadius: '3px',
            fontSize: '0.8rem',
          },
          '& ul, & ol': { pl: 2.5, my: 0.5 },
          '& li': { mb: 0.25 },
        }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {msg.content}
          </ReactMarkdown>
        </Box>

        <StatsCharts
          content={msg.content}
          autoShow={/chart|graph|bar|visual|plot/i.test(prevContent)}
          hint={prevContent}
        />
        {msg.eval && (
          <Box sx={{ mt: 0.75, display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
            {[
              { label: 'Accuracy',     val: msg.eval.scores?.accuracy },
              { label: 'Complete',     val: msg.eval.scores?.completeness },
              { label: 'Relevance',    val: msg.eval.scores?.relevance },
              { label: 'Format',       val: msg.eval.scores?.format },
            ].map(({ label, val }) => (
              <Box key={label} sx={{
                px: 0.75, py: 0.2,
                borderRadius: 0.75,
                fontSize: '0.62rem',
                fontWeight: 600,
                bgcolor: val >= 4 ? 'rgba(46,184,126,0.1)' : val >= 3 ? 'rgba(239,159,39,0.1)' : 'rgba(226,75,74,0.1)',
                color:   val >= 4 ? '#1A8A5A' : val >= 3 ? '#BA7517' : '#C62828',
                border: '1px solid',
                borderColor: val >= 4 ? 'rgba(46,184,126,0.3)' : val >= 3 ? 'rgba(239,159,39,0.3)' : 'rgba(226,75,74,0.3)',
              }}>
                {label} {val}/5
              </Box>
            ))}
            <Box sx={{
              px: 0.75, py: 0.2, borderRadius: 0.75,
              fontSize: '0.62rem', fontWeight: 700,
              bgcolor: 'rgba(46,184,126,0.15)', color: '#1A8A5A',
              border: '1px solid rgba(46,184,126,0.4)',
            }}>
              Overall {msg.eval.scores?.overall}/5
            </Box>
            {msg.eval.explanation && (
              <Box component="span" sx={{ fontSize: '0.62rem', color: 'text.secondary', ml: 0.5 }}>
                — {msg.eval.explanation}
              </Box>
            )}
          </Box>
        )}
        <Typography variant="caption" sx={{ color: 'text.secondary', mt: 0.5, display: 'block' }}>
          {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </Typography>
      </Paper>
    </Box>
  )
}

function TypingIndicator() {
  return (
    <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start', mb: 2 }}>
      <Avatar sx={{ width: 32, height: 32, bgcolor: 'primary.main', flexShrink: 0 }}>
        <SmartToyOutlinedIcon sx={{ fontSize: 18 }} />
      </Avatar>
      <Paper
        elevation={0}
        sx={{
          px: 2, py: 1.5,
          background: 'rgba(46,184,126,0.07)',
          border: '1px solid rgba(46,184,126,0.25)',
          borderRadius: '4px 16px 16px 16px',
          display: 'flex', alignItems: 'center', gap: 1,
        }}
      >
        <CircularProgress size={12} thickness={5} sx={{ color: 'primary.main' }} />
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          Searching ARCL data…
        </Typography>
      </Paper>
    </Box>
  )
}

function ChatTab() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "Hi! I'm Adar, the ARCL cricket assistant. I can help you with league rules, player statistics, team history, and schedules.\n\nWhat would you like to know?",
      timestamp: Date.now(),
    },
  ])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [userId] = useState(() => `user_${uuidv4().slice(0, 8)}`)
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = useCallback(async (text) => {
    const message = text || input.trim()
    if (!message || loading) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: message, timestamp: Date.now() }])
    setLoading(true)

    try {
      const token = localStorage.getItem('adar_token') || ''
      const headers = {}
      if (API_KEY)  headers['X-API-Key']     = API_KEY
      if (token)    headers['Authorization'] = `Bearer ${token}`
      const { data } = await axios.post(
        `${API_URL}/api/chat`,
        { message, user_id: userId, session_id: sessionId },
        { headers },
      )
      setSessionId(data.session_id)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        timestamp: Date.now(),
        eval: data.eval || null,
      }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: Date.now(),
      }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [input, loading, sessionId, userId])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const clearSession = async () => {
    if (sessionId) {
      try {
        await axios.delete(
          `${API_URL}/api/sessions/${sessionId}?user_id=${userId}`,
          { headers: API_KEY ? { 'X-API-Key': API_KEY } : {} },
        )
      } catch { /* ignore */ }
    }
    setSessionId(null)
    setMessages([{
      role: 'assistant',
      content: 'Session cleared. How can I help you with ARCL cricket?',
      timestamp: Date.now(),
    }])
  }

  return (
    <>
      {/* Messages */}
      <Box sx={{ flex: 1, overflowY: 'auto', px: 2.5, py: 2 }}>
        {messages.map((msg, i) => <MessageBubble key={i} msg={msg} prevContent={messages[i-1]?.content||''} />)}
        {loading && <TypingIndicator />}
        <div ref={bottomRef} />
      </Box>

      {/* Suggested questions */}
      {messages.length <= 1 && (
        <Box sx={{ px: 2.5, pb: 1.5 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary', mb: 1, display: 'block' }}>
            Try asking:
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            {SUGGESTED_QUESTIONS.map(q => (
              <Chip
                key={q}
                label={q}
                size="small"
                variant="outlined"
                onClick={() => sendMessage(q)}
                sx={{
                  cursor: 'pointer', fontSize: '0.72rem',
                  borderColor: '#C8E8D8', color: 'text.secondary', bgcolor: '#EBF7F1',
                  '&:hover': { borderColor: 'primary.main', color: 'primary.dark', bgcolor: 'rgba(46,184,126,0.12)' },
                }}
              />
            ))}
          </Box>
        </Box>
      )}

      <Divider />

      {/* Clear session button */}
      {sessionId && (
        <Box sx={{ px: 2.5, pt: 1, display: 'flex', justifyContent: 'flex-end' }}>
          <Tooltip title="Clear session">
            <IconButton size="small" onClick={clearSession} sx={{ color: 'text.secondary' }}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      )}

      {/* Input */}
      <Box sx={{ px: 2.5, py: 2, bgcolor: 'background.paper' }}>
        <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-end' }}>
          <TextField
            inputRef={inputRef}
            fullWidth
            multiline
            maxRows={4}
            variant="outlined"
            placeholder="Ask about rules, players, teams, or standings…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            size="small"
            sx={{
              '& .MuiOutlinedInput-root': {
                bgcolor: 'background.default',
                '& fieldset': { borderColor: '#C8E8D8' },
                '&:hover fieldset': { borderColor: 'primary.light' },
                '&.Mui-focused fieldset': { borderColor: 'primary.main' },
              },
            }}
          />
          <IconButton
            onClick={() => sendMessage()}
            disabled={!input.trim() || loading}
            sx={{
              bgcolor: 'primary.main', color: '#fff',
              width: 40, height: 40, flexShrink: 0,
              '&:hover': { bgcolor: 'primary.dark' },
              '&.Mui-disabled': { bgcolor: '#C8E8D8', color: '#5A8A70' },
            }}
          >
            <SendIcon fontSize="small" />
          </IconButton>
        </Box>
        <Typography variant="caption" sx={{ color: 'text.secondary', mt: 0.75, display: 'block', textAlign: 'center' }}>
          Powered by Adar · Data from arcl.org
        </Typography>
      </Box>
    </>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState(0)
  const [page, setPage]           = useState(() => {
    const token = localStorage.getItem('adar_token')
    const role  = localStorage.getItem('adar_role')
    if (token) return role === 'admin' ? 'admin' : 'chat'
    return 'login'
  })
  const [token, setToken]   = useState(() => localStorage.getItem('adar_token') || '')
  const [teamName, setTeamName] = useState(() => localStorage.getItem('adar_team_name') || '')

  // Auto-logout after 30 minutes
  useEffect(() => {
    if (page !== 'chat' && page !== 'admin') return
    const THIRTY_MIN = 30 * 60 * 1000   // 30 * 60 * 1000 for production
    const timer = setTimeout(() => {
      handleLogout()
      alert('Your session has expired after 30 minutes. Please log in again.')
    }, THIRTY_MIN)
    return () => clearTimeout(timer)
  }, [page])

  const handleLogin = (data, redirect) => {
    if (redirect === 'register') { setPage('register'); return }
    if (!data) return
    setToken(data.access_token)
    setTeamName(data.team_name)
    setPage(data.role === 'admin' ? 'admin' : 'chat')
  }

  const handleLogout = () => {
    localStorage.removeItem('adar_token')
    localStorage.removeItem('adar_team_id')
    localStorage.removeItem('adar_team_name')
    localStorage.removeItem('adar_role')
    localStorage.removeItem('adar_login_time')
    setToken(''); setTeamName(''); setPage('login')
  }

  if (page === 'login')    return <ThemeProvider theme={theme}><CssBaseline /><Login onLogin={handleLogin} /></ThemeProvider>
  if (page === 'register') return <ThemeProvider theme={theme}><CssBaseline /><Register onBack={() => setPage('login')} /></ThemeProvider>
  if (page === 'admin')    return <ThemeProvider theme={theme}><CssBaseline /><AdminDashboard token={token} onLogout={handleLogout} /></ThemeProvider>
  if (page === 'checkout') return <ThemeProvider theme={theme}><CssBaseline /><Checkout token={token} onBack={() => setPage('chat')} onSuccess={() => setPage('chat')} /></ThemeProvider>
  if (page === 'billing')  return <ThemeProvider theme={theme}><CssBaseline /><Billing token={token} onSubscribe={() => setPage('checkout')} onBack={() => setPage('chat')} /></ThemeProvider>

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box
        sx={{
          height: '100dvh',
          display: 'flex',
          flexDirection: 'column',
          bgcolor: 'background.default',
          maxWidth: 800,
          mx: 'auto',
        }}
      >
        {/* Header */}
        <Paper
          elevation={0}
          sx={{
            px: 2.5, py: 1.5,
            borderRadius: 0,
            borderBottom: '1px solid',
            borderColor: 'divider',
            display: 'flex',
            alignItems: 'center',
            bgcolor: 'background.paper',
          }}
        >
          <Stack direction="row" alignItems="center" spacing={1.5} sx={{ flex: 1 }}>
            <Box
              sx={{
                width: 36, height: 36, borderRadius: '10px',
                bgcolor: 'primary.main',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.8rem', fontWeight: 700, color: '#fff', letterSpacing: '-0.5px',
                userSelect: 'none',
              }}
            >
              আদর
            </Box>
            <Box sx={{ flex: 1 }}>
              <Typography variant="subtitle1" fontWeight={600} lineHeight={1.2} sx={{ color: 'text.primary' }}>
                Adar ARCL
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {teamName || 'Cricket Assistant'}
              </Typography>
            </Box>
            <Box
              onClick={() => setPage('billing')}
              sx={{
                cursor: 'pointer', px: 1.5, py: 0.5,
                borderRadius: 1.5, border: '1px solid', borderColor: 'divider',
                fontSize: '0.82rem', fontWeight: 600, color: 'text.secondary',
                userSelect: 'none', display: 'flex', alignItems: 'center', gap: 0.5,
                '&:hover': { borderColor: 'primary.main', color: 'primary.main', bgcolor: 'rgba(46,184,126,0.06)' },
              }}
            >
              <span style={{fontSize: '1rem'}}>💳</span> Billing
            </Box>
            <Tooltip title="Sign out">
              <IconButton
                size="small"
                onClick={handleLogout}
                sx={{
                  color: 'text.secondary',
                  '&:hover': { color: 'error.main', bgcolor: 'rgba(211,47,47,0.08)' },
                }}
              >
                <LogoutIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Paper>

        {/* Tabs */}
        <Tabs
          value={activeTab}
          onChange={(_, v) => setActiveTab(v)}
          sx={{
            borderBottom: '1px solid',
            borderColor: 'divider',
            bgcolor: 'background.paper',
            minHeight: 42,
            '& .MuiTab-root': { minHeight: 42, fontSize: '0.8rem', textTransform: 'none', fontWeight: 500 },
          }}
        >
          <Tab label="💬 Chat" />
          <Tab label="📊 Polls" />
        </Tabs>

        {/* Tab content */}
        {activeTab === 0 ? (
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <ChatTab />
          </Box>
        ) : (
          <Box sx={{ flex: 1, overflowY: 'auto' }}>
            <PollsPage />
          </Box>
        )}
      </Box>
    </ThemeProvider>
  )
}