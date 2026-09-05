// ui/src/scheduling/SchedulingTraces.jsx
// Trace Explorer for ADAR Front Desk — the admin-panel extension of the
// adar-core observability build, mirroring adar-rag's (DocIntel) Trace
// Explorer but scoped to one practice at a time and built with this
// codebase's own MUI conventions (see SchedulingOverview.jsx) rather than
// DocIntel's custom inline-style system.
//
// Reads from api/routes/scheduling_traces.py, which reads the Postgres
// trace store (src/adar/tracedb.py + src/adar/tracing.py). Every
// conversation's trace_id is the single OTel-native id — see the
// observability plan doc — and the judge-agent eval for that same
// conversation shows up here as the "Evaluation" strip, correlated by
// that same trace_id (never a freshly minted one).

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Typography, Stack, CircularProgress, Alert, Chip, TextField,
  MenuItem, Select, FormControl, InputLabel, IconButton, Tooltip, Divider,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(token) {
  const h = { Authorization: `Bearer ${token}` }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

const STATUS_COLOR = { success: '#4ade80', error: '#f87171', running: '#fbbf24' }

function fmtDT(s) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return s }
}

function fmtDuration(ms) {
  if (!ms && ms !== 0) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function StatusChip({ status }) {
  return (
    <Chip
      size="small"
      label={status || 'running'}
      sx={{
        bgcolor: `${STATUS_COLOR[status] || '#94a3b8'}22`,
        color: STATUS_COLOR[status] || '#94a3b8',
        fontWeight: 600,
        textTransform: 'capitalize',
      }}
    />
  )
}

function TraceRow({ trace, active, onClick }) {
  return (
    <Paper
      variant="outlined"
      onClick={onClick}
      sx={{
        p: 1.5, mb: 1, cursor: 'pointer',
        borderColor: active ? 'primary.main' : 'divider',
        bgcolor: active ? 'action.selected' : 'background.paper',
        '&:hover': { bgcolor: 'action.hover' },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={0.5}>
        <StatusChip status={trace.status} />
        <Typography variant="caption" color="text.secondary">
          {fmtDuration(trace.duration_ms)} · {trace.span_count || 0} steps
        </Typography>
      </Stack>
      <Typography variant="body2" fontWeight={600} sx={{
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {trace.input_text_preview || '(no question preview)'}
      </Typography>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mt={0.5}>
        <Typography variant="caption" color="text.secondary">{fmtDT(trace.started_at)}</Typography>
        {trace.eval_overall != null && (
          <Chip size="small" label={`eval ${Number(trace.eval_overall).toFixed(1)}/5`}
            sx={{ height: 20, fontSize: 11 }} />
        )}
      </Stack>
    </Paper>
  )
}

// A tool span's result_preview is itself a JSON-encoded string of the
// tool's raw return value -- usually {"result": "<the actual text the
// tool gave back>"}. Unwrap that one level so the flow shows the plain
// text instead of an escaped JSON blob.
function _unwrapResultPreview(preview) {
  if (typeof preview !== 'string') return preview
  try {
    const parsed = JSON.parse(preview)
    if (parsed && typeof parsed === 'object' && 'result' in parsed) return String(parsed.result)
    return preview
  } catch {
    return preview
  }
}

function SpanRow({ span, offsetBase, llmEvents = [] }) {
  const offset = offsetBase && span.started_at
    ? Math.max(0, new Date(span.started_at) - new Date(offsetBase))
    : 0
  const args = span.metadata && span.metadata.args
  const hasArgs = args && typeof args === 'object' && Object.keys(args).length > 0
  const resultText = span.metadata && _unwrapResultPreview(span.metadata.result_preview)
  return (
    <Box sx={{ display: 'flex', gap: 1.5, py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
      <Box sx={{
        width: 10, height: 10, borderRadius: '50%', mt: 0.5, flexShrink: 0,
        bgcolor: STATUS_COLOR[span.status] || '#94a3b8',
      }} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" justifyContent="space-between">
          <Typography variant="body2" fontWeight={600}>{span.name}</Typography>
          <Typography variant="caption" color="text.secondary">{fmtDuration(span.duration_ms)}</Typography>
        </Stack>
        <Typography variant="caption" color="text.secondary">
          +{fmtDuration(offset)} from request start
        </Typography>
        {span.status === 'error' && (
          <Alert severity="error" sx={{ mt: 0.5, py: 0 }}>
            {(span.error && span.error.message) || 'This step failed.'}
          </Alert>
        )}
        {hasArgs && (
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
            <b>Args:</b> {Object.entries(args).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ')}
          </Typography>
        )}
        {resultText && (
          <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
            {resultText}
          </Typography>
        )}
        {llmEvents.map((ev) => (
          <Paper key={ev.event_id} variant="outlined" sx={{ p: 1, mt: 1, bgcolor: 'action.hover' }}>
            <Stack direction="row" justifyContent="space-between">
              <Typography variant="caption" color="text.secondary">
                {ev.provider} · {ev.model || 'default model'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {ev.input_tokens ?? '—'} in / {ev.output_tokens ?? '—'} out tokens
              </Typography>
            </Stack>
            {ev.system_prompt && (
              <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                <b>System:</b> {ev.system_prompt}
              </Typography>
            )}
            {ev.user_prompt && (
              <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                <b>Prompt:</b> {ev.user_prompt}
              </Typography>
            )}
            {ev.llm_response && (
              <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                {ev.llm_response}
              </Typography>
            )}
            {ev.error && <Alert severity="error" sx={{ mt: 0.5, py: 0 }}>{ev.error}</Alert>}
          </Paper>
        ))}
      </Box>
    </Box>
  )
}

function TraceDetail({ detail, loading, hasSelection }) {
  const [view, setView] = useState('flow')

  if (loading) {
    return <Box sx={{ textAlign: 'center', py: 6 }}><CircularProgress size={24} /></Box>
  }
  if (!hasSelection) {
    return (
      <Box sx={{ textAlign: 'center', py: 6 }}>
        <Typography variant="body2" color="text.secondary">
          Select a trace to inspect its steps, timing, and evaluation score.
        </Typography>
      </Box>
    )
  }
  if (!detail) {
    return (
      <Box sx={{ textAlign: 'center', py: 6 }}>
        <Typography variant="body2" color="text.secondary">Trace not found.</Typography>
      </Box>
    )
  }

  const { trace, spans = [], llm_events = [], evaluations = [] } = detail

  // Group each LLM turn under the span it belongs to (agent_run, almost
  // always) so the Flow view can show a tool call's args/result AND the
  // model turns that happened as part of it in one place, instead of
  // making you switch to Raw to see what the agent actually saw and said.
  const llmEventsBySpan = {}
  const unassignedLlmEvents = []
  for (const ev of llm_events) {
    if (ev.span_id && spans.some((s) => s.span_id === ev.span_id)) {
      (llmEventsBySpan[ev.span_id] ||= []).push(ev)
    } else {
      unassignedLlmEvents.push(ev)
    }
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" mb={1}>
        <Box minWidth={0}>
          <Stack direction="row" spacing={1} alignItems="center" mb={0.5}>
            <Typography variant="subtitle1" fontWeight={700}>Request workflow</Typography>
            <StatusChip status={trace.status} />
          </Stack>
          <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
            {trace.trace_id}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} textAlign="center">
          <Box><Typography variant="h6">{fmtDuration(trace.duration_ms)}</Typography><Typography variant="caption" color="text.secondary">total</Typography></Box>
          <Box><Typography variant="h6">{trace.span_count || spans.length}</Typography><Typography variant="caption" color="text.secondary">steps</Typography></Box>
          <Box><Typography variant="h6">{llm_events.length}</Typography><Typography variant="caption" color="text.secondary">LLM calls</Typography></Box>
        </Stack>
      </Stack>

      <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5, bgcolor: 'action.hover' }}>
        <Typography variant="caption" color="text.secondary" display="block">User question</Typography>
        <Typography variant="body2" fontWeight={600}>{trace.input_text_preview || 'No question preview captured'}</Typography>
      </Paper>

      {trace.error_message && (
        <Alert severity="error" sx={{ mb: 1.5 }}>{trace.error_message}</Alert>
      )}

      {evaluations.length > 0 && (
        <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
          <Typography variant="caption" color="text.secondary" display="block" mb={1}>
            Evaluation correlation (judge agent, same trace_id)
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {evaluations.map((ev) => (
              <Chip
                key={ev.eval_id}
                label={`${Number(ev.overall ?? 0).toFixed(1)}/5 · ${fmtDT(ev.created_at)}`}
                sx={{ fontWeight: 600 }}
              />
            ))}
          </Stack>
          {evaluations[0]?.explanation && (
            <Typography variant="body2" sx={{ mt: 1, fontStyle: 'italic' }}>
              "{evaluations[0].explanation}"
            </Typography>
          )}
        </Paper>
      )}

      <Stack direction="row" spacing={1} mb={1.5}>
        {[['flow', 'Flow'], ['timeline', 'Timeline'], ['raw', 'Raw']].map(([key, label]) => (
          <Chip
            key={key}
            label={label}
            onClick={() => setView(key)}
            color={view === key ? 'primary' : 'default'}
            variant={view === key ? 'filled' : 'outlined'}
            size="small"
          />
        ))}
      </Stack>

      {view === 'flow' && (
        <Box>
          {spans.length === 0 && <Typography variant="body2" color="text.secondary">No spans recorded for this trace.</Typography>}
          {spans.map((s) => (
            <SpanRow key={s.span_id} span={s} offsetBase={trace.started_at} llmEvents={llmEventsBySpan[s.span_id] || []} />
          ))}
        </Box>
      )}

      {view === 'timeline' && (
        <Box>
          {spans.length === 0 && <Typography variant="body2" color="text.secondary">No spans recorded for this trace.</Typography>}
          {spans.map((s) => {
            const total = trace.duration_ms || 1
            const offset = s.started_at ? Math.max(0, new Date(s.started_at) - new Date(trace.started_at)) : 0
            const leftPct = Math.min(100, (offset / total) * 100)
            const widthPct = Math.max(1, Math.min(100 - leftPct, ((s.duration_ms || 0) / total) * 100))
            return (
              <Box key={s.span_id} sx={{ mb: 1.2 }}>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="caption">{s.name}</Typography>
                  <Typography variant="caption" color="text.secondary">{fmtDuration(s.duration_ms)}</Typography>
                </Stack>
                <Box sx={{ position: 'relative', height: 8, bgcolor: 'action.hover', borderRadius: 1, mt: 0.4 }}>
                  <Box sx={{
                    position: 'absolute', left: `${leftPct}%`, width: `${widthPct}%`, height: '100%',
                    borderRadius: 1, bgcolor: STATUS_COLOR[s.status] || '#94a3b8',
                  }} />
                </Box>
              </Box>
            )
          })}
        </Box>
      )}

      {view === 'raw' && (
        <Box component="pre" sx={{
          fontSize: 12, bgcolor: 'action.hover', p: 1.5, borderRadius: 1,
          overflow: 'auto', maxHeight: 480, fontFamily: 'monospace',
        }}>
          {JSON.stringify(detail, null, 2)}
        </Box>
      )}

      {((view === 'timeline' && llm_events.length > 0) || unassignedLlmEvents.length > 0) && view !== 'raw' && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="caption" color="text.secondary" display="block" mb={1}>LLM calls</Typography>
          {(view === 'timeline' ? llm_events : unassignedLlmEvents).map((ev) => (
            <Paper key={ev.event_id} variant="outlined" sx={{ p: 1.2, mb: 1 }}>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2" fontWeight={600}>{ev.provider} · {ev.model || 'default model'}</Typography>
                <Typography variant="caption" color="text.secondary">{fmtDuration(ev.latency_ms)}</Typography>
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {ev.input_tokens ?? '—'} in / {ev.output_tokens ?? '—'} out tokens
                {ev.error ? ` · error: ${ev.error}` : ''}
              </Typography>
            </Paper>
          ))}
        </>
      )}
    </Box>
  )
}

export default function SchedulingTraces({ token, practiceId }) {
  const [summary, setSummary] = useState(null)
  const [traces, setTraces] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [listLoading, setListLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')

  const loadSummary = useCallback(async () => {
    if (!practiceId) return
    try {
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/traces/summary`,
        { headers: authHeaders(token) },
      )
      setSummary(data)
    } catch (e) {
      setSummary(null)
    }
  }, [token, practiceId])

  const loadTraces = useCallback(async () => {
    if (!practiceId) return
    setListLoading(true); setError('')
    try {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (search) params.set('search', search)
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/traces?${params}`,
        { headers: authHeaders(token) },
      )
      setTraces(data.traces || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load traces')
    } finally {
      setListLoading(false)
    }
  }, [token, practiceId, statusFilter, search])

  const openTrace = useCallback(async (traceId) => {
    setSelectedId(traceId)
    setDetailLoading(true)
    try {
      const { data } = await axios.get(
        `${API_URL}/admin/scheduling/practices/${practiceId}/traces/${traceId}`,
        { headers: authHeaders(token) },
      )
      setDetail(data)
    } catch (e) {
      setDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }, [token, practiceId])

  useEffect(() => { loadSummary(); loadTraces() }, [loadSummary, loadTraces])

  const refresh = () => { loadSummary(); loadTraces(); if (selectedId) openTrace(selectedId) }

  if (summary && summary.ready === false) {
    return (
      <Alert severity="info">
        The Postgres trace store isn't configured yet for this deployment
        (TRACE_DB_URL is unset), so there's nothing to show here. OpenTelemetry
        spans are still being emitted to the shared Collector in the
        meantime — see the observability plan doc for provisioning steps.
      </Alert>
    )
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="subtitle1" fontWeight={600}>
          Trace Explorer {summary ? `· ${summary.trace_count ?? 0} traces` : ''}
        </Typography>
        <Tooltip title="Refresh">
          <IconButton size="small" onClick={refresh}><RefreshIcon fontSize="small" /></IconButton>
        </Tooltip>
      </Stack>

      <Stack direction="row" spacing={1.5} mb={2} flexWrap="wrap">
        <TextField
          size="small" label="Search question or trace id" value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 260 }}
        />
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Status</InputLabel>
          <Select label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="success">Success</MenuItem>
            <MenuItem value="error">Error</MenuItem>
            <MenuItem value="running">Running</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Box sx={{ flex: '1 1 320px', minWidth: 280, maxHeight: 640, overflowY: 'auto' }}>
          {listLoading ? (
            <Box sx={{ textAlign: 'center', py: 4 }}><CircularProgress size={20} /></Box>
          ) : traces.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No traces yet. Run a chat or voice query against this practice, then refresh.
            </Typography>
          ) : (
            traces.map((t) => (
              <TraceRow key={t.trace_id} trace={t} active={t.trace_id === selectedId} onClick={() => openTrace(t.trace_id)} />
            ))
          )}
        </Box>
        <Box sx={{ flex: '2 1 480px', minWidth: 320 }}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <TraceDetail detail={detail} loading={detailLoading} hasSelection={!!selectedId} />
          </Paper>
        </Box>
      </Box>
    </Box>
  )
}
