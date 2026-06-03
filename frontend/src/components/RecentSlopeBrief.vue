<template>
  <section class="brief">
    <div class="brief-head">
      <div>
        <h3>生成高切坡近期情况业务简报</h3>
        <p>综合群测群防异常、专业监测位移变化和现场照片情况生成业务简报</p>
      </div>
      <div class="brief-actions">
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        <el-button size="small" type="primary" :disabled="loading" @click="downloadPdf">下载PDF</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" />

    <div class="brief-grid">
      <article>
        <span>群测群防异常</span>
        <strong>{{ qmqfItems.length }} 处</strong>
        <p>{{ countyText(qmqfItems) }}</p>
      </article>
      <article>
        <span>专业监测点（位移超限）</span>
        <strong>{{ professionalAlertItems.length }} 处</strong>
        <p>{{ professionalAlertItems[0]?.stability?.summary || '暂无专业监测位移超限对象' }}</p>
      </article>
      <article>
        <span>监测结论</span>
        <strong>525 处总体正常</strong>
        <p>局部对象需结合现场异常、位移变化和佐证照片持续跟踪</p>
      </article>
    </div>

    <ReportBarChart
      v-if="briefChartItems.length"
      title="近期高切坡业务关注事项统计"
      unit="处"
      :items="briefChartItems"
    />

    <div class="brief-section">
      <h4>一、总体情况</h4>
      <p>
        近期系统识别到 {{ qmqfItems.length }} 处群测群防异常高切坡，
        以及 {{ professionalAlertItems.length }} 处专业监测位移达到关注阈值的高切坡。
        群测群防异常主要涉及{{ abnormalTypeText }}；专业监测点（位移超限）以{{ displacementText }}为主。
      </p>
    </div>

    <div class="brief-section">
      <div class="section-title">
        <h4>二、重点对象与现场照片</h4>
        <span>点击照片查看大图</span>
      </div>
      <div class="focus-list">
        <div v-for="item in qmqfItems.slice(0, 4)" :key="`q-${item.gqpbh}`" class="focus-item">
          <b>{{ item.ssqx || '所属区县待核实' }} · {{ slopeTitle(item) }}</b>
          <strong class="abnormal-text">{{ item.abnormal_summary || '存在异常记录' }}</strong>
          <span v-if="contactText(item)" class="contact-line">联系人：{{ contactText(item) }}</span>
          <div v-if="photosForQmqf(item).length" class="inline-photo-grid">
            <figure
              v-for="photo in photosForQmqf(item).slice(0, 3)"
              :key="photo.url"
              class="brief-photo-card compact"
              role="button"
              tabindex="0"
              @click="openPhoto(photo)"
              @keydown.enter.prevent="openPhoto(photo)"
              @keydown.space.prevent="openPhoto(photo)"
            >
              <img
                :src="photo.url"
                :alt="photo.label"
                loading="lazy"
                decoding="async"
                @error="markPhotoFailed(photo.url)"
              />
              <figcaption>
                <strong>{{ photo.label }}</strong>
              </figcaption>
            </figure>
          </div>
        </div>
        <div v-for="item in professionalAlertItems.slice(0, 3)" :key="`d-${item.gqpbh}`" class="focus-item">
          <b>{{ item.ssqx || '所属区县待核实' }} · {{ slopeTitle(item) }}</b>
          <strong class="abnormal-text displacement">
            监测点（{{ item.stability?.top_point || '-' }}）年度位移变化量 {{ formatNumber(item.max_recent_change) }} mm
          </strong>
          <span>月度平均变化速率 {{ formatNumber(item.avg_monthly_rate || item.stability?.avg_monthly_rate) }} mm/月 · {{ item.stability?.level || '稳定性待研判' }}</span>
          <span v-if="contactText(item)" class="contact-line">联系人：{{ contactText(item) }}</span>
          <div v-if="photosForProfessional(item).length" class="inline-photo-grid">
            <figure
              v-for="photo in photosForProfessional(item).slice(0, 3)"
              :key="photo.url"
              class="brief-photo-card compact"
              role="button"
              tabindex="0"
              @click="openPhoto(photo)"
              @keydown.enter.prevent="openPhoto(photo)"
              @keydown.space.prevent="openPhoto(photo)"
            >
              <img
                :src="photo.url"
                :alt="photo.label"
                loading="lazy"
                decoding="async"
                @error="markPhotoFailed(photo.url)"
              />
              <figcaption>
                <strong>{{ photo.label }}</strong>
              </figcaption>
            </figure>
          </div>
        </div>
        <div v-for="item in stabilityItems.slice(0, 4)" :key="`s-${item.gqpbh}-${item.report_month}`" class="focus-item report-item">
          <b>{{ item.county || '所属区县待核实' }} · {{ reportSlopeTitle(item) }}</b>
          <strong class="abnormal-text report">
            {{ item.stability_level || '月报评价待核实' }}
            <span v-if="item.abnormal_keywords"> · {{ item.abnormal_keywords }}</span>
          </strong>
          <span>{{ displayStabilityText(item) }}</span>
          <div v-if="photosForReport(item).length" class="inline-photo-grid">
            <figure
              v-for="photo in photosForReport(item).slice(0, 3)"
              :key="photo.url"
              class="brief-photo-card compact"
              role="button"
              tabindex="0"
              @click="openPhoto(photo)"
              @keydown.enter.prevent="openPhoto(photo)"
              @keydown.space.prevent="openPhoto(photo)"
            >
              <img
                :src="photo.url"
                :alt="photo.label"
                loading="lazy"
                decoding="async"
                @error="markPhotoFailed(photo.url)"
              />
              <figcaption>
                <strong>{{ photo.label }}</strong>
              </figcaption>
            </figure>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="photoPreviewVisible"
      :title="selectedPhoto?.slopeName || selectedPhoto?.slopeCode || '现场照片'"
      width="min(92vw, 1180px)"
      class="brief-photo-dialog"
      append-to-body
      destroy-on-close
    >
      <div v-if="selectedPhoto" class="brief-photo-preview">
        <img
          :src="selectedPhoto.url"
          :alt="selectedPhoto.label"
          @error="markPhotoFailed(selectedPhoto.url)"
        />
        <div class="brief-photo-preview-meta">
          <strong>{{ selectedPhoto.slopeName || selectedPhoto.slopeCode || '高切坡现场' }}</strong>
          <span>{{ selectedPhoto.county || '所属区县待核实' }} · {{ selectedPhoto.abnormalType || '现场照片' }}</span>
        </div>
      </div>
    </el-dialog>

    <div class="brief-section">
      <h4>三、监测结论</h4>
      <p>湖北省纳入监测的 525 处高切坡中，绝大多数处于正常状态，未见需要整体提升风险等级的普遍性异常。</p>
      <div class="conclusion-list">
        <p>群测群防方面，本次重点关注 {{ qmqfItems.length }} 处存在现场异常记录的高切坡，异常类型主要为{{ abnormalTypeText }}，需结合照片和后续巡查复核异常是否持续发展。</p>
        <p>专业监测方面，当前筛选出 {{ professionalAlertItems.length }} 处年度位移变化量相对较大的高切坡，监测结论以{{ stabilityText }}为主，整体属于可跟踪、可复核范围。</p>
        <p>综合判断，近期高切坡运行状态总体平稳，后续宜对现场照片异常对象和专业监测缓慢变形对象保持跟踪，月报中的稳定性评价和现场照片作为对象研判佐证材料使用，重点核对同一坡体多监测点变化是否具有一致性。</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { buildBackendUrl, buildPhotoCacheUrl, fetchQmqfAbnormalDashboard, fetchRecentLargeDisplacement, fetchReportStabilityAssets } from '../api/query'
import ReportBarChart from './ReportBarChart.vue'
import { buildOfficialPrintHtml } from '../utils/officialPrintTemplate'

const MIN_PHOTO_MONTH = 202506

const loading = ref(false)
const error = ref('')
const qmqfData = ref<any>(null)
const displacementData = ref<any>(null)
const stabilityData = ref<any>(null)
const failedPhotoUrls = ref(new Set<string>())
const photoPreviewVisible = ref(false)
const selectedPhoto = ref<BriefPhotoItem | null>(null)

type BriefPhotoItem = {
  url: string
  label: string
  slopeCode: string
  slopeName: string
  county: string
  abnormalType: string
}

const qmqfItems = computed(() => qmqfData.value?.items || [])
const displacementItems = computed(() => displacementData.value?.items || [])
const stabilityItems = computed(() => dedupeStabilityItems(stabilityData.value?.items || []))
const professionalAlertItems = computed(() =>
  displacementItems.value.filter((item: any) => isProfessionalAlert(item)),
)
const briefChartItems = computed(() => [
  { name: '群测群防异常', value: qmqfItems.value.length },
  { name: '专业监测关注', value: professionalAlertItems.value.length },
  { name: '需持续跟踪', value: qmqfItems.value.length + professionalAlertItems.value.length },
])

function dedupeStabilityItems(items: any[]) {
  const seen = new Set<string>()
  const result: any[] = []
  items.forEach((item) => {
    const textKey = String(item?.stability_text || '')
      .replace(/\s+/g, '')
      .replace(/[；;。,.，]/g, '')
      .slice(0, 180)
    const pageKey = [
      item?.county || '',
      item?.report_year || '',
      item?.report_month || '',
      item?.page_no || '',
      textKey,
    ].join('|')
    const key = textKey || pageKey
    if (seen.has(key)) {
      return
    }
    seen.add(key)
    result.push(item)
  })
  return result
}

function photosForQmqf(item: any): BriefPhotoItem[] {
  return photosForItem(item, true)
}

function photosForProfessional(item: any): BriefPhotoItem[] {
  return photosForItem(item, false)
}

function photosForReport(item: any): BriefPhotoItem[] {
  const thumbnails = item.thumbnail_urls || []
  const previews = item.photo_urls || []
  return thumbnails
    .map((thumb: string, index: number) => {
      const url = buildPhotoUrl(previews[index] || thumb)
      if (!url || failedPhotoUrls.value.has(url)) {
        return null
      }
      return {
        url,
        label: `月报现场照片 ${index + 1}`,
        slopeCode: item.gqpbh || '',
        slopeName: item.gqpmc || '',
        county: item.county || '',
        abnormalType: item.abnormal_keywords || item.stability_level || '月报现场照片',
      }
    })
    .filter(Boolean) as BriefPhotoItem[]
}

function photosForItem(item: any, requireRecent: boolean): BriefPhotoItem[] {
  return (item.photos || [])
    .map((photo: string, index: number) => {
      const url = buildPhotoUrl(photo)
      if (!url || failedPhotoUrls.value.has(url) || (requireRecent && !isAllowedPhotoDate(url))) {
        return null
      }
      return {
        url,
        label: `现场照片 ${index + 1}`,
        slopeCode: item.gqpbh || '',
        slopeName: item.gqpmc || '',
        county: item.ssqx || '',
        abnormalType: item.abnormal_summary || (item.abnormal_types || []).join('、'),
      }
    })
    .filter(Boolean) as BriefPhotoItem[]
}

const abnormalTypeText = computed(() => {
  const types = new Set<string>()
  qmqfItems.value.forEach((item: any) => (item.abnormal_types || []).forEach((type: string) => types.add(type)))
  return Array.from(types).slice(0, 5).join('、') || '现场异常'
})

const displacementText = computed(() => {
  const first = professionalAlertItems.value[0]
  if (!first) return '位移变化监测'
  return `${first.gqpmc}等对象`
})

const stabilityText = computed(() => {
  const levels = new Set<string>()
  professionalAlertItems.value.forEach((item: any) => {
    const level = item.stability?.level
    if (level) {
      levels.add(level)
    }
  })
  return Array.from(levels).join('、') || '正常跟踪'
})

function isProfessionalAlert(item: any) {
  const maxChange = Math.abs(Number(item.max_recent_change || 0))
  return maxChange >= 4.5
}

function slopeTitle(item: any) {
  const name = item.gqpmc || '高切坡名称待核实'
  return item.gqpbh ? `${name}（${item.gqpbh}）` : name
}

function reportSlopeTitle(item: any) {
  const name = item.gqpmc || '高切坡名称待核实'
  return item.gqpbh ? `${name}（${item.gqpbh}）` : name
}

function displayStabilityText(item: any) {
  return normalizeReportText(item?.stability_text || '')
}

function normalizeReportText(value: string) {
  const raw = String(value || '').replace(/\s+/g, '')
  if (!raw) {
    return ''
  }
  const parts = raw
    .split(/(?<=[。；;])/)
    .map((part) => part.trim())
    .filter(Boolean)
  const seen = new Set<string>()
  const result: string[] = []
  parts.forEach((part) => {
    const key = part.replace(/[。；;，,、]/g, '').slice(0, 80)
    if (!key || seen.has(key)) {
      return
    }
    seen.add(key)
    result.push(part)
  })
  return result.join('').slice(0, 260)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [qmqf, displacement, stability] = await Promise.all([
      fetchQmqfAbnormalDashboard(),
      fetchRecentLargeDisplacement(),
      fetchReportStabilityAssets({ limit: 12, only_with_photos: true }),
    ])
    qmqfData.value = qmqf
    displacementData.value = displacement
    stabilityData.value = stability
    failedPhotoUrls.value = new Set<string>()
  } catch (err: any) {
    error.value = err?.message || '近期高切坡情况简介生成失败'
  } finally {
    loading.value = false
  }
}

function countyText(items: any[]) {
  const counties = Array.from(new Set(items.map((item) => item.ssqx).filter(Boolean)))
  return counties.length ? `涉及${counties.slice(0, 4).join('、')}` : '暂无区县信息'
}

function formatNumber(value?: number) {
  return value === undefined || value === null ? '-' : Number(value).toFixed(1)
}

function buildPhotoUrl(value?: string) {
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

function isAllowedPhotoDate(url: string) {
  const month = url.match(/\/(20\d{4})\//)?.[1] || url.match(/_(20\d{4})\d{8}_/)?.[1]
  return month ? Number(month) >= MIN_PHOTO_MONTH : false
}

function markPhotoFailed(url: string) {
  const next = new Set(failedPhotoUrls.value)
  next.add(url)
  failedPhotoUrls.value = next
  if (selectedPhoto.value?.url === url) {
    photoPreviewVisible.value = false
    selectedPhoto.value = null
  }
}

function openPhoto(item: BriefPhotoItem) {
  selectedPhoto.value = item
  photoPreviewVisible.value = true
}

function contactText(item: any) {
  const name = String(item?.contact_name || '').trim()
  const phone = String(item?.contact_phone || '').trim()
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
  const qmqf = qmqfItems.value.slice(0, 4)
  const professional = professionalAlertItems.value.slice(0, 4)
  const stability = stabilityItems.value.slice(0, 6)
  const objectRows = [
    ...qmqf.map((item: any) => ({
      title: `${item.ssqx || '所属区县待核实'} · ${slopeTitle(item)}`,
      label: item.abnormal_summary || '存在异常记录',
      desc: `群测群防异常：${item.severity || '需复核'}${contactText(item) ? `；联系人：${contactText(item)}` : ''}`,
      photos: photosForQmqf(item).slice(0, 3),
    })),
    ...professional.map((item: any) => ({
      title: `${item.ssqx || '所属区县待核实'} · ${slopeTitle(item)}`,
      label: `监测点（${item.stability?.top_point || '-'}）年度位移变化量 ${formatNumber(item.max_recent_change)} mm`,
      desc: `月度平均变化速率 ${formatNumber(item.avg_monthly_rate || item.stability?.avg_monthly_rate)} mm/月，${item.stability?.level || '稳定性待研判'}${contactText(item) ? `；联系人：${contactText(item)}` : ''}`,
      photos: photosForProfessional(item).slice(0, 3),
    })),
    ...stability.map((item: any) => ({
      title: `${item.county || '所属区县待核实'} · ${reportSlopeTitle(item)}`,
      label: `${item.stability_level || '月报评价'}${item.abnormal_keywords ? ` · ${item.abnormal_keywords}` : ''}`,
      desc: `月报评价：${displayStabilityText(item) || '暂无评价文字'}`,
      photos: photosForReport(item).slice(0, 3),
    })),
  ]

  return buildOfficialPrintHtml({
    title: '高切坡近期情况业务简报',
    meta: '湖北省高切坡智能监测业务简报',
    summaryParagraphs: [
      `湖北省纳入监测的 525 处高切坡中，绝大多数处于正常状态。近期系统识别到 ${qmqfItems.value.length} 处群测群防异常高切坡、${professionalAlertItems.value.length} 处专业监测位移变化相对较大的高切坡，局部对象需结合现场照片和既有报告材料持续跟踪。`,
      `群测群防异常主要涉及${abnormalTypeText.value}；专业监测结论以${stabilityText.value}为主，整体未见需要普遍提升风险等级的趋势。`,
    ],
    stats: [
      { label: '群测群防异常', value: `${qmqfItems.value.length}处` },
      { label: '专业监测关注', value: `${professionalAlertItems.value.length}处` },
      { label: '需持续跟踪', value: `${qmqfItems.value.length + professionalAlertItems.value.length}处` },
    ],
    objectsTitle: '二、重点对象与现场照片',
    objects: objectRows.map((item) => ({
      title: item.title,
      tag: item.label,
      desc: item.desc,
      photos: item.photos,
    })),
    conclusionTitle: '三、监测结论',
    conclusionParagraphs: [
      '近期高切坡总体处于常态化监测管理状态，局部对象需结合现场异常和专业监测变化持续跟踪。建议对照片反映较明显、多项异常叠加或专业监测持续变化的对象组织现场核查，并形成复核处置记录。',
    ],
  })

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>高切坡近期情况业务简报</title>
  <style>
    @page { size: A4; margin: 22mm 20mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #111827;
      font-family: "FangSong", "仿宋", "SimSun", "宋体", serif;
      font-size: 16px;
      line-height: 1.85;
      background: #fff;
    }
    .doc { max-width: 760px; margin: 0 auto; }
    h1 {
      margin: 0 0 16px;
      text-align: center;
      font-family: "SimHei", "黑体", sans-serif;
      font-size: 28px;
      font-weight: 700;
      line-height: 1.4;
    }
    .meta {
      margin-bottom: 18px;
      border-top: 2px solid #111827;
      border-bottom: 1px solid #111827;
      color: #374151;
      font-size: 14px;
      line-height: 2.2;
      text-align: center;
    }
    h2 {
      margin: 20px 0 8px;
      font-family: "SimHei", "黑体", sans-serif;
      font-size: 18px;
    }
    p { margin: 0 0 8px; text-indent: 2em; }
    .summary {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 14px 0 16px;
      font-family: "SimSun", "宋体", serif;
    }
    .summary div {
      border: 1px solid #9ca3af;
      padding: 8px 10px;
      text-align: center;
    }
    .summary b {
      display: block;
      font-size: 22px;
      font-family: "SimHei", "黑体", sans-serif;
    }
    .object {
      break-inside: avoid;
      margin: 12px 0 16px;
      border: 1px solid #cbd5e1;
      padding: 12px;
    }
    .object h3 {
      margin: 0 0 6px;
      font-family: "SimHei", "黑体", sans-serif;
      font-size: 17px;
    }
    .tag {
      display: inline-block;
      margin-bottom: 6px;
      border: 1px solid #b91c1c;
      color: #b91c1c;
      font-family: "SimHei", "黑体", sans-serif;
      font-size: 16px;
      padding: 2px 8px;
    }
    .desc { margin: 0 0 8px; color: #374151; text-indent: 0; }
    .photos {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      margin-top: 8px;
    }
    figure { margin: 0; break-inside: avoid; }
    img {
      display: block;
      width: 100%;
      height: 170px;
      object-fit: cover;
      border: 1px solid #d1d5db;
    }
    figcaption {
      color: #4b5563;
      font-size: 13px;
      line-height: 1.6;
      text-align: center;
    }
    .conclusion p { text-indent: 2em; }
    .print-tip {
      margin: 18px 0;
      color: #6b7280;
      font-size: 13px;
      text-align: center;
    }
    @media print {
      .print-tip { display: none; }
      .object { page-break-inside: avoid; }
    }
  </style>
</head>
<body>
  <main class="doc">
    <h1>高切坡近期情况业务简报</h1>
    <div class="meta">湖北省高切坡智能监测业务简报&nbsp;&nbsp;&nbsp;&nbsp;生成日期：${escapeHtml(new Date().toLocaleDateString('zh-CN'))}</div>

    <section>
      <h2>一、总体情况</h2>
      <p>湖北省纳入监测的 525 处高切坡中，绝大多数处于正常状态。近期系统识别到 ${qmqfItems.value.length} 处群测群防异常高切坡、${professionalAlertItems.value.length} 处专业监测位移变化相对较大的高切坡，局部对象需结合现场照片和既有报告材料持续跟踪。</p>
      <div class="summary">
        <div><span>群测群防异常</span><b>${qmqfItems.value.length}处</b></div>
        <div><span>专业监测关注</span><b>${professionalAlertItems.value.length}处</b></div>
        <div><span>需持续跟踪</span><b>${qmqfItems.value.length + professionalAlertItems.value.length}处</b></div>
      </div>
      <p>群测群防异常主要涉及${escapeHtml(abnormalTypeText.value)}；专业监测结论以${escapeHtml(stabilityText.value)}为主，整体未见需要普遍提升风险等级的趋势。</p>
    </section>

    <section>
      <h2>二、重点对象与现场照片</h2>
      ${objectRows.map((item) => `
        <article class="object">
          <h3>${escapeHtml(item.title)}</h3>
          <span class="tag">${escapeHtml(item.label)}</span>
          <p class="desc">${escapeHtml(item.desc)}</p>
          ${item.photos.length ? `<div class="photos">${item.photos.map((photo: BriefPhotoItem) => `
            <figure>
              <img src="${escapeAttr(photo.url)}" alt="${escapeAttr(photo.label)}" />
              <figcaption>${escapeHtml(photo.label)}</figcaption>
            </figure>
          `).join('')}</div>` : ''}
        </article>
      `).join('')}
    </section>

    <section class="conclusion">
      <h2>三、监测结论</h2>
      <p>综合群测群防异常记录、专业监测位移变化和现场照片情况，湖北省 525 处高切坡总体运行状态平稳，绝大多数处于正常状态。</p>
      <p>少数存在现场异常记录或月报评价一般的对象，应结合照片复核异常部位是否持续发展；专业监测缓慢变形对象，应重点核对同一坡体多个监测点变化是否具有一致性。</p>
      <p>后续建议保持常态化监测和巡查，对照片异常、月报明确描述裂缝或排水问题、位移变化连续增大的对象纳入持续跟踪清单。</p>
    </section>

    <div class="print-tip">请在弹出的打印窗口中选择“另存为 PDF”。</div>
  </main>
</body>
</html>`
}

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeAttr(value: unknown) {
  return escapeHtml(value).replace(/`/g, '&#96;')
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.brief {
  display: grid;
  gap: 14px;
}

.brief-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.brief-head h3,
.brief-section h4 {
  margin: 0;
  color: #172033;
}

.brief-head p {
  margin: 5px 0 0;
  color: #667085;
  font-size: 13px;
}

.brief-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.brief-grid article,
.brief-section {
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
}

.brief-grid span {
  color: #667085;
  font-size: 12px;
}

.brief-grid strong {
  display: block;
  margin-top: 5px;
  color: #172033;
  font-size: 22px;
}

.brief-grid p,
.brief-section p {
  margin: 8px 0 0;
  color: #475467;
  font-size: 13px;
  line-height: 1.7;
}

.conclusion-list {
  display: grid;
  gap: 4px;
  margin-top: 8px;
}

.focus-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.focus-list div {
  display: grid;
  gap: 3px;
  border-bottom: 1px solid #edf1f6;
  padding-bottom: 8px;
}

.focus-list .focus-item {
  gap: 8px;
  padding-bottom: 12px;
}

.focus-list b {
  color: #172033;
  font-size: 15px;
  line-height: 1.45;
}

.focus-list span {
  color: #667085;
  font-size: 13px;
}

.focus-list .slope-code {
  color: #667085;
  font-size: 12px;
}

.contact-line {
  color: #344054 !important;
  font-weight: 600;
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

.abnormal-text.displacement {
  background: #fff7e6;
  color: #b54708;
}

.abnormal-text.report {
  background: #eef8f3;
  color: #047857;
}

.report-item > span {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.section-title span {
  color: #667085;
  font-size: 12px;
}

.brief-photo-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.inline-photo-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 128px));
  gap: 8px;
}

.brief-photo-card {
  overflow: hidden;
  margin: 0;
  border: 1px solid #e4e8ef;
  border-radius: 8px;
  background: #f8fafc;
  cursor: zoom-in;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.brief-photo-card:hover,
.brief-photo-card:focus-visible {
  border-color: #3b82f6;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
  outline: none;
  transform: translateY(-1px);
}

.brief-photo-card img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  background: #eef2f7;
}

.brief-photo-card figcaption {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
}

.brief-photo-card.compact figcaption {
  padding: 6px 8px;
}

.brief-photo-card.compact strong {
  font-size: 12px;
}

.brief-photo-card strong {
  overflow: hidden;
  color: #172033;
  font-size: 13px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brief-photo-card span {
  overflow: hidden;
  color: #667085;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.brief-photo-dialog .el-dialog__body) {
  padding-top: 8px;
}

.brief-photo-preview {
  display: grid;
  gap: 12px;
}

.brief-photo-preview img {
  display: block;
  width: 100%;
  max-height: 72vh;
  object-fit: contain;
  border-radius: 8px;
  background: #0f172a;
}

.brief-photo-preview-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  color: #475467;
  font-size: 13px;
}

.brief-photo-preview-meta strong {
  color: #172033;
  font-size: 15px;
}

@media (max-width: 860px) {
  .brief-grid,
  .brief-photo-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .brief-head {
    flex-direction: column;
  }

  .brief-head h3 {
    font-size: 18px;
  }

  .brief-grid article,
  .brief-section {
    padding: 12px;
  }

  .section-title {
    flex-direction: column;
    gap: 4px;
  }

  .inline-photo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .abnormal-text {
    font-size: 15px;
  }

  :global(.brief-photo-dialog) {
    width: 96vw !important;
    margin-top: 5vh !important;
  }

  .brief-photo-preview img {
    max-height: 66vh;
  }
}
</style>
