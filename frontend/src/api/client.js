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
  return client.post(`/tasks/${taskId}/stop`, null, config)
}
