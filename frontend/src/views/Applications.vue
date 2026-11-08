<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { addApplication, getApplications, getJob, getJobs, resolveApplication } from '../api/client'
import { applicationStates, dateLabel, errorMessage, sourceFrom, sources } from '../workflow'

const route = useRoute()
const router = useRouter()
const source = computed(() => sourceFrom(route.query.source))
const status = computed(() => Object.hasOwn(applicationStates, route.query.status) ? route.query.status : '')
const page = ref(1)
const size = 10
const list = ref(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const dialog = ref(false)
const record = ref(null)
const search = ref('')
const options = ref([])
const jobId = ref(null)
const jobLoading = ref(false)
const outcome = ref('')
const evidence = ref('')
const saving = ref(false)
const actionError = ref('')
let listRequest, jobRequest
let disposed = false
const pages = computed(() => Math.max(1, Math.ceil((list.value?.total ?? 0) / size)))
const originLabels = { manual: '人工登记', fixture: '样例记录', auto: '自动任务' }

async function load() {
  listRequest?.abort()
  const controller = listRequest = new AbortController()
  loading.value = true
  list.value = null
  error.value = ''
  try {
    const { data } = await getApplications(
      { source: source.value, status: status.value || undefined, page: page.value, page_size: size },
      { signal: controller.signal },
    )
    if (controller.signal.aborted) return
    const last = Math.max(1, Math.ceil(data.total / size))
    if (page.value > last) page.value = last
    else list.value = data
  } catch (err) {
    if (!controller.signal.aborted) error.value = errorMessage(err, '无法加载投递记录。')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

function setFilters(nextSource, nextStatus = '') {
  page.value = 1
  notice.value = ''
  router.replace({ query: { source: nextSource, status: nextStatus || undefined } })
}

async function findJobs(preset) {
  jobRequest?.abort()
  const controller = jobRequest = new AbortController()
  jobId.value = null
  options.value = []
  jobLoading.value = true
  actionError.value = ''
  try {
    if (preset) {
      const { data } = await getJob(preset, { signal: controller.signal })
      if (!controller.signal.aborted && data.source === source.value) {
        options.value = [data]
        jobId.value = data.id
      }
    } else {
      const { data } = await getJobs({ source: source.value, q: search.value.trim() || undefined, page_size: 20 }, { signal: controller.signal })
      if (!controller.signal.aborted) options.value = data.items
    }
  } catch (err) {
    if (!controller.signal.aborted) actionError.value = errorMessage(err, '无法加载候选职位，请重新搜索。')
  } finally {
    if (!controller.signal.aborted) jobLoading.value = false
  }
}

function openAdd(preset) {
  record.value = null
  search.value = ''
  dialog.value = true
  findJobs(preset)
}

function openResolve(row) {
  record.value = row
  evidence.value = ''
  outcome.value = ''
  actionError.value = ''
  dialog.value = true
}

async function save() {
  if (saving.value || (record.value ? !outcome.value || !evidence.value.trim() : !jobId.value)) return
  const resolving = Boolean(record.value)
  saving.value = true
  actionError.value = ''
  try {
    const { data } = resolving
      ? await resolveApplication(record.value.id, { status: outcome.value, evidence_summary: evidence.value.trim() })
      : await addApplication(jobId.value)
    if (disposed) return
    dialog.value = false
    page.value = 1
    if (status.value !== data.status) await router.replace({ query: { source: data.job.source, status: data.status } })
    else await load()
    notice.value = resolving ? `已保存人工确认：${applicationStates[data.status][0]}。` : '已建立待投递记录。'
  } catch (err) {
    if (!disposed) actionError.value = errorMessage(err, '保存结果未确认，请查看列表后再试。')
  } finally {
    saving.value = false
  }
}

watch([source, status], () => { page.value = 1 }, { flush: 'sync' })
watch([source, status, page], load, { immediate: true })
watch(dialog, (open) => { if (!open) jobRequest?.abort() })
onMounted(() => {
  const preset = Number(route.query.job)
  if (Number.isSafeInteger(preset) && preset > 0) {
    router.replace({ query: { source: source.value, status: status.value || undefined } })
    openAdd(preset)
  }
})
onUnmounted(() => {
  disposed = true
  listRequest?.abort()
  jobRequest?.abort()
})
</script>

<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">APPLICATIONS</div>
      <h1>投递记录</h1>
      <p>建立待投递清单，核对后人工登记结果。所有操作仅写入本地记录。</p>
    </div>
    <el-button type="primary" @click="openAdd()">新建待投递</el-button>
  </section>

  <section class="workflow-panel">
    <div class="workflow-toolbar">
      <label class="job-filter">数据来源
        <select :value="source" @change="setFilters($event.target.value, status)">
          <option v-for="(label, key) in sources" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <label class="job-filter">投递状态
        <select :value="status" @change="setFilters(source, $event.target.value)">
          <option value="">全部状态</option>
          <option v-for="([label], key) in applicationStates" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <p v-if="notice" class="workflow-success" role="status">{{ notice }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-else-if="loading" class="workflow-empty" role="status">正在读取投递记录…</div>
    <template v-else-if="list">
      <p v-if="!list.items.length" class="workflow-empty">该来源和状态暂无记录。</p>
      <div v-else class="workflow-table-wrap">
        <table class="workflow-table application-table">
          <thead><tr><th scope="col">职位</th><th scope="col">状态</th><th scope="col">登记与任务</th><th scope="col">最近依据</th><th scope="col">更新时间</th><th scope="col">操作</th></tr></thead>
          <tbody>
            <tr v-for="row in list.items" :key="row.id" :data-application-id="row.id" :data-status="row.status">
              <td><strong>{{ row.job.title }}</strong><small>{{ row.job.company }} · {{ sources[row.job.source] }}</small></td>
              <td><el-tag :type="applicationStates[row.status][1]" :effect="row.status === 'uncertain' ? 'dark' : 'plain'">{{ applicationStates[row.status][0] }}</el-tag></td>
              <td>{{ originLabels[row.origin] }}<small v-if="row.task_id"><RouterLink class="workflow-link" :to="{ name: 'tasks', query: { task: row.task_id } }">任务 #{{ row.task_id }}</RouterLink></small></td>
              <td class="evidence-cell">{{ row.evidence_summary || '—' }}</td>
              <td class="nowrap">{{ dateLabel(row.updated_at) }}</td>
              <td><el-button v-if="['pending', 'uncertain'].includes(row.status)" text type="primary" @click="openResolve(row)">人工确认</el-button><span v-else>—</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer class="workflow-line workflow-pager">
        <span>共 {{ list.total }} 条记录</span>
        <el-button size="small" :disabled="page <= 1" @click="page--">上一页</el-button>
        <span>第 {{ page }} / {{ pages }} 页</span>
        <el-button size="small" :disabled="page >= pages" @click="page++">下一页</el-button>
      </footer>
    </template>
  </section>

  <el-dialog v-model="dialog" :title="record ? '人工确认投递结果' : '新建待投递'" width="min(540px, 94vw)"
    :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
    <div v-if="record" class="workflow-fields">
      <p class="workflow-note">{{ record.job.title }} · {{ sources[record.job.source] }}。请先核对{{ record.job.source === 'boss' ? '官方页面' : '样例依据' }}，再登记结果。</p>
      <label class="job-filter">确认结果
        <select v-model="outcome" :disabled="saving">
          <option value="">选择结果</option><option value="succeeded">已投递</option><option value="failed">失败（已确认未完成）</option>
        </select>
      </label>
      <label class="job-filter">核对依据
        <textarea v-model="evidence" rows="3" maxlength="500" placeholder="简述看到的结果，不填账号或会话信息" :disabled="saving"></textarea>
      </label>
    </div>
    <div v-else class="workflow-fields">
      <p class="workflow-note">为 {{ sources[source] }} 的职位建立一条待投递记录。</p>
      <form class="workflow-toolbar" @submit.prevent="findJobs()">
        <label class="job-filter">搜索职位
          <input v-model="search" type="search" maxlength="128" placeholder="职位、公司或城市" :disabled="saving">
        </label>
        <el-button native-type="submit" :disabled="saving" :loading="jobLoading">搜索</el-button>
      </form>
      <label class="job-filter">选择职位
        <select v-model="jobId" :disabled="jobLoading || saving">
          <option :value="null">{{ jobLoading ? '正在加载…' : options.length ? '请选择（最多显示 20 条）' : '暂无匹配职位' }}</option>
          <option v-for="job in options" :key="job.id" :value="job.id">{{ job.title }} · {{ job.company }} (#{{ job.id }})</option>
        </select>
      </label>
    </div>
    <el-alert v-if="actionError" class="workflow-message" :title="actionError" type="error" :closable="false" show-icon />
    <template #footer>
      <el-button :disabled="saving" @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="saving || (record ? !outcome || !evidence.trim() : jobLoading || !jobId)" @click="save">
        {{ record ? '保存人工确认' : '建立待投递' }}
      </el-button>
    </template>
  </el-dialog>
</template>
