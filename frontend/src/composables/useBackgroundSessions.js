import { notification } from 'ant-design-vue'
import router from '../router'
import { sessionApi } from '../api'

const STORAGE_KEY = 'vela_watched_sessions'
const POLL_INTERVAL_MS = 3000

let pollTimer = null
let watchedSessions = loadWatched()
let activeViewing = null

function loadWatched() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]')
  } catch {
    return []
  }
}

function saveWatched() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(watchedSessions))
}

export function setActiveViewing(sessionId, agentId) {
  activeViewing = sessionId ? { sessionId, agentId } : null
}

function isUserViewingSession(sessionId, agentId) {
  return (
    activeViewing
    && activeViewing.sessionId === sessionId
    && activeViewing.agentId === agentId
  )
}

export function watchBackgroundSession(sessionId, agentId, agentName) {
  const exists = watchedSessions.find((s) => s.sessionId === sessionId)
  if (!exists) {
    watchedSessions.push({ sessionId, agentId, agentName })
    saveWatched()
  } else {
    exists.agentId = agentId
    exists.agentName = agentName
    saveWatched()
  }
}

export function unwatchBackgroundSession(sessionId) {
  watchedSessions = watchedSessions.filter((s) => s.sessionId !== sessionId)
  saveWatched()
}

function showCompletionNotification(watched, session) {
  const agentName = watched.agentName || 'Agent'
  const preview = (session.messages || [])
    .filter((m) => m.role === 'user')
    .map((m) => m.content)
    .pop() || ''

  let type = 'success'
  let title = '会话任务已完成'
  if (session.status === 'HITL_WAIT') {
    type = 'info'
    title = '会话任务待审批'
  } else if (session.status === 'ERROR') {
    type = 'warning'
    title = '会话任务失败'
  }

  notification[type]({
    message: title,
    description: `${agentName} · ${preview.slice(0, 60)}${preview.length > 60 ? '...' : ''}`,
    duration: 8,
    onClick: () => {
      router.push({
        path: `/agents/${watched.agentId}/chat`,
        query: { session_id: watched.sessionId },
      })
    },
  })
}

async function pollWatchedSessions() {
  if (!watchedSessions.length) return

  const snapshot = [...watchedSessions]
  for (const watched of snapshot) {
    try {
      const session = await sessionApi.get(watched.sessionId)
      if (session.status === 'RUNNING') continue

      if (!isUserViewingSession(watched.sessionId, watched.agentId)) {
        showCompletionNotification(watched, session)
      }
      unwatchBackgroundSession(watched.sessionId)
    } catch (e) {
      console.error('[backgroundSessions] poll failed:', e)
    }
  }
}

export function startBackgroundSessionWatcher() {
  if (pollTimer) return
  watchedSessions = loadWatched()
  pollTimer = setInterval(pollWatchedSessions, POLL_INTERVAL_MS)
  pollWatchedSessions()
}

export function stopBackgroundSessionWatcher() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}
