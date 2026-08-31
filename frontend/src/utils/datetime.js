/**
 * Backend stores UTC. Naive ISO strings (no Z / offset) are treated as UTC,
 * then displayed in the browser's local timezone.
 */

export function parseServerTime(value) {
  if (value == null || value === '') return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }
  const s = String(value).trim()
  if (!s) return null
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(s)) {
    const d = new Date(s)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const normalized = s.includes('T') ? s : s.replace(' ', 'T')
  const d = new Date(`${normalized}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

/** Local `YYYY-MM-DD HH:mm:ss` */
export function formatDateTime(value, empty = '-') {
  const d = parseServerTime(value)
  if (!d) return value == null || value === '' ? empty : String(value)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/** Local short datetime for inbox-style lists (MM-DD HH:mm). */
export function formatDateTimeShort(value, empty = '') {
  const d = parseServerTime(value)
  if (!d) return value == null || value === '' ? empty : String(value)
  return d.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Relative time when recent; otherwise short local date. */
export function formatRelativeTime(value, empty = '') {
  const d = parseServerTime(value)
  if (!d) return empty
  const diff = Date.now() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

/** Full local locale string (zh-CN, 24h). */
export function formatLocaleString(value, empty = '-') {
  const d = parseServerTime(value)
  if (!d) return value == null || value === '' ? empty : String(value)
  return d.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
