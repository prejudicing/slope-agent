<template>
  <section class="displacement-dashboard">
    <div class="dashboard-head">
      <div>
        <h3>{{ data?.title || '近期专业监测情况' }}</h3>
        <p>按专业监测成果筛选近期位移变化相对较大的高切坡，展示监测点、年度变化量、稳定性评价和趋势分析。</p>
      </div>
      <div class="dashboard-actions">
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        <el-button size="small" type="primary" :disabled="loading || !items.length" @click="downloadPdf">下载PDF</el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="warning"
      show-icon
      :closable="false"
    />

    <div v-if="loading && !items.length" class="dashboard-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在汇总近期位移变化较大的专业监测点</span>
    </div>

    <section v-if="!loading || items.length" class="conclusion-panel">
      <h4>监测结论</h4>
      <div class="conclusion-summary">
        <div>
          <span>专业监测高切坡</span>
          <strong>{{ professionalSlopeCount }} 处</strong>
        </div>
        <div>
          <span>本次重点展示</span>
          <strong>{{ items.length }} 处</strong>
        </div>
        <div>
          <span>总体判断</span>
          <strong>{{ stabilityText }}</strong>
        </div>
      </div>
      <p>近期专业监测结果总体未显示普遍性失稳迹象，部分坡体存在连续小幅位移变化，整体属于可跟踪、可复核范围。</p>
      <p>后续宜关注同一坡体多监测点变化是否具有一致性，并结合现场照片和既有报告材料持续核验；如同步增大或连续加速，再提高关注等级。</p>
    </section>

    <div v-if="items.length" class="slope-grid">
      <article v-for="item in items" :key="item.gqpbh" class="slope-card">
        <div class="card-top">
          <div>
            <strong>{{ slopeTitle(item) }}</strong>
            <small v-if="item.latest_monitor_date" class="date-line">监测数据更新至：{{ item.latest_monitor_date }}</small>
          </div>
        </div>

        <strong class="abnormal-text">
          监测点（{{ item.stability?.top_point || '-' }}）年度位移变化量 {{ formatNumber(item.max_recent_change) }} mm
        </strong>
        <p class="monitor-desc">
          月度平均变化速率 {{ formatNumber(item.avg_monthly_rate || item.stability?.avg_monthly_rate) }} mm/月
          <span>{{ item.stability?.level || '待评价' }}</span>
          <span>监测点 {{ item.point_count }} 个</span>
        </p>
        <p class="contact-line">联系人：{{ contactText(item) || '待补充' }}</p>

        <div class="point-list">
          <div v-for="point in item.points.slice(0, 4)" :key="point.jcdbh" class="point-row">
            <span>{{ point.jcdbh }}</span>
            <i>X {{ formatNumber(point.x_change) }}</i>
            <i>Y {{ formatNumber(point.y_change) }}</i>
            <i>H {{ formatNumber(point.h_change) }}</i>
            <i>月均 {{ formatNumber(point.avg_monthly_rate) }}</i>
          </div>
        </div>

        <p class="summary">{{ item.stability?.summary }}</p>

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
        <div v-else class="empty-photo">暂无匹配现场照片</div>

        <div class="card-actions">
          <button type="button" @click="toggleChart(item)">
            查看位移变化图
          </button>
          <button type="button" @click="toggleAnalysis(item)">
            {{ activeAnalysisKey === item.gqpbh ? '收起分析' : '展开分析' }}
          </button>
        </div>

        <div v-if="activeAnalysisKey === item.gqpbh" class="analysis-panel">
          <div>
            <b>稳定性评价</b>
            <p>{{ item.stability?.level || '待评价' }}。{{ item.stability?.summary }}</p>
            <p v-if="item.stability?.report_evaluation">{{ item.stability.report_evaluation }}</p>
          </div>
          <div>
            <b>趋势预测</b>
            <p>{{ item.stability?.prediction }}</p>
          </div>
          <div>
            <b>处置建议</b>
            <p>{{ item.stability?.advice || '建议结合现场巡查和后续监测数据复核。' }}</p>
          </div>
        </div>
      </article>
    </div>
  </section>

  <Teleport to="body">
    <div v-if="chartDialogItem" class="chart-dialog" @click.self="closeChartDialog">
      <section class="chart-dialog-panel">
        <header>
          <div>
            <h3>{{ chartDialogItem.gqpmc }}</h3>
            <p>{{ chartDialogItem.gqpbh }} · {{ chartDialogItem.ssqx || '未标注区县' }} · 主控监测点 {{ chartDialogItem.stability?.top_point || '-' }}</p>
          </div>
          <button type="button" aria-label="关闭位移变化图" @click="closeChartDialog">×</button>
        </header>

        <div class="chart-dialog-body">
          <ReportLineChart
            v-if="chartDataMap[chartDialogItem.gqpbh]?.series?.length"
            :title="chartTitle(chartDialogItem)"
            :subtitle="chartSubtitle(chartDialogItem)"
            :rows="chartDataMap[chartDialogItem.gqpbh].series"
          />
          <div v-else-if="chartSvgMap[chartDialogItem.gqpbh]" class="chart-dialog-svg" v-html="chartSvgMap[chartDialogItem.gqpbh]"></div>
          <p v-else>{{ chartLoadingMap[chartDialogItem.gqpbh] ? '正在加载位移变化图...' : '该监测点暂未生成位移变化图。' }}</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { buildBackendUrl, buildPhotoCacheUrl, fetchRecentLargeDisplacement } from '../api/query'
import ReportLineChart from './ReportLineChart.vue'
import { buildOfficialPrintHtml } from '../utils/officialPrintTemplate'

type MonitorPoint = {
  jcdbh: string
  x_change: number
  y_change: number
  h_change: number
  max_recent_change: number
  avg_monthly_rate?: number
}

type ReportBasis = {
  county: string
  year: number
  month: number
  report_type: string
  file_name: string
  key_points: string
  mentioned_slopes: string
  excerpt: string
  rule: string
}

type DashboardItem = {
  gqpbh: string
  gqpmc: string
  ssqx: string
  point_count: number
  latest_monitor_date?: string
  freshness_note?: string
  max_recent_change: number
  avg_monthly_rate?: number
  analysis_period?: string
  chart_url: string
  data_url?: string
  chart_svg?: string
  photos?: string[]
  photo_note?: string
  contact_name?: string
  contact_phone?: string
  report_basis?: ReportBasis
  points: MonitorPoint[]
  stability?: {
    level: string
    top_point: string
    summary: string
    prediction: string
    advice: string
    report_evaluation?: string
    avg_monthly_rate?: number
    analysis_period?: string
    alert_threshold?: number
  }
}

const loading = ref(false)
const error = ref('')
const data = ref<any>(null)
const activeAnalysisKey = ref('')
const chartDialogItem = ref<DashboardItem | null>(null)
const chartSvgMap = ref<Record<string, string>>({})
const chartDataMap = ref<Record<string, { series: Array<{ date: string; x: number; y: number; h: number }> }>>({})
const chartLoadingMap = ref<Record<string, boolean>>({})
const failedUrls = ref(new Set<string>())

const items = computed<DashboardItem[]>(() => data.value?.items || [])
const professionalSlopeCount = computed(() => Number(data.value?.professional_slope_count || 0))
const stabilityText = computed(() => {
  const levels = new Set<string>()
  items.value.forEach((item) => {
    if (item.stability?.level) {
      levels.add(item.stability.level)
    }
  })
  return Array.from(levels).join('、') || '正常跟踪'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await fetchRecentLargeDisplacement()
    data.value = result
    if (result?.status === 'error') {
      error.value = result.error || '近期位移变化数据读取失败'
    }
  } catch (err: any) {
    error.value = err?.message || '近期位移变化数据读取失败'
  } finally {
    loading.value = false
  }
}

function buildAssetUrl(url?: string) {
  if (!url) {
    return ''
  }
  if (/^https?:\/\//i.test(url)) {
    return url
  }
  return buildBackendUrl(url)
}

function chartUrl(item: DashboardItem) {
  const stableUrl = item.chart_url?.replace(/\.html(\?.*)?$/i, '.svg$1')
  const url = buildAssetUrl(stableUrl)
  if (!url) {
    return ''
  }
  return `${url}${url.includes('?') ? '&' : '?'}_t=${Date.now()}`
}

function chartDataUrl(item: DashboardItem) {
  if (!item.data_url) {
    return ''
  }
  const url = buildAssetUrl(item.data_url)
  return `${url}${url.includes('?') ? '&' : '?'}_t=${Date.now()}`
}

function chartTitle(item: DashboardItem) {
  const point = item.stability?.top_point || '-'
  return `${item.gqpmc || item.gqpbh} - ${point} 位移变化图`
}

function chartSubtitle(item: DashboardItem) {
  return `${item.gqpbh || '编号待核'} · ${item.ssqx || '区县待核'} · X/Y/H 三向位移变化量，单位：mm`
}

function formatNumber(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '-'
  }
  return Number(value).toFixed(1)
}

function slopeTitle(item: DashboardItem) {
  const county = item.ssqx || '所属区县待核实'
  const name = item.gqpmc || '高切坡名称待核实'
  return item.gqpbh ? `${county} · ${name}（${item.gqpbh}）` : `${county} · ${name}`
}

function imageUrls(item: DashboardItem) {
  return (item.photos || [])
    .map(buildImageUrl)
    .filter((url) => url && !failedUrls.value.has(url))
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

function toggleAnalysis(item: DashboardItem) {
  activeAnalysisKey.value = activeAnalysisKey.value === item.gqpbh ? '' : item.gqpbh
}

async function toggleChart(item: DashboardItem) {
  chartDialogItem.value = item
  if (chartDataMap.value[item.gqpbh] || chartSvgMap.value[item.gqpbh]) {
    return
  }
  const dataUrl = chartDataUrl(item)
  if (!dataUrl) {
    if (item.chart_svg?.includes('<svg')) {
      chartSvgMap.value = { ...chartSvgMap.value, [item.gqpbh]: item.chart_svg }
    }
    return
  }
  chartLoadingMap.value = { ...chartLoadingMap.value, [item.gqpbh]: true }
  try {
    const response = await fetch(dataUrl, { cache: 'no-store' })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const payload = await response.json()
    if (!Array.isArray(payload?.series) || !payload.series.length) {
      throw new Error('未读取到位移序列')
    }
    chartDataMap.value = { ...chartDataMap.value, [item.gqpbh]: { series: payload.series } }
  } catch (err: any) {
    if (item.chart_svg?.includes('<svg')) {
      chartSvgMap.value = { ...chartSvgMap.value, [item.gqpbh]: item.chart_svg }
    } else {
      const fallbackUrl = chartUrl(item)
      if (fallbackUrl) {
        try {
          const response = await fetch(fallbackUrl, { cache: 'no-store' })
          const svg = await response.text()
          if (svg.includes('<svg')) {
            chartSvgMap.value = { ...chartSvgMap.value, [item.gqpbh]: svg }
          }
        } catch {
          error.value = `位移变化图加载失败：${err?.message || '请刷新后重试'}`
        }
      } else {
        error.value = `位移变化图加载失败：${err?.message || '请刷新后重试'}`
      }
    }
  } finally {
    chartLoadingMap.value = { ...chartLoadingMap.value, [item.gqpbh]: false }
  }
}

function closeChartDialog() {
  chartDialogItem.value = null
}

function contactText(item: DashboardItem) {
  const name = String(item.contact_name || '').trim()
  const phone = String(item.contact_phone || '').trim()
  if (name && phone) return `${name} ${phone}`
  return name || phone
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
    label: `监测点（${item.stability?.top_point || '-'}）年度位移变化量 ${formatNumber(item.max_recent_change)} mm`,
    desc: `月度平均变化速率 ${formatNumber(item.avg_monthly_rate || item.stability?.avg_monthly_rate)} mm/月；${item.stability?.level || '待评价'}；监测点 ${item.point_count} 个`,
    summary: item.stability?.summary || '',
    contact: contactText(item),
    photos: imageUrls(item).slice(0, 4).map((url, index) => ({ url, label: `现场照片 ${index + 1}` })),
  }))
  return buildOfficialPrintHtml({
    title: '近期专业监测情况简报',
    meta: '湖北省高切坡专业监测',
    summaryParagraphs: [
      `本次共识别专业监测高切坡 ${professionalSlopeCount.value} 处。绝大多数专业监测对象处于正常或缓慢变形状态，未见需要整体提升风险等级的普遍性异常。`,
    ],
    stats: [
      { label: '专业监测高切坡', value: `${professionalSlopeCount.value}处` },
      { label: '重点展示对象', value: `${items.value.length}处` },
    ],
    objectsTitle: '二、重点对象与现场照片',
    objects: rows.map((item) => ({
      title: item.title,
      tag: item.label,
      desc: `${item.desc}${item.contact ? `；联系人：${item.contact}` : ''}`,
      body: item.summary,
      photos: item.photos,
    })),
    conclusionTitle: '三、监测结论',
    conclusionParagraphs: [
      '综合专业监测数据、年度位移变化量和现场照片情况，近期专业监测高切坡总体处于可跟踪、可复核范围。后续宜重点关注同一坡体多监测点变化是否具有一致性。',
    ],
  })
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.displacement-dashboard {
  display: grid;
  gap: 14px;
  max-width: 1180px;
  margin: 0 auto 24px;
}

.dashboard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-top: 4px;
}

.dashboard-head h3 {
  margin: 0;
  color: #172033;
  font-size: 21px;
  line-height: 1.35;
}

.dashboard-head p {
  max-width: 760px;
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
}

.dashboard-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
  padding-top: 2px;
}

.conclusion-panel {
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  background: #fff;
  padding: 14px 16px;
}

.conclusion-panel h4 {
  margin: 0 0 8px;
  color: #172033;
  font-size: 16px;
}

.conclusion-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.conclusion-summary div {
  border: 1px solid #e4e9f2;
  border-radius: 6px;
  background: #f8fafc;
  padding: 10px 12px;
}

.conclusion-summary span {
  display: block;
  color: #667085;
  font-size: 12px;
  line-height: 1.4;
}

.conclusion-summary strong {
  display: block;
  margin-top: 4px;
  color: #172033;
  font-size: 18px;
  line-height: 1.35;
}

.conclusion-panel p {
  margin: 0;
  color: #475467;
  font-size: 14px;
  line-height: 1.75;
}

.conclusion-panel p + p {
  margin-top: 6px;
}

.dashboard-loading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #667085;
  font-size: 14px;
  padding: 18px;
}

.slope-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.slope-card {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
  text-align: left;
}

.card-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
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

.date-line {
  display: block;
  margin-top: 6px;
  color: #667085;
  font-size: 12px;
  line-height: 1.45;
}

.card-top em {
  flex: 0 0 auto;
  align-self: flex-start;
  border-radius: 999px;
  font-size: 12px;
  font-style: normal;
  padding: 5px 9px;
}

.level-danger {
  background: #fff1f0;
  color: #b42318;
}

.level-warning {
  background: #fff7e6;
  color: #b54708;
}

.level-normal {
  background: #ecfdf3;
  color: #027a48;
}

.abnormal-text {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  border-radius: 6px;
  background: #fff7e6;
  color: #b54708;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.45;
  padding: 6px 10px;
}

.monitor-desc {
  margin: 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.65;
}

.monitor-desc span {
  display: inline-flex;
  align-items: center;
  margin-left: 8px;
  padding-left: 8px;
  border-left: 1px solid #d8dee9;
}

.contact-line {
  margin: 0;
  color: #344054;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.6;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.metric-row div {
  border-radius: 8px;
  background: #f7f9fc;
  padding: 9px;
}

.metric-row span {
  display: block;
  color: #667085;
  font-size: 12px;
}

.metric-row b {
  display: block;
  margin-top: 4px;
  color: #172033;
  font-size: 15px;
}

.point-list {
  display: grid;
  gap: 6px;
}

.point-row {
  display: grid;
  grid-template-columns: 1fr repeat(4, 68px);
  gap: 6px;
  align-items: center;
  border-bottom: 1px solid #edf1f6;
  color: #475467;
  font-size: 12px;
  padding-bottom: 6px;
}

.point-row span {
  color: #172033;
  font-weight: 700;
}

.point-row i {
  font-style: normal;
  text-align: right;
}

.summary,
.prediction {
  margin: 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.65;
}

.prediction {
  color: #667085;
}

.freshness-note {
  margin: 0;
  border-left: 3px solid #f59e0b;
  background: #fffbeb;
  color: #92400e;
  font-size: 12px;
  line-height: 1.6;
  padding: 8px 10px;
}

.photo-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.photo-strip a {
  display: block;
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
  display: grid;
  min-height: 91px;
  place-items: center;
  border: 1px dashed #d0d5dd;
  border-radius: 8px;
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
  padding: 13px;
}

.card-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.card-actions a,
.card-actions button {
  border: 1px solid #cbd8ff;
  border-radius: 8px;
  background: #fff;
  color: #1b5cff;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  line-height: 1;
  padding: 9px 11px;
  text-decoration: none;
}

.card-actions button {
  color: #1b5cff;
}

.chart-panel,
.analysis-panel {
  display: grid;
  gap: 10px;
  border: 1px solid #dbe7ff;
  border-radius: 8px;
  background: #f7faff;
  padding: 12px;
}

.chart-panel {
  background: #fff;
  overflow: auto;
}

.chart-panel p {
  margin: 0;
  color: #667085;
  font-size: 13px;
}

.chart-svg {
  min-width: 720px;
}

.chart-svg :deep(svg) {
  display: block;
  width: 100%;
  height: auto;
}

.analysis-panel b {
  display: block;
  color: #172033;
  font-size: 13px;
  margin-bottom: 4px;
}

.analysis-panel p {
  margin: 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.7;
}

.chart-dialog {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(15, 23, 42, 0.58);
}

.chart-dialog-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: min(1320px, 94vw);
  height: min(860px, 90vh);
  overflow: hidden;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.32);
}

.chart-dialog-panel header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid #e5eaf3;
  background: #f8fafc;
}

.chart-dialog-panel h3 {
  margin: 0;
  color: #111827;
  font-size: 17px;
  line-height: 1.35;
}

.chart-dialog-panel p {
  margin: 5px 0 0;
  color: #667085;
  font-size: 12px;
}

.chart-dialog-panel header button {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid #d7deea;
  border-radius: 8px;
  background: #fff;
  color: #334155;
  cursor: pointer;
  font-size: 24px;
  line-height: 1;
}

.chart-dialog-body {
  min-height: 0;
  overflow: auto;
  padding: 12px;
  background: #f3f6fb;
}

.chart-dialog-svg {
  min-width: 980px;
  height: 100%;
  border: 1px solid #e5eaf3;
  border-radius: 8px;
  background: #fff;
}

.chart-dialog-svg :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 620px;
}

@media (max-width: 980px) {
  .dashboard-head {
    flex-direction: column;
  }

  .dashboard-actions {
    width: 100%;
  }

  .conclusion-summary {
    grid-template-columns: 1fr;
  }

  .slope-grid {
    grid-template-columns: 1fr;
  }

  .chart-dialog {
    padding: 12px;
  }

  .chart-dialog-panel {
    width: 96vw;
    height: 88vh;
  }

  .chart-dialog-svg {
    min-width: 760px;
  }
}

@media (max-width: 640px) {
  .displacement-dashboard {
    gap: 12px;
  }

  .dashboard-head h3 {
    font-size: 18px;
  }

  .dashboard-head p {
    font-size: 12px;
  }

  .dashboard-actions {
    width: 100%;
  }

  .dashboard-actions :deep(.el-button) {
    flex: 1;
  }

  .photo-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-row {
    grid-template-columns: 1fr;
  }

  .point-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
    gap: 4px 8px;
  }

  .point-row i {
    text-align: left;
  }

  .abnormal-text {
    font-size: 15px;
  }

  .monitor-desc span {
    display: block;
    margin-left: 0;
    padding-left: 0;
    border-left: 0;
  }

  .chart-dialog {
    padding: 0;
  }

  .chart-dialog-panel {
    width: 100vw;
    height: 100dvh;
    border-radius: 0;
  }

  .chart-dialog-panel header {
    padding: 12px;
  }

  .chart-dialog-panel h3 {
    font-size: 15px;
  }

  .chart-dialog-body {
    padding: 8px;
  }

  .chart-dialog-svg {
    min-width: 680px;
  }

  .chart-dialog-svg :deep(svg) {
    min-height: 440px;
  }
}
</style>
