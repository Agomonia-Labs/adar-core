// ui/src/scheduling/WorkingHoursEditor.jsx
// Weekly working-hours editor: one row per weekday, each with zero or more
// start/end time ranges (e.g. a lunch-break split shows as two ranges on
// the same day). Data shape in/out matches the backend exactly — a flat
// array of {weekday: 0-6 (Mon=0), start: "HH:MM", end: "HH:MM"}.

import { Box, Typography, IconButton, TextField, Button, Stack, Checkbox, FormControlLabel } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function groupByWeekday(hours) {
  const byDay = Array.from({ length: 7 }, () => [])
  for (const h of hours || []) {
    if (h.weekday >= 0 && h.weekday <= 6) byDay[h.weekday].push({ start: h.start, end: h.end })
  }
  return byDay
}

function flatten(byDay) {
  const out = []
  byDay.forEach((ranges, weekday) => {
    for (const r of ranges) {
      if (r.start && r.end) out.push({ weekday, start: r.start, end: r.end })
    }
  })
  return out
}

export default function WorkingHoursEditor({ value, onChange }) {
  const byDay = groupByWeekday(value)

  const updateDay = (weekday, ranges) => {
    const next = byDay.map((r, i) => (i === weekday ? ranges : r))
    onChange(flatten(next))
  }

  const addRange = (weekday) => updateDay(weekday, [...byDay[weekday], { start: '09:00', end: '17:00' }])
  const removeRange = (weekday, idx) => updateDay(weekday, byDay[weekday].filter((_, i) => i !== idx))
  const updateRange = (weekday, idx, field, val) =>
    updateDay(weekday, byDay[weekday].map((r, i) => (i === idx ? { ...r, [field]: val } : r)))

  return (
    <Box>
      {DAYS.map((label, weekday) => {
        const ranges = byDay[weekday]
        const active = ranges.length > 0
        return (
          <Box key={weekday} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}>
            <FormControlLabel
              sx={{ width: 130, flexShrink: 0, m: 0 }}
              control={
                <Checkbox
                  size="small"
                  checked={active}
                  onChange={(e) => (e.target.checked ? addRange(weekday) : updateDay(weekday, []))}
                />
              }
              label={<Typography variant="body2">{label}</Typography>}
            />
            <Box sx={{ flex: 1 }}>
              {ranges.length === 0 && (
                <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: '32px' }}>Closed</Typography>
              )}
              <Stack spacing={0.75}>
                {ranges.map((r, idx) => (
                  <Stack key={idx} direction="row" spacing={1} alignItems="center">
                    <TextField
                      type="time" size="small" value={r.start}
                      onChange={(e) => updateRange(weekday, idx, 'start', e.target.value)}
                      sx={{ width: 130 }}
                    />
                    <Typography variant="body2" sx={{ color: 'text.secondary' }}>to</Typography>
                    <TextField
                      type="time" size="small" value={r.end}
                      onChange={(e) => updateRange(weekday, idx, 'end', e.target.value)}
                      sx={{ width: 130 }}
                    />
                    <IconButton size="small" onClick={() => removeRange(weekday, idx)}>
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                    {idx === ranges.length - 1 && (
                      <Button size="small" startIcon={<AddIcon fontSize="small" />} onClick={() => addRange(weekday)} sx={{ ml: 1 }}>
                        Add range
                      </Button>
                    )}
                  </Stack>
                ))}
              </Stack>
            </Box>
          </Box>
        )
      })}
    </Box>
  )
}
