<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDashboard } from '../api/client'
import { applicationStates, dateLabel, errorMessage, sourceFrom, sources, taskStates } from '../workflow'

const route = useRoute()
const router = useRouter()
const source = computed(() => sourceFrom(route.query.source))
const dashboard = ref(null)
const loading = ref(false)
const error = ref('')
let request

const jobsLink = (extra = {}) => ({ name: 'jobs', query: { source: source.value, ...extra } })
const taskLink = (task) => ({ name: 'tasks', query: { task: task.task_id } })

async function load() {
  request?.abort()
  const controller = request = new AbortController()
  loading.value = true
  dashboard.value = null
  error.value = ''
  try {
    const response = await getDashboard(source.value, { signal: controller.signal })
    if (!controller.signal.aborted) dashboard.value = response.data
  } catch (err) {
    if (!controller.signal.aborted) error.value = errorMessage(err, '无法加载总览，请稍后重试。')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

watch(source, load, { immediate: true })
onUnmounted(() => request?.abort())
</script>

<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">OVERVIEW</div>
      <h1>总览</h1>
      <p>按来源查看职位、投递记录与最近任务。</p>
    </div>
    <div class="workflow-actions">
      <label class="job-filter">数据来源
        <select :value="source" @change="router.replace({ query: { source: $event.target.value } })">
          <option v-for="(label, key) in sources" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
  </section>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <div v-else-if="loading" class="workflow-panel workflow-empty" role="status">正在读取总览…</div>
  <template v-else-if="dashboard">
    <section class="workflow-panel">
      <div class="workflow-title"><h2>职位</h2><el-tag effect="plain" :type="source === 'fixture' ? 'warning' : 'info'">{{ sources[source] }}</el-tag></div>
      <div class="metric-grid">
        <RouterLink class="metric-card" :to="jobsLink()"><span>职位总数</span><strong data-metric="jobs-total">{{ dashboard.jobs_total }}</strong></RouterLink>
        <RouterLink class="metric-card" :to="jobsLink({ recommended: 'true' })"><span>推荐职位</span><strong data-metric="jobs-recommended">{{ dashboard.jobs_recommended }}</strong></RouterLink>
      </div>
    </section>
    <section class="workflow-panel">
      <div class="workflow-title"><h2>投递记录</h2><span class="workflow-note">按记录计数</span></div>
      <div class="metric-grid">
        <RouterLink v-for="([label, type], status) in applicationStates" :key="status" class="metric-card"
          :to="{ name: 'applications', query: { source, status } }">
          <span>{{ label }}</span><strong :data-metric="status" :class="`metric-${type}`">{{ dashboard.applications[status] }}</strong>
        </RouterLink>
      </div>
    </section>
    <section class="workflow-panel">
      <div class="workflow-title"><h2>当前任务</h2><RouterLink class="workflow-link" :to="{ name: 'tasks' }">打开任务中心</RouterLink></div>
      <div v-if="dashboard.active_task" class="workflow-line">
        <RouterLink class="workflow-link" :to="taskLink(dashboard.active_task)">#{{ dashboard.active_task.task_id }} · {{ dashboard.active_task.mode === 'review' ? 'Review 职位筛选' : 'Auto' }}</RouterLink>
        <el-tag :type="taskStates[dashboard.active_task.status]?.[1]" effect="plain">{{ taskStates[dashboard.active_task.status]?.[0] }}</el-tag>
      </div>
      <p v-else class="workflow-note">该来源没有进行中的任务。</p>
      <h3 class="workflow-subtitle">最近任务</h3>
      <p v-if="!dashboard.recent_tasks.length" class="workflow-note">该来源暂无任务记录。</p>
      <ul v-else class="workflow-list">
        <li v-for="task in dashboard.recent_tasks" :key="task.task_id">
          <RouterLink class="workflow-link" :to="taskLink(task)">#{{ task.task_id }} · {{ task.mode === 'review' ? 'Review 职位筛选' : 'Auto' }}</RouterLink>
          <span>{{ dateLabel(task.created_at) }}</span>
          <el-tag :type="taskStates[task.status]?.[1]" effect="plain" size="small">{{ taskStates[task.status]?.[0] }}</el-tag>
        </li>
      </ul>
    </section>
  </template>
</template>
