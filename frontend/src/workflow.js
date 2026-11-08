export const sources = { fixture: '本地样例', boss: 'BOSS 来源' }
export const sourceFrom = (value) => value === 'boss' ? 'boss' : 'fixture'

export const applicationStates = {
  pending: ['待投递', 'info'],
  sending: ['投递中', 'primary'],
  succeeded: ['已投递', 'success'],
  failed: ['失败', 'danger'],
  uncertain: ['待核对', 'warning'],
}

export const taskStates = {
  queued: ['排队中', 'info'],
  running: ['运行中', 'primary'],
  stop_requested: ['正在停止', 'warning'],
  succeeded: ['已完成', 'success'],
  failed: ['失败', 'danger'],
  stopped: ['已停止', 'warning'],
  interrupted: ['已中断', 'danger'],
}

export const isActive = (task) => ['queued', 'running', 'stop_requested'].includes(task?.status)

const timeFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium', hour12: false })

export function dateLabel(value) {
  if (!value) return '—'
  const utc = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`)
  return Number.isNaN(utc.getTime()) ? '—' : timeFormat.format(utc)
}

export function errorMessage(error, fallback) {
  return error.response?.data?.detail?.message || fallback
}
