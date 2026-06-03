<template>
  <section class="qmqf-dashboard">
    <div class="dashboard-head">
      <div>
        <h3>{{ data?.title || '近期群测群防监测情况' }}</h3>
        <p>{{ data?.description || '正在读取近期群测群防监测情况' }}</p>
      </div>
      <div class="dashboard-actions">
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        <el-button size="small" type="primary" :disabled="loading || !items.length" @click="downloadPdf">下载PDF</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" />

    <div v-if="loading && !items.length" class="dashboard-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在汇总异常监测记录</span>
    </div>

    <section v-if="!loading || items.length" class="conclusion-panel">
      <h4>监测结论</h4>
      <p>湖北省纳入监测的 525 处高切坡中，绝大多数处于正常状态。本次群测群防记录识别到 {{ items.length }} 处存在现场异常记录的高切坡，异常类型主要涉及{{ abnormalText }}。</p>
      <p>综合现场照片和记录状态看，当前异常对象整体属于可复核、可跟踪范围，暂未形成需要整体提升风险等级的普遍性异常。后续宜对照片反映较明显、重复出现异常或状态持续变化的对象保持跟踪。</p>
    </section>

    <ReportBarChart
      v-if="abnormalChartItems.length"
      title="群测群防异常类型统计"
      unit="处"
      :items="abnormalChartItems"
    />

    <div v-if="!loading || items.length" class="abnormal-grid">
      <article v-for="item in items" :key="item.gqpbh" class="abnormal-card">
        <div class="card-top">
          <div>
            <strong>{{ slopeTitle(item) }}</strong>
            <span>{{ item.photo_on || item.created_on || '记录时间待核实' }}</span>
          </div>
        </div>

        <strong class="abnormal-text">{{ item.abnormal_types?.length ? item.abnormal_types.join('、') : '存在异常记录' }}</strong>

        <div class="photo-strip" v-if="imageUrls(item).length">
          <a
            v-for="url in imageUrls(item).slice(0, 3)"
            :key="url"
            :href="url"
            target="_blank"
            rel="noreferrer"
          >
            <img :src="url" loading="lazy" decoding="async" @error="markFailed(url)" />
          </a>
        </div>
        <div v-else class="empty-photo">暂无有效现场照片</div>

        <dl class="info-list">
          <div v-if="contactText(item)">
            <dt>联系人</dt>
            <dd>{{ contactText(item) }}</dd>
          </div>
          <div>
            <dt>记录时间</dt>
            <dd>{{ item.photo_on || item.created_on || '-' }}</dd>
          </div>
          <div>
            <dt>状态说明</dt>
            <dd>{{ item.status_text || '未填写' }}</dd>
          </div>
          <div v-if="item.crack_width">
            <dt>裂缝宽度</dt>
            <dd>{{ item.crack_width }} mm</dd>
          </div>
        </dl>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { buildBackendUrl, buildPhotoCacheUrl, fetchQmqfAbnormalDashboard } from '../api/query'
import ReportBarChart from './ReportBarChart.vue'
import { buildOfficialPrintHtml } from '../utils/officialPrintTemplate'

type DashboardItem = {
  gqpbh: string
  gqpmc: string
  ssqx: string
  abnormal_types: string[]
  severity: string
  priority_reason: string
  photo_on: string
  created_on: string
  status_text: string
  has_crack_marker: boolean
  crack_width?: string
  evidence?: string
  photos: string[]
  contact_name?: string
  contact_phone?: string
  advice: string
}

const loading = ref(false)
const error = ref('')
const data = ref<any>(null)
const failedUrls = ref(new Set<string>())

const items = computed<DashboardItem[]>(() => data.value?.items || [])

const abnormalText = computed(() => {
  const types = new Set<string>()
  items.value.forEach((item) => (item.abnormal_types || []).forEach((type) => types.add(type)))
  return Array.from(types).slice(0, 5).join('、') || '现场异常'
})

const abnormalChartItems = computed(() => {
  const counts = new Map<string, number>()
  items.value.forEach((item) => {
    ;(item.abnormal_types || []).forEach((type) => {
      counts.set(type, (counts.get(type) || 0) + 1)
    })
  })
  return Array.from(counts.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await fetchQmqfAbnormalDashboard()
    data.value = result
    if (result?.status === 'error') {
      error.value = result.error || '异常监测记录读取失败'
    }
  } catch (err: any) {
    error.value = err?.message || '异常监测记录读取失败'
  } finally {
    loading.value = false
  }
}

function imageUrls(item: DashboardItem) {
  return (item.photos || [])
    .map(buildImageUrl)
    .filter((url) => url && !failedUrls.value.has(url))
}

function contactText(item: DashboardItem) {
  const name = String(item.contact_name || '').trim()
  const phone = String(item.contact_phone || '').trim()
  if (name && phone) return `${name} ${phone}`
  return name || phone
}

function buildImageUrl(value?: string) {
  const raw = String(value || '').trim()
  if (!raw || raw.toLowerCase() === 'null' || raw.toLowerCase() === 'none') {
    return ''
  }
  if (/^https?:\/\//i.test(raw)) {
    return raw.includes('1.13.19.44') ? buildPhotoCacheUrl(raw, 'thumb') : raw
  }
  if (raw.startsWith('/report-assets/')) {
    return buildBackendUrl(raw)
  }
  const normalized = raw.replace(/\\/g, '/').replace(/^\/+/, '')
  if (/^u\/mon\//i.test(normalized)) {
    return buildPhotoCacheUrl(`/${normalized.replace(/^u\/mon\//i, 'u/mon/')}`, 'thumb')
  }
  const filename = normalized.split('/').pop() || normalized
  const month = filename.match(/_(20\d{4})\d{8}_/)?.[1] || normalized.match(/(?:^|\/)(20\d{4})(?:\/|$)/)?.[1] || ''
  const remotePath = month ? `/u/mon/${month}/${filename}` : `/u/mon/${normalized}`
  return buildPhotoCacheUrl(remotePath, 'thumb')
}

function markFailed(url: string) {
  const next = new Set(failedUrls.value)
  next.add(url)
  failedUrls.value = next
}

function slopeTitle(item: DashboardItem) {
  const county = item.ssqx || '所属区县待核实'
  const name = item.gqpmc || '高切坡名称待核实'
  return item.gqpbh ? `${county} · ${name}（${item.gqpbh}）` : `${county} · ${name}`
}

function downloadPdf() {
  const win = window.open('', '_blank')
  if (!win) {
    return
  }
  win.document.open()
  win.document.write(buildPrintHtml())
  win.document.close()
  win.focus()
  window.setTimeout(() => {
    win.print()
  }, 700)
}

function buildPrintHtml() {
  const rows = items.value.slice(0, 8).map((item) => ({
    title: slopeTitle(item),
    tag: item.abnormal_types?.length ? item.abnormal_types.join('、') : '存在异常记录',
    time: item.photo_on || item.created_on || '-',
    status: item.status_text || '未填写',
    crackWidth: item.crack_width || '',
    contact: contactText(item),
    photos: imageUrls(item).slice(0, 4).map((url, index) => ({ url, label: `现场照片 ${index + 1}` })),
  }))
  return buildOfficialPrintHtml({
    title: '近期群测群防监测情况简报',
    meta: '湖北省高切坡群测群防监测',
    summaryParagraphs: [
      `近期系统汇总显示，共有 ${items.value.length} 处高切坡存在群测群防异常记录，异常对象主要涉及${countyText.value}。本简报重点展示异常类型、记录时间、状态说明和现场照片。`,
    ],
    stats: [
      { label: '异常记录对象', value: `${items.value.length}处` },
      { label: '涉及区县', value: countyText.value },
    ],
    objectsTitle: '二、异常对象与现场照片',
    objects: rows.map((item) => ({
      title: item.title,
      tag: item.tag,
      desc: `记录时间：${item.time}；状态说明：${item.status}${item.crackWidth ? `；裂缝宽度：${item.crackWidth} mm` : ''}${item.contact ? `；联系人：${item.contact}` : ''}`,
      photos: item.photos,
    })),
    conclusionTitle: '三、监测结论',
    conclusionParagraphs: [
      '本次异常记录以现场巡查发现和照片留痕为主，整体属于可复核、可跟踪范围。后续宜对重复出现异常、照片反映较明显破坏迹象或状态持续变化的对象保持跟踪。',
    ],
  })
}

const countyText = computed(() => {
  const counties = Array.from(new Set(items.value.map((item) => item.ssqx).filter(Boolean)))
  return counties.length ? counties.slice(0, 4).join('、') : '未标注区县'
})

onMounted(() => {
  void load()
})
</script>

<style scoped>
.qmqf-dashboard {
  display: grid;
  gap: 14px;
}

.dashboard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.dashboard-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.dashboard-head h3 {
  margin: 0;
  color: #172033;
  font-size: 19px;
}

.dashboard-head p {
  margin: 5px 0 0;
  color: #667085;
  font-size: 13px;
}

.dashboard-loading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #667085;
  font-size: 14px;
  padding: 18px;
}

.conclusion-panel {
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
}

.conclusion-panel h4 {
  margin: 0;
  color: #172033;
  font-size: 17px;
}

.conclusion-panel p {
  margin: 8px 0 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.75;
}

.abnormal-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.abnormal-card {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
}

.card-top strong {
  display: block;
  color: #172033;
  font-size: 15px;
  line-height: 1.45;
}

.card-top span {
  display: block;
  margin-top: 3px;
  color: #667085;
  font-size: 12px;
}

.abnormal-text {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  border-radius: 6px;
  background: #fff1f0;
  color: #b42318;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.45;
  padding: 5px 9px;
}

.photo-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.photo-strip a {
  display: block;
  position: relative;
  overflow: hidden;
  border: 1px solid #d9e3f5;
  border-radius: 8px;
  background: #f8fafc;
}

.photo-strip img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
}

.empty-photo {
  border: 1px dashed #d0d5dd;
  border-radius: 8px;
  color: #667085;
  font-size: 13px;
  padding: 14px;
}

.info-list {
  display: grid;
  gap: 8px;
  margin: 0;
}

.info-list div {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  gap: 8px;
}

.info-list dt {
  color: #667085;
  font-size: 12px;
}

.info-list dd {
  margin: 0;
  color: #344054;
  font-size: 13px;
  line-height: 1.5;
}

.advice {
  margin: 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.65;
}

@media (max-width: 980px) {
  .abnormal-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-head {
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .dashboard-head h3 {
    font-size: 18px;
  }

  .dashboard-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .dashboard-actions :deep(.el-button) {
    margin-left: 0;
  }

  .conclusion-panel,
  .abnormal-card {
    padding: 12px;
  }

  .photo-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .info-list div {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .abnormal-text {
    font-size: 15px;
  }
}
</style>
