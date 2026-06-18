<template>
  <el-card v-if="attachments.length" :shadow="'never'" :class="['panel-card', { embedded }]">
    <template #header>
      <div class="panel-header">
        <span>现场资料</span>
        <span class="attachment-count">{{ attachments.length }} 项</span>
      </div>
    </template>

    <section v-if="photoAttachments.length" class="asset-section">
      <div class="section-title">
        <h4>现场照片</h4>
        <span>点击查看大图</span>
      </div>
      <div class="attachment-grid">
      <a
        v-for="item in photoAttachments"
        :key="`${item.monitoring_id}-${item.label}-${item.path}`"
        class="attachment-item"
        :href="resolveUrl(item.url)"
        target="_blank"
        rel="noreferrer"
      >
        <img
          v-if="item.type === 'image'"
          :src="resolveUrl(item.url)"
          :alt="item.label"
          loading="lazy"
        />
        <div v-else class="video-placeholder">视频</div>
        <div class="attachment-meta">
          <strong>{{ item.label }}</strong>
          <span>{{ item.hcs_code || '-' }} {{ item.hcs_name || '' }}</span>
          <span v-if="item.photo_on">拍摄时间：{{ item.photo_on }}</span>
        </div>
      </a>
      </div>
    </section>

    <section v-if="chartAttachments.length" class="asset-section chart-section">
      <div class="section-title">
        <h4>监测点位移变化图</h4>
        <span>按X/Y/H三向位移变化量展示</span>
      </div>
      <a
        v-for="item in chartAttachments"
        :key="`${item.monitoring_id}-${item.label}-${item.path}`"
        class="chart-card"
        :href="resolveUrl(item.url)"
        target="_blank"
        rel="noreferrer"
      >
        <img :src="resolveUrl(item.url)" :alt="item.label" loading="lazy" decoding="async" />
        <div class="chart-meta">
          <strong>{{ item.label }}</strong>
          <span>{{ item.hcs_code || '-' }} {{ item.hcs_name || '' }}</span>
        </div>
      </a>
    </section>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { buildApiUrl } from '../api/query'
import type { QueryAttachment } from '../types/query'

const props = defineProps<{
  attachments: QueryAttachment[]
  embedded?: boolean
}>()

const chartAttachments = computed(() =>
  props.attachments.filter((item) => item.type === 'image' && /位移变化|曲线图|变化曲线/.test(item.label || '')),
)

const photoAttachments = computed(() =>
  props.attachments.filter((item) => !chartAttachments.value.includes(item)),
)

const resolveUrl = (url: string) => {
  if (!url || /^https?:\/\//i.test(url)) {
    return url
  }
  return buildApiUrl(url)
}
</script>

<style scoped>
.panel-card {
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.panel-card.embedded {
  border-color: #e5ecea;
  background: #fff;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.attachment-count {
  color: #5f6f86;
  font-size: 13px;
  font-weight: 400;
}

.asset-section + .asset-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e6edf7;
}

.section-title {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.section-title h4 {
  margin: 0;
  color: #172033;
  font-size: 15px;
}

.section-title span {
  color: #667085;
  font-size: 12px;
}

.attachment-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.attachment-item {
  display: grid;
  gap: 8px;
  color: inherit;
  text-decoration: none;
}

.attachment-item img,
.video-placeholder {
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 8px;
  border: 1px solid #e5ecea;
  background: #f5f7fa;
  object-fit: cover;
}

.video-placeholder {
  display: grid;
  place-items: center;
  color: #5f6f86;
  font-size: 15px;
  font-weight: 700;
}

.attachment-meta {
  display: grid;
  gap: 3px;
  color: #4b5b70;
  font-size: 12px;
  line-height: 1.45;
}

.attachment-meta strong {
  color: #1f2d3d;
  font-size: 13px;
}

.chart-section {
  display: grid;
  gap: 10px;
}

.chart-card {
  display: grid;
  gap: 10px;
  padding: 10px;
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  background: #fff;
  color: inherit;
  text-decoration: none;
}

.chart-card img {
  display: block;
  width: 100%;
  max-height: 520px;
  object-fit: contain;
  border: 1px solid #e5eaf3;
  border-radius: 8px;
  background: #fff;
}

.chart-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  color: #667085;
  font-size: 13px;
}

.chart-meta strong {
  color: #172033;
  font-size: 14px;
}

@media (max-width: 640px) {
  .section-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .chart-card {
    padding: 8px;
  }
}
</style>
