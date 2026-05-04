import { useState } from 'react'
import { Box, Typography, Tabs, Tab } from '@mui/material'

function parseMarkdownTable(md) {
  const lines = md.trim().split('\n').filter(l => l.trim())
  const tableLines = lines.filter(l => l.includes('|'))
  if (tableLines.length < 3) return null
  const headers = tableLines[0].split('|').map(h => h.trim()).filter(Boolean)
  const rows = tableLines.slice(2)
    .map(line => line.split('|').map(c => c.trim()).filter(Boolean))
    .filter(r => r.length >= 2)
  return { headers, rows }
}

function isBattingTable(headers) {
  const h = headers.map(h => h.toLowerCase()).join(' ')
  return (h.includes('run') || h.includes('bat')) &&
    (h.includes('ball') || h.includes('sr') || h.includes('inning') || h.includes('four'))
}

function isBowlingTable(headers) {
  const h = headers.map(h => h.toLowerCase()).join(' ')
  return (h.includes('wicket') || h.includes('wkt') || h.includes('bowl')) &&
    (h.includes('over') || h.includes('eco') || h.includes('maiden'))
}

function tableToChartData(headers, rows, statType) {
  const h = headers.map(x => x.toLowerCase())
  const nameIdx = h.findIndex(x => x.includes('player') || x.includes('name'))
  if (nameIdx === -1) return null
  const colIdx = (...kws) => {
    for (const kw of kws) {
      const i = h.findIndex(x => x.includes(kw))
      if (i !== -1) return i
    }
    return -1
  }
  const valIdx = statType === 'batting'
    ? colIdx('run', 'total_run')
    : colIdx('wicket', 'wkt')
  if (valIdx === -1) return null
  return rows
    .map(row => ({
      name: (row[nameIdx] || '').replace(/[*†]/g, '').trim().split(' ').slice(0, 2).join(' '),
      value: parseFloat(row[valIdx]) || 0,
    }))
    .filter(d => d.name && d.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 10)
}

const BAT_COLOR  = '#2EB87E'
const BOWL_COLOR = '#EF9F27'

function SVGBarChart({ data, color, unit }) {
  if (!data || data.length === 0) return null
  const barH    = 26
  const gap     = 6
  const labelW  = 120
  const valW    = 40
  const chartW  = 260
  const padTop  = 8
  const padBot  = 8
  const max     = Math.max(...data.map(d => d.value))
  const totalH  = padTop + data.length * (barH + gap) - gap + padBot

  return (
    <svg width="100%" viewBox={`0 0 ${labelW + chartW + valW + 8} ${totalH}`} style={{ display: 'block' }}>
      {data.map((d, i) => {
        const y       = padTop + i * (barH + gap)
        const barLen  = max > 0 ? Math.round((d.value / max) * chartW) : 0
        const opacity = 1 - i * 0.06

        return (
          <g key={i}>
            <text
              x={labelW - 6}
              y={y + barH / 2}
              dominantBaseline="central"
              textAnchor="end"
              fontSize={11}
              fill="var(--color-text-primary, #1A3326)"
            >
              {d.name}
            </text>
            <rect
              x={labelW}
              y={y}
              width={Math.max(barLen, 2)}
              height={barH}
              rx={3}
              fill={color}
              opacity={opacity}
            />
            <text
              x={labelW + barLen + 5}
              y={y + barH / 2}
              dominantBaseline="central"
              fontSize={11}
              fill="var(--color-text-secondary, #5A8A70)"
            >
              {d.value} {unit}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export default function StatsCharts({ content, showChart = false }) {
  const [tab, setTab]             = useState(0)
  const [chartMode, setChartMode] = useState(showChart)

  const blocks = content.split(/\n(?=\|)|\n\n/)
  let battingChart = null
  let bowlingChart = null

  for (const block of blocks) {
    if (!block.includes('|')) continue
    const parsed = parseMarkdownTable(block)
    if (!parsed) continue
    if (!battingChart && isBattingTable(parsed.headers)) {
      const data = tableToChartData(parsed.headers, parsed.rows, 'batting')
      if (data?.length) battingChart = data
    }
    if (!bowlingChart && isBowlingTable(parsed.headers)) {
      const data = tableToChartData(parsed.headers, parsed.rows, 'bowling')
      if (data?.length) bowlingChart = data
    }
  }

  if (!battingChart && !bowlingChart) return null

  const hasBoth = battingChart && bowlingChart

  return (
    <Box sx={{ mt: 1 }}>
      <Box
        onClick={() => setChartMode(m => !m)}
        sx={{
          display: 'inline-flex', alignItems: 'center',
          cursor: 'pointer',
          mb: chartMode ? 1.5 : 0,
          px: 1, py: 0.4, borderRadius: 1,
          border: '1px solid rgba(46,184,126,0.3)',
          bgcolor: chartMode ? 'rgba(46,184,126,0.1)' : 'transparent',
          '&:hover': { bgcolor: 'rgba(46,184,126,0.12)' },
          transition: 'all 0.15s',
        }}
      >
        <Typography variant="caption" sx={{ color: 'primary.dark', fontSize: '0.7rem', userSelect: 'none' }}>
          {chartMode ? '📋 Table' : '📊 Chart'}
        </Typography>
      </Box>

      {chartMode && (
        <Box>
          {hasBoth && (
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{
              minHeight: 34, mb: 1,
              '& .MuiTab-root': { minHeight: 34, fontSize: '0.72rem', textTransform: 'none', py: 0 },
              '& .MuiTabs-indicator': { bgcolor: 'primary.main' },
            }}>
              <Tab label="🏏 Batting" />
              <Tab label="⚾ Bowling" />
            </Tabs>
          )}

          {(!hasBoth || tab === 0) && battingChart && (
            <Box>
              <Typography variant="caption" fontWeight={600}
                sx={{ color: 'primary.dark', display: 'block', mb: 0.5, textTransform: 'uppercase', letterSpacing: 0.5, fontSize: '0.65rem' }}>
                Batting — runs scored
              </Typography>
              <SVGBarChart data={battingChart} color={BAT_COLOR} unit="runs" />
            </Box>
          )}

          {(!hasBoth || tab === 1) && bowlingChart && (
            <Box>
              <Typography variant="caption" fontWeight={600}
                sx={{ color: '#BA7517', display: 'block', mb: 0.5, textTransform: 'uppercase', letterSpacing: 0.5, fontSize: '0.65rem' }}>
                Bowling — wickets taken
              </Typography>
              <SVGBarChart data={bowlingChart} color={BOWL_COLOR} unit="wkts" />
            </Box>
          )}
        </Box>
      )}
    </Box>
  )
}