<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createTask, getSettings, getTask, getTasks, stopTask } from '../api/client'
import { dateLabel, errorMessage, isActive, sources, taskStates } from '../workflow'

const route = useRoute()
const router = useRouter()
const form = reactive({ keywords: '', city: '', max_pages: 1, max_jobs: 1 })
const settings = ref(null)
const items = ref([])
const total = ref(0)
const active = ref(null)
const detail = ref(null)
const ready = ref(false)
const refreshing = ref(false)
const creating = ref(false)
const stopping = ref(false)
const historyError = ref('')
const settingsError = ref('')
const detailError = ref('')
const actionError = ref('')
const pollError = ref('')
let pollTimer, pollRequest, historyRequest, settingsRequest, detailRequest
let retryBody
let disposed = false

const phases = {
  ...Object.fromEntries(Object.entries(taskStates).map(([key, [label]]) => [key, label])),
  queued: '等待领取', starting: '启动浏览器', reading: '读取职位', writing: '保存职位',
}
const counters = {
  keyword_index: '关键词进度', pages_attempted: '读取页数', details_attempted: '详情尝试',
  jobs_found: '发现职位', jobs_saved: '入库职位', duplicates: '重复职位',
}
const taskId = computed(() => {
  const id = Number(route.query.task)
  return Number.isSafeInteger(id) && id > 0 ? id : null
})
const selected = computed(() => {
  if (taskId.value == null) return active.value || items.value[0] || null
  return [active.value, ...items.value, detail.value].find((task) => task?.task_id === taskId.value) || null
})
const guard = computed(() => settings.value?.guards.find((row) => row.provider === 'fixture'))
const canCreate = computed(() => ready.value && settings.value?.capabilities.fixture.review_enabled &&
  guard.value?.state === 'clear' && !active.value && !creating.value && !refreshing.value)

function stopPolling() {
  clearTimeout(pollTimer)
  pollRequest?.abort()
}

function storeTask(task) {
  const index = items.value.findIndex((row) => row.task_id === task.task_id)
  if (index >= 0) items.value.splice(index, 1, task)
  else {
    items.value.unshift(task)
    total.value += 1
    if (items.value.length > 20) items.value.pop()
  }
  if (detail.value?.task_id === task.task_id) detail.value = task
  active.value = isActive(task) ? task : null
}

function schedulePoll() {
  clearTimeout(pollTimer)
  if (!disposed && active.value && !stopping.value && !refreshing.value) {
    pollTimer = setTimeout(poll, settings.value?.poll_interval_ms ?? 2000)
  }
}

async function poll() {
  const id = active.value?.task_id
  if (!id || disposed) return
  const controller = pollRequest = new AbortController()
  try {
    const { data } = await getTask(id, { signal: controller.signal })
    if (controller.signal.aborted) return
    pollError.value = ''
    storeTask(data)
    if (!isActive(data)) loadSettings()
  } catch (err) {
    if (!controller.signal.aborted) pollError.value = errorMessage(err, '暂时无法更新任务状态，将继续重试。')
  } finally {
    if (!controller.signal.aborted) schedulePoll()
  }
}

async function loadSettings() {
  settingsRequest?.abort()
  const controller = settingsRequest = new AbortController()
  settingsError.value = ''
  try {
    const { data } = await getSettings({ signal: controller.signal })
    if (controller.signal.aborted) return
    if (!settings.value) {
      const { keywords, city, max_pages, max_jobs } = data.search
      Object.assign(form, { keywords: keywords.join('\n'), city: city || '', max_pages, max_jobs })
    }
    settings.value = data
  } catch (err) {
    if (!controller.signal.aborted) settingsError.value = errorMessage(err, '无法加载任务默认配置，请刷新。')
  }
}

async function loadSelected() {
  detailRequest?.abort()
  detail.value = null
  detailError.value = ''
  const id = taskId.value
  if (!id || selected.value) return
  const controller = detailRequest = new AbortController()
  try {
    const { data } = await getTask(id, { signal: controller.signal })
    if (!controller.signal.aborted) detail.value = data
  } catch (err) {
    if (!controller.signal.aborted) detailError.value = errorMessage(err, '无法读取所选任务。')
  }
}

async function refresh() {
  if (disposed) return
  stopPolling()
  historyRequest?.abort()
  const controller = historyRequest = new AbortController()
  refreshing.value = true
  historyError.value = ''
  pollError.value = ''
  loadSettings()
  try {
    const { data } = await getTasks({ limit: 20 }, { signal: controller.signal })
    if (controller.signal.aborted) return
    items.value = data.items
    total.value = data.total
    active.value = data.active_task
    ready.value = true
  } catch (err) {
    if (!controller.signal.aborted) historyError.value = errorMessage(err, '无法读取任务历史，请刷新。')
  } finally {
    if (!controller.signal.aborted) {
      refreshing.value = false
      schedulePoll()
      loadSelected()
    }
  }
}

function selectTask(id) {
  return router.replace({ query: { task: String(id) } })
}

async function submitReview() {
  if (!canCreate.value) return
  actionError.value = ''
  const keywords = form.keywords.split(/[\n,，]+/).map((word) => word.trim()).filter(Boolean)
  if (!keywords.length || keywords.length > settings.value.review_limits.max_keywords ||
      new Set(keywords.map((word) => word.replace(/\s+/g, ' ').toLowerCase())).size !== keywords.length) {
    actionError.value = `请填写 1–${settings.value.review_limits.max_keywords} 个不重复的关键词。`
    return
  }
  const params = { ...form, keywords, city: form.city.trim() }
  const signature = JSON.stringify(params)
  if (retryBody?.signature !== signature) retryBody = { signature, key: crypto.randomUUID() }
  creating.value = true
  try {
    const { data } = await createTask({ mode: 'review', provider: 'fixture', params, request_key: retryBody.key })
    retryBody = null
    if (!disposed) await selectTask(data.task_id)
  } catch (err) {
    if (!disposed) actionError.value = errorMessage(err, '提交结果未确认。请先查看历史；使用相同参数重试将复用同一个请求。')
    if (err.response && err.response.status < 500) retryBody = null
  } finally {
    if (!disposed) {
      await refresh()
      creating.value = false
    }
  }
}

async function requestStop(task) {
  if (!isActive(task) || task.status === 'stop_requested' || stopping.value || refreshing.value) return
  stopping.value = true
  actionError.value = ''
  stopPolling()
  try {
    const { data } = await stopTask(task.task_id)
    if (disposed) return
    storeTask(data.task)
    if (!isActive(data.task)) loadSettings()
  } catch (err) {
    if (!disposed) actionError.value = errorMessage(err, '停止请求未确认，请查看当前状态。')
  } finally {
    stopping.value = false
    schedulePoll()
  }
}

watch(taskId, loadSelected)
onMounted(refresh)
onUnmounted(() => {
  disposed = true
  stopPolling()
  historyRequest?.abort()
  detailRequest?.abort()
  settingsRequest?.abort()
})
</script>

<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">TASK CENTER</div>
      <h1>任务中心</h1>
      <p>运行 Review 读取样例职位，并查看后台进度。</p>
    </div>
    <el-button :loading="refreshing" :disabled="creating || stopping" @click="refresh">刷新任务</el-button>
  </section>

  <section class="workflow-panel">
    <div class="workflow-title"><h2>创建 Review</h2><el-tag type="info" effect="plain" data-testid="auto-disabled">Auto 已禁用</el-tag></div>
    <el-alert v-if="settingsError" :title="settingsError" type="error" :closable="false" show-icon />
    <template v-if="settings">
      <p v-if="active" class="workflow-note">当前执行槽由 <button type="button" class="workflow-link link-button" @click="selectTask(active.task_id)">任务 #{{ active.task_id }}</button> 占用。</p>
      <p v-if="guard?.state !== 'clear'" class="workflow-note">样例来源的安全闸当前不可用或已锁定，请在 <RouterLink class="workflow-link" :to="{ name: 'settings' }">系统设置</RouterLink> 查看。</p>
      <form class="workflow-fields" @submit.prevent="submitReview">
        <div class="workflow-toolbar">
          <label class="job-filter">Review 来源
            <select :value="settings.search.provider" :disabled="creating">
              <option value="fixture">本地样例</option>
              <option value="boss" disabled>BOSS 来源（未启用）</option>
            </select>
          </label>
          <label class="job-filter">城市<input v-model="form.city" :disabled="creating" maxlength="64" placeholder="不限"></label>
          <label class="job-filter">最多页数<input v-model.number="form.max_pages" type="number" :disabled="creating" min="1" :max="settings.review_limits.max_pages" required></label>
          <label class="job-filter">最多职位数<input v-model.number="form.max_jobs" type="number" :disabled="creating" min="1" :max="settings.review_limits.max_jobs" required></label>
        </div>
        <label class="job-filter">关键词（换行或逗号分隔）
          <textarea v-model="form.keywords" rows="2" maxlength="650" :disabled="creating" required></textarea>
        </label>
        <div><el-button native-type="submit" type="primary" :disabled="!canCreate" :loading="creating">创建 Review</el-button></div>
      </form>
    </template>
    <el-alert v-if="actionError" class="workflow-message" :title="actionError" type="error" :closable="false" show-icon />
  </section>

  <section class="workflow-panel" aria-label="任务详情">
    <div class="workflow-title">
      <h2>任务详情 <span v-if="selected">#{{ selected.task_id }}</span></h2>
      <el-button v-if="isActive(selected)" :disabled="selected.status === 'stop_requested' || stopping || refreshing" :loading="stopping"
        type="warning" plain @click="requestStop(selected)">停止任务</el-button>
    </div>
    <el-alert v-if="pollError || detailError" class="workflow-message" :title="pollError || detailError" type="warning" :closable="false" show-icon />
    <template v-if="selected">
      <div class="workflow-line" aria-live="polite">
        <el-tag :type="taskStates[selected.status]?.[1]" :data-task-status="selected.status">{{ taskStates[selected.status]?.[0] || selected.status }}</el-tag>
        <span>{{ selected.mode === 'review' ? 'Review' : 'Auto' }} · {{ sources[selected.provider] }} · {{ phases[selected.phase] || selected.phase || '—' }}</span>
        <span class="workflow-note">更新于 {{ dateLabel(selected.updated_at) }}</span>
      </div>
      <dl class="workflow-counters">
        <div v-for="(label, key) in counters" :key="key"><dt>{{ label }}</dt><dd>{{ selected.progress[key] ?? 0 }}<template v-if="key === 'keyword_index'"> / {{ selected.progress.keyword_count ?? '—' }}</template></dd></div>
      </dl>
      <p v-if="Object.keys(selected.progress.skipped || {}).length" class="workflow-note">跳过：{{ Object.entries(selected.progress.skipped).map(([reason, count]) => `${reason} × ${count}`).join('、') }}</p>
      <p v-if="selected.stop_reason || selected.error_code" class="workflow-note">结束原因：{{ [...new Set([selected.stop_reason, selected.error_code].filter(Boolean))].join(' / ') }}</p>
      <RouterLink v-if="selected.progress.jobs_saved > 0" class="workflow-link" :to="{ name: 'jobs', query: { source: selected.provider } }">查看此来源的职位</RouterLink>
    </template>
    <p v-else-if="!detailError" class="workflow-note">{{ refreshing || taskId ? '正在读取任务…' : '暂无可查看的任务。' }}</p>
  </section>

  <section class="workflow-panel">
    <div class="workflow-title"><h2>任务历史</h2><span class="workflow-note">最近 {{ items.length }} 条 / 共 {{ total }} 条</span></div>
    <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
    <p v-else-if="!items.length" class="workflow-note">{{ refreshing ? '正在读取历史…' : '暂无历史任务。' }}</p>
    <div v-else class="workflow-table-wrap">
      <table class="workflow-table">
        <thead><tr><th scope="col">任务</th><th scope="col">来源</th><th scope="col">状态</th><th scope="col">创建时间</th><th scope="col">操作</th></tr></thead>
        <tbody>
          <tr v-for="task in items" :key="task.task_id" :data-task-id="task.task_id">
            <td>#{{ task.task_id }} · {{ task.mode === 'review' ? 'Review' : 'Auto' }}</td>
            <td>{{ sources[task.provider] }}</td>
            <td><el-tag size="small" effect="plain" :type="taskStates[task.status]?.[1]">{{ taskStates[task.status]?.[0] }}</el-tag></td>
            <td class="nowrap">{{ dateLabel(task.created_at) }}</td>
            <td><button class="workflow-link link-button" type="button" @click="selectTask(task.task_id)">查看</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
