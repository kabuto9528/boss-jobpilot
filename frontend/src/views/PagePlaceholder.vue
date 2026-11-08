<script setup>
defineProps({
  eyebrow: { type: String, required: true },
  title: { type: String, required: true },
  description: { type: String, required: true },
  icon: { type: String, required: true },
})
</script>

<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <div class="heading-icon" aria-hidden="true">{{ icon }}</div>
  </section>

  <section class="placeholder-card">
    <div class="placeholder-symbol" aria-hidden="true">{{ icon }}</div>
    <div class="placeholder-copy">
      <div class="placeholder-kicker">页面入口已就绪</div>
      <h2>{{ title }}</h2>
      <p>导航与前后端通信已接通。业务内容将在后续阶段逐步加入。</p>
    </div>
    <el-tag effect="plain" round type="info">阶段 3 · 占位页面</el-tag>
  </section>
</template>
