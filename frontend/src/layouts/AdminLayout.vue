<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getHealth, getReady } from '../api/client'

const route = useRoute()
const serviceState = ref('checking')
const lastChecked = ref('')
const checking = ref(false)
let refreshTimer

const navigation = [
  { path: '/dashboard', label: '总览', mark: '概' },
  { path: '/jobs', label: '职位管理', mark: '职' },
  { path: '/applications', label: '投递记录', mark: '投' },
  { path: '/tasks', label: '任务中心', mark: '任' },
  { path: '/settings', label: '系统设置', mark: '设' },
]

const pageTitle = computed(() => route.meta.title || '管理后台')
const connection = computed(() => {
  const states = {
    checking: { label: '正在连接', type: 'info', dot: 'checking' },
    ready: { label: '服务正常', type: 'success', dot: 'online' },
    databaseUnavailable: { label: '数据库不可用', type: 'warning', dot: 'warning' },
    readinessFailed: { label: '就绪检查失败', type: 'warning', dot: 'warning' },
    offline: { label: '后端服务不可用', type: 'danger', dot: 'offline' },
  }
  return states[serviceState.value]
})

const alertContent = computed(() => {
  if (serviceState.value === 'databaseUnavailable') {
    return {
      title: '数据库暂不可用',
      description: '后端 API 正常，但数据库就绪检查未通过。数据库恢复后，页面会自动更新状态。',
      type: 'warning',
    }
  }
  if (serviceState.value === 'readinessFailed') {
    return {
      title: '服务就绪检查未完成',
      description: '健康接口可访问，但就绪接口未返回预期结果。请稍后重试。',
      type: 'warning',
    }
  }
  if (serviceState.value === 'offline') {
    return {
      title: '无法连接后端服务',
      description: '请确认本地 API 已启动。管理台会自动重试，也可以立即重新检查。',
      type: 'error',
    }
  }
  return null
})

async function refreshStatus() {
  if (checking.value) return
  checking.value = true

  try {
    const health = await getHealth()
    if (health.status !== 200 || health.data?.status !== 'ok') {
      serviceState.value = 'offline'
      return
    }

    try {
      const ready = await getReady()
      serviceState.value = ready.status === 200 && ready.data?.status === 'ready'
        ? 'ready'
        : 'readinessFailed'
    } catch (error) {
      serviceState.value = error.response?.status === 503
        ? 'databaseUnavailable'
        : 'readinessFailed'
    }
  } catch {
    serviceState.value = 'offline'
  } finally {
    lastChecked.value = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date())
    checking.value = false
  }
}

onMounted(() => {
  refreshStatus()
  refreshTimer = window.setInterval(refreshStatus, 5000)
})

onUnmounted(() => {
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="admin-shell">
    <aside class="sidebar">
      <div class="brand-lockup">
        <div class="brand-mark">B</div>
        <div>
          <div class="brand-name">职位管理台</div>
          <div class="brand-caption">本地工作空间</div>
        </div>
      </div>

      <div class="nav-caption">工作台</div>
      <el-menu :default-active="route.path" class="side-menu" router>
        <el-menu-item v-for="item in navigation" :key="item.path" :index="item.path">
          <span class="nav-mark" aria-hidden="true">{{ item.mark }}</span>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footnote">
        <span class="footnote-dot"></span>
        <span>单机本地运行</span>
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div class="breadcrumb-line">
          <span>工作台</span>
          <span class="breadcrumb-divider">/</span>
          <strong>{{ pageTitle }}</strong>
        </div>
        <div class="topbar-status">
          <span class="connection-dot" :class="connection.dot"></span>
          <span class="connection-label">{{ connection.label }}</span>
          <span v-if="lastChecked" class="checked-time">检查于 {{ lastChecked }}</span>
          <el-button
            class="refresh-button"
            text
            :loading="checking"
            aria-label="重新检查服务状态"
            @click="refreshStatus"
          >
            重新检查
          </el-button>
        </div>
      </header>

      <main class="page-area">
        <el-alert
          v-if="alertContent"
          class="connection-alert"
          :title="alertContent.title"
          :description="alertContent.description"
          :type="alertContent.type"
          show-icon
          :closable="false"
        />
        <RouterView />
      </main>
    </section>
  </div>
</template>
