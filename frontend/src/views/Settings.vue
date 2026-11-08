<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { acknowledgeGuard, getSettings } from '../api/client'
import { dateLabel, errorMessage, sources } from '../workflow'

const settings = ref(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const dialog = ref(false)
const selected = ref(null)
const confirmed = ref(false)
const saving = ref(false)
const actionError = ref('')
let request
let disposed = false
const guardLabels = { clear: ['未锁定', 'success'], blocked: ['已锁定', 'warning'], unavailable: ['不可用', 'danger'] }
const loginLabels = { not_required: '无需登录', not_checked: '未检测' }

async function load() {
  request?.abort()
  const controller = request = new AbortController()
  loading.value = true
  error.value = ''
  try {
    const { data } = await getSettings({ signal: controller.signal })
    if (!controller.signal.aborted) settings.value = data
  } catch (err) {
    if (!controller.signal.aborted) {
      settings.value = null
      error.value = errorMessage(err, '无法加载生效配置。')
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

function confirmGuard(guard) {
  selected.value = guard
  confirmed.value = false
  actionError.value = ''
  dialog.value = true
}

async function unlock() {
  if (!confirmed.value || saving.value) return
  saving.value = true
  actionError.value = ''
  try {
    await acknowledgeGuard(selected.value)
    if (disposed) return
    dialog.value = false
    notice.value = `${sources[selected.value.provider]}的安全闸已解除。旧任务不会续跑。`
    await load()
  } catch (err) {
    if (!disposed) actionError.value = errorMessage(err, '解除结果未确认，请刷新后核对。')
  } finally {
    saving.value = false
  }
}

onMounted(load)
onUnmounted(() => {
  disposed = true
  request?.abort()
})
</script>

<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">SETTINGS</div>
      <h1>系统设置</h1>
      <p>查看生效配置、来源能力与安全闸。</p>
    </div>
    <el-button :loading="loading" @click="load">刷新配置</el-button>
  </section>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <p v-else-if="loading && !settings" class="workflow-panel workflow-empty" role="status">正在读取配置…</p>
  <template v-if="settings">
    <section class="workflow-panel">
      <div class="workflow-title"><h2>来源能力与安全闸</h2><el-tag type="info" effect="plain">Auto 已禁用</el-tag></div>
      <p v-if="notice" class="workflow-success" role="status">{{ notice }}</p>
      <p v-if="settings.task_busy" class="workflow-note">有任务进行中，结束后可刷新并解除安全闸。</p>
      <div class="workflow-table-wrap">
        <table class="workflow-table">
          <thead><tr><th scope="col">数据来源</th><th scope="col">Review</th><th scope="col">登录状态</th><th scope="col">安全闸</th><th scope="col">操作</th></tr></thead>
          <tbody>
            <tr v-for="guard in settings.guards" :key="guard.provider" :data-guard="guard.provider">
              <td><strong>{{ sources[guard.provider] }}</strong></td>
              <td>{{ settings.capabilities[guard.provider].review_enabled ? '已启用' : '未启用' }}</td>
              <td>{{ loginLabels[settings.capabilities[guard.provider].login.status] }}<small>检查时间：{{ dateLabel(settings.capabilities[guard.provider].login.checked_at) }}</small></td>
              <td>
                <el-tag :type="guardLabels[guard.state][1]" :data-guard-state="guard.state" effect="plain">{{ guardLabels[guard.state][0] }}</el-tag>
                <small v-if="guard.reason_code">{{ guard.reason_code }} · {{ dateLabel(guard.blocked_at) }}</small>
                <small v-if="guard.task_id"><RouterLink class="workflow-link" :to="{ name: 'tasks', query: { task: guard.task_id } }">任务 #{{ guard.task_id }}</RouterLink></small>
                <small v-if="guard.acknowledged_at">已人工解除：{{ dateLabel(guard.acknowledged_at) }}</small>
              </td>
              <td><el-button v-if="guard.state === 'blocked'" :disabled="loading || settings.task_busy" type="warning" plain @click="confirmGuard(guard)">解除安全闸</el-button><span v-else>—</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="workflow-panel">
      <div class="workflow-title"><h2>Review 搜索与运行</h2><span class="workflow-note">只读</span></div>
      <dl class="workflow-facts">
        <div><dt>默认来源</dt><dd>{{ sources[settings.search.provider] }}</dd></div>
        <div><dt>默认关键词</dt><dd>{{ settings.search.keywords.join('、') }}</dd></div>
        <div><dt>默认城市</dt><dd>{{ settings.search.city || '不限' }}</dd></div>
        <div><dt>关键词上限</dt><dd>{{ settings.review_limits.max_keywords }} 个</dd></div>
        <div><dt>页数（默认 / 上限）</dt><dd>{{ settings.search.max_pages }} / {{ settings.review_limits.max_pages }}</dd></div>
        <div><dt>职位数（默认 / 上限）</dt><dd>{{ settings.search.max_jobs }} / {{ settings.review_limits.max_jobs }}</dd></div>
        <div><dt>任务轮询间隔</dt><dd>{{ settings.poll_interval_ms / 1000 }} 秒</dd></div>
        <div><dt>浏览器超时</dt><dd>{{ settings.browser_timeout_ms / 1000 }} 秒</dd></div>
      </dl>
    </section>

    <section class="workflow-panel">
      <div class="workflow-title"><h2>评分规则</h2><el-tag effect="plain">{{ settings.scoring.version }}</el-tag></div>
      <dl class="workflow-facts">
        <div><dt>基础分</dt><dd>{{ settings.scoring.base }}</dd></div>
        <div><dt>分数区间</dt><dd>{{ settings.scoring.minimum }}–{{ settings.scoring.maximum }}</dd></div>
        <div><dt>推荐阈值</dt><dd>{{ settings.scoring.recommendation_threshold }}</dd></div>
        <div><dt>职位优先级</dt><dd>实习 P{{ settings.scoring.type_priority.internship }} / 校招 P{{ settings.scoring.type_priority.campus }} / 初级 P{{ settings.scoring.type_priority.junior }} / 社招 P{{ settings.scoring.type_priority.social }}</dd></div>
      </dl>
      <details class="workflow-details">
        <summary>展开评分权重和扣分</summary>
        <dl class="workflow-facts">
          <div><dt>岗位方向（最多 {{ settings.scoring.directions_maximum_rules }} 项）</dt><dd>{{ settings.scoring.directions.map((r) => `${r.label} +${r.points}`).join('、') }}</dd></div>
          <div><dt>招聘匹配（最高 {{ settings.scoring.recruitment_maximum_points }} 分）</dt><dd>{{ settings.scoring.recruitment.map((r) => `${r.label} +${r.points}`).join('、') }}</dd></div>
          <div><dt>技能匹配（最高 {{ settings.scoring.skills_maximum_points }} 分）</dt><dd>{{ settings.scoring.skills.map((r) => `${r.label} +${r.points}`).join('、') }}</dd></div>
          <div><dt>经验扣分</dt><dd>{{ settings.scoring.experience.thresholds.map((r) => `${r.years} 年及以上 −${r.deduction}`).join('、') }}；高级岗位 −{{ settings.scoring.experience.senior_deduction }}</dd></div>
          <div><dt>排除推荐</dt><dd>最低要求 {{ settings.scoring.experience.hard_exclude_min_years }} 年经验；{{ settings.scoring.hard_exclusions.join('、') }}</dd></div>
        </dl>
      </details>
    </section>
  </template>

  <el-dialog v-model="dialog" title="人工解除安全闸" width="min(500px, 94vw)"
    :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
    <div v-if="selected" class="workflow-fields">
      <p class="workflow-note">{{ sources[selected.provider] }} · {{ selected.reason_code || '安全停止' }}。解除后只影响下一次新任务。</p>
      <label class="workflow-line"><input v-model="confirmed" type="checkbox" :disabled="saving">我已人工检查并处理本次风险。</label>
      <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="dialog = false">取消</el-button>
      <el-button type="warning" :loading="saving" :disabled="!confirmed || saving" @click="unlock">确认解除</el-button>
    </template>
  </el-dialog>
</template>
