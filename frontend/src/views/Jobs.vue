<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJob, getJobs } from '../api/client'
import { sourceFrom } from '../workflow'

const PAGE_SIZE_OPTIONS = [5, 10, 20]
const route = useRoute()

const filters = reactive({
  source: sourceFrom(route.query.source),
  q: '',
  job_type: '',
  recommended: route.query.recommended === 'true' ? 'true' : '',
  min_score: '',
})

const requestFilters = ref({ ...filters })
const page = ref(1)
const pageSize = ref(5)
const retryVersion = ref(0)
const jobs = ref([])
const total = ref(0)
const loading = ref(false)
const listError = ref('')

const detailVisible = ref(false)
const selectedJob = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
let listController
let detailController

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const firstResult = computed(() => total.value === 0 ? 0 : (page.value - 1) * pageSize.value + 1)
const lastResult = computed(() => Math.min(page.value * pageSize.value, total.value))

function applyFilters() {
  page.value = 1
  requestFilters.value = {
    source: filters.source,
    q: filters.q.trim(),
    job_type: filters.job_type,
    recommended: filters.recommended,
    min_score: filters.min_score === '' ? '' : Number(filters.min_score),
  }
}

function clearFilters() {
  Object.assign(filters, { source: 'fixture', q: '', job_type: '', recommended: '', min_score: '' })
  applyFilters()
}

function retryList() {
  retryVersion.value += 1
}

function changePageSize(event) {
  pageSize.value = Number(event.target.value)
  page.value = 1
}

function reasonsFor(job) {
  const reasons = job?.score_reasons
  if (Array.isArray(reasons)) {
    return reasons.map((reason) => {
      if (typeof reason === 'string') return reason
      if (reason && typeof reason === 'object') {
        return reason.reason || reason.message || reason.label || reason.rule_id || JSON.stringify(reason)
      }
      return String(reason)
    })
  }
  if (reasons && typeof reasons === 'object') {
    if (Array.isArray(reasons.reasons)) return reasons.reasons.map(String)
    return Object.entries(reasons).map(([key, value]) => `${key}：${String(value)}`)
  }
  return []
}

function scoreLabel(score) {
  return score === null || score === undefined ? '未评分' : `${Number(score).toFixed(0)} 分`
}

function sourceLabel(source) {
  return source === 'boss' ? 'BOSS 来源' : '本地样例'
}

function priorityLabel(priority) {
  return priority === null || priority === undefined ? '未分类' : `P${priority}`
}

async function openDetail(job) {
  detailController?.abort()
  detailController = new AbortController()
  const controller = detailController

  detailVisible.value = true
  selectedJob.value = job
  detail.value = null
  detailError.value = ''
  detailLoading.value = true

  try {
    const response = await getJob(job.id, { signal: controller.signal })
    if (!controller.signal.aborted) detail.value = response.data
  } catch (error) {
    if (!controller.signal.aborted) {
      detailError.value = error.response?.data?.detail?.message || '职位详情加载失败，请重试。'
    }
  } finally {
    if (!controller.signal.aborted) detailLoading.value = false
  }
}

function retryDetail() {
  const job = jobs.value.find((item) => item.id === selectedJob.value?.id) || selectedJob.value
  if (job) openDetail(job)
}

function closeDetail() {
  detailVisible.value = false
  detailController?.abort()
  detailController = undefined
  selectedJob.value = null
  detail.value = null
  detailError.value = ''
  detailLoading.value = false
}

watch(
  () => [
    requestFilters.value.source,
    requestFilters.value.q,
    requestFilters.value.job_type,
    requestFilters.value.recommended,
    requestFilters.value.min_score,
    page.value,
    pageSize.value,
    retryVersion.value,
  ],
  async ([source, q, jobType, recommended, minScore, pageNumber, size]) => {
    listController?.abort()
    listController = new AbortController()
    const controller = listController
    const params = { source, page: pageNumber, page_size: size }

    if (q) params.q = q
    if (jobType) params.job_type = jobType
    if (recommended !== '') params.recommended = recommended
    if (minScore !== '') params.min_score = minScore

    jobs.value = []
    total.value = 0
    listError.value = ''
    loading.value = true

    try {
      const response = await getJobs(params, { signal: controller.signal })
      if (controller.signal.aborted) return
      jobs.value = response.data.items
      total.value = response.data.total
    } catch (error) {
      if (!controller.signal.aborted) {
        listError.value = error.response?.data?.detail?.message || '职位列表加载失败，请检查后端服务后重试。'
      }
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  listController?.abort()
  detailController?.abort()
})
</script>

<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">JOB LIBRARY</div>
      <h1>职位管理</h1>
      <p>查看已收集的职位、匹配评分和岗位详情。</p>
    </div>
    <el-tag class="fixture-pill" effect="plain" round type="warning">{{ sourceLabel(requestFilters.source) }}</el-tag>
  </section>

  <section class="jobs-board" aria-label="职位列表">
    <form class="jobs-filters" aria-label="职位筛选" @submit.prevent="applyFilters">
      <label class="job-filter job-filter-source">
        <span>数据来源</span>
        <select v-model="filters.source" aria-label="数据来源">
          <option value="fixture">本地样例</option>
          <option value="boss">BOSS 来源</option>
        </select>
      </label>
      <label class="job-filter job-filter-keyword">
        <span>关键词</span>
        <input v-model="filters.q" type="search" maxlength="128" placeholder="职位、公司或城市" aria-label="搜索职位、公司或城市">
      </label>
      <label class="job-filter">
        <span>职位类型</span>
        <select v-model="filters.job_type" aria-label="职位类型">
          <option value="">全部类型</option>
          <option value="实习">实习</option>
          <option value="校招">校招</option>
          <option value="社招">社招</option>
        </select>
      </label>
      <label class="job-filter">
        <span>推荐</span>
        <select v-model="filters.recommended" aria-label="推荐筛选">
          <option value="">全部</option>
          <option value="true">仅推荐</option>
          <option value="false">未推荐</option>
        </select>
      </label>
      <label class="job-filter job-filter-score">
        <span>最低分</span>
        <input v-model="filters.min_score" type="number" min="0" max="100" step="1" placeholder="不限" aria-label="最低分数">
      </label>
      <div class="filter-actions">
        <el-button native-type="submit" type="primary">筛选</el-button>
        <el-button native-type="button" @click="clearFilters">重置</el-button>
      </div>
    </form>

    <div v-if="listError" class="jobs-state jobs-state-error" role="alert">
      <div class="jobs-state-mark" aria-hidden="true">!</div>
      <div>
        <h2>暂时无法加载职位</h2>
        <p>{{ listError }}</p>
        <el-button type="primary" @click="retryList">重新加载</el-button>
      </div>
    </div>
    <div v-else-if="loading" class="jobs-state" role="status" aria-live="polite">
      <div class="jobs-loading-dots" aria-hidden="true"><i></i><i></i><i></i></div>
      <h2>正在加载职位</h2>
      <p>正在读取当前来源的职位列表。</p>
    </div>
    <div v-else-if="jobs.length === 0" class="jobs-state">
      <div class="jobs-state-mark" aria-hidden="true">空</div>
      <h2>{{ total === 0 && requestFilters.q ? '没有匹配的职位' : requestFilters.source === 'boss' ? '该来源暂时没有职位' : '职位列表为空' }}</h2>
      <p>{{ requestFilters.source === 'boss' ? '当前样例只包含本地 fixture 数据。' : '试试调整筛选条件，或重置后查看全部本地样例。' }}</p>
      <el-button v-if="requestFilters.source === 'fixture'" @click="clearFilters">重置筛选</el-button>
    </div>
    <template v-else>
      <div class="jobs-summary">
        <span>共 {{ total }} 个职位</span>
        <span>数据来源：{{ sourceLabel(requestFilters.source) }}</span>
      </div>

      <div class="jobs-table-wrap">
        <table class="jobs-table">
          <thead>
            <tr>
              <th scope="col">职位与公司</th>
              <th scope="col">地点与薪资</th>
              <th scope="col">类型</th>
              <th scope="col">Priority</th>
              <th scope="col">Score</th>
              <th scope="col">推荐原因</th>
              <th scope="col"><span class="sr-only">职位详情</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id" :data-job-id="job.id">
              <td class="job-title-cell">
                <button class="job-title-link" type="button" @click="openDetail(job)">{{ job.title }}</button>
                <span class="job-company">{{ job.company }}</span>
                <el-tag class="row-source-tag" effect="plain" size="small" type="warning">{{ sourceLabel(job.source) }}</el-tag>
              </td>
              <td class="job-meta-cell">
                <span>{{ job.city || '未填写' }}</span>
                <span>{{ job.salary_text || '薪资未填写' }}</span>
                <span>{{ job.experience_text || '经验未填写' }}</span>
              </td>
              <td><el-tag effect="plain" size="small">{{ job.job_type || '未分类' }}</el-tag></td>
              <td><span class="priority-mark" :class="`priority-mark-${job.priority ?? 'unknown'}`">{{ priorityLabel(job.priority) }}</span></td>
              <td><span class="job-score" :class="{ 'job-score-empty': job.score === null || job.score === undefined }">{{ scoreLabel(job.score) }}</span></td>
              <td class="job-reasons-cell">
                <span v-if="reasonsFor(job).length" v-for="reason in reasonsFor(job)" :key="reason" class="job-reason">{{ reason }}</span>
                <span v-else class="muted-text">{{ job.jd_state === 'missing' ? '缺少 JD，暂不推荐' : '暂无评分理由' }}</span>
              </td>
              <td><el-button text type="primary" @click="openDetail(job)">查看详情</el-button></td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="jobs-pagination" aria-label="职位分页">
        <span class="pagination-summary">显示 {{ firstResult }}–{{ lastResult }}，共 {{ total }} 个职位</span>
        <div class="pagination-controls">
          <label class="page-size-picker">每页
            <select :value="pageSize" aria-label="每页显示条数" @change="changePageSize">
              <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">{{ size }} 条</option>
            </select>
          </label>
          <el-button :disabled="page <= 1" aria-label="上一页" @click="page -= 1">上一页</el-button>
          <span class="pagination-current" aria-live="polite">第 {{ page }} / {{ pageCount }} 页</span>
          <el-button :disabled="page >= pageCount" aria-label="下一页" @click="page += 1">下一页</el-button>
        </div>
      </footer>
    </template>
  </section>

  <el-drawer
    v-model="detailVisible"
    title="职位详情"
    direction="rtl"
    size="min(580px, 100%)"
    class="job-detail-drawer"
    @closed="closeDetail"
  >
    <template v-if="detailLoading">
      <div class="detail-loading" role="status" aria-live="polite">正在读取完整职位详情…</div>
    </template>
    <div v-else-if="detailError" class="detail-error" role="alert">
      <h2>详情暂时无法加载</h2>
      <p>{{ detailError }}</p>
      <el-button type="primary" @click="retryDetail">重新加载</el-button>
    </div>
    <article v-else-if="detail" class="job-detail-content">
      <div class="detail-badges">
        <el-tag effect="plain" type="warning">{{ sourceLabel(detail.source) }}</el-tag>
        <el-tag effect="plain">{{ detail.job_type || '未分类' }}</el-tag>
        <span class="priority-mark" :class="`priority-mark-${detail.priority ?? 'unknown'}`">Priority {{ priorityLabel(detail.priority) }}</span>
      </div>
      <h2>{{ detail.title }}</h2>
      <p class="detail-company">{{ detail.company }}</p>
      <p class="workflow-note">职位 ID <strong>{{ detail.id }}</strong></p>
      <RouterLink class="workflow-link" :to="{ name: 'applications', query: { source: detail.source, job: detail.id } }">建立待投递记录</RouterLink>
      <dl class="detail-facts">
        <div><dt>地点</dt><dd>{{ detail.city || '未填写' }}</dd></div>
        <div><dt>薪资</dt><dd>{{ detail.salary_text || '未填写' }}</dd></div>
        <div><dt>经验要求</dt><dd>{{ detail.experience_text || '未填写' }}</dd></div>
        <div><dt>匹配分数</dt><dd>{{ scoreLabel(detail.score) }}</dd></div>
        <div><dt>推荐</dt><dd>{{ detail.recommended ? '推荐' : '暂不推荐' }}</dd></div>
        <div><dt>评分规则</dt><dd>{{ detail.scoring_version || '未评分' }}</dd></div>
      </dl>
      <section class="detail-section">
        <h3>推荐原因与评分说明</h3>
        <ul v-if="reasonsFor(detail).length" class="detail-reason-list">
          <li v-for="reason in reasonsFor(detail)" :key="reason">{{ reason }}</li>
        </ul>
        <p v-else class="muted-text">{{ detail.jd_state === 'missing' ? '该职位缺少 JD，因此未计算评分，也不会推荐。' : '尚无评分说明。' }}</p>
      </section>
      <section class="detail-section">
        <h3>职位描述（纯文本）</h3>
        <div v-if="detail.jd_text" class="job-description">{{ detail.jd_text }}</div>
        <p v-else class="jd-empty">{{ detail.jd_state === 'unavailable' ? 'JD 暂时无法获取。' : '该职位没有可展示的 JD。' }}</p>
      </section>
    </article>
  </el-drawer>
</template>
