import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 3000,
  headers: { Accept: 'application/json' },
})

export function getHealth() {
  return client.get('/health')
}

export function getReady() {
  return client.get('/ready')
}

export function getJobs(params, config) {
  return client.get('/jobs', { ...config, params })
}

export function getJob(jobId, config) {
  return client.get(`/jobs/${jobId}`, config)
}

export function createTask(payload, config) {
  return client.post('/tasks', payload, config)
}

export function getTasks(params, config) {
  return client.get('/tasks', { ...config, params })
}

export function getTask(taskId, config) {
  return client.get(`/tasks/${taskId}`, config)
}

export function stopTask(taskId, config) {
  return client.post(`/tasks/${taskId}/stop`, {}, config)
}

export const getDashboard = (source, config) => client.get('/dashboard', { ...config, params: { source } })
export const getApplications = (params, config) => client.get('/applications', { ...config, params })
export const addApplication = (jobId) => client.post('/applications', { job_id: jobId })
export const resolveApplication = (id, payload) => client.post(`/applications/${id}/resolve`, payload)
export const getSettings = (config) => client.get('/settings', config)
export const acknowledgeGuard = (guard) => client.post(`/automation-guard/${guard.provider}/acknowledge`, {
  confirmed: true, blocked_at: guard.blocked_at,
})
