<template>
  <el-card v-if="attachments.length" :shadow="'never'" :class="['panel-card', { embedded }]">
    <template #header>
      <div class="panel-header">
        <span>现场照片</span>
        <span class="attachment-count">{{ attachments.length }} 个</span>
      </div>
    </template>

    <div class="attachment-grid">
      <a
        v-for="item in attachments"
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
  </el-card>
</template>

<script setup lang="ts">
import { buildApiUrl } from '../api/query'
import type { QueryAttachment } from '../types/query'

defineProps<{
  attachments: QueryAttachment[]
  embedded?: boolean
}>()

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
</style>
