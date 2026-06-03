<template>
  <section class="result-card">
    <div v-if="isDamagePhotoResult" class="damage-overview">
      <div>
        <p class="eyebrow">现场核查成果</p>
        <h3>典型破坏状态下的高切坡现状照片</h3>
        <p>
          已筛选 {{ totalRows }} 条包含裂缝、落石或坡面破坏特征的群测群防记录，
          当前优先展示 {{ rows.length }} 条重点对象和 {{ availableImageItems.length }} 张可访问照片。
        </p>
      </div>
      <el-tag type="danger" effect="plain">重点核查</el-tag>
    </div>

    <div v-else class="result-header">
      <div>
        <h3>结果明细</h3>
        <p v-if="totalRows">共 {{ totalRows }} 条，本页 {{ rows.length }} 条</p>
        <p v-else>暂无可展示表格数据</p>
      </div>
      <el-tag v-if="availableImageItems.length" type="success" effect="plain">含现场照片</el-tag>
    </div>

    <el-empty v-if="!rows.length" description="暂无表格数据" />

    <div v-if="monitoringScaleChartItems.length" class="result-chart-block">
      <ReportBarChart
        title="湖北四县区群测群防监测数量统计"
        unit="处"
        :items="monitoringScaleChartItems"
      />
    </div>

    <div v-if="isDamagePhotoResult && availableImageItems.length" class="damage-section">
      <div class="section-title">
        <h4>一、现场照片</h4>
        <span>按高切坡对象关联展示，点击可查看原图</span>
      </div>
      <div class="damage-photo-grid">
        <a
          v-for="item in visibleImageItems"
          :key="item.url"
          :href="item.url"
          target="_blank"
          rel="noreferrer"
          class="damage-photo-card"
        >
          <img
            :src="item.url"
            :alt="item.label"
            loading="lazy"
            decoding="async"
            fetchpriority="low"
            @error="markImageFailed(item.url)"
          />
          <div>
            <strong>{{ item.slopeName || item.slopeCode || item.label }}</strong>
            <span>{{ item.county || '所属区县待核实' }} · {{ item.abnormalType || '异常类型待核实' }}</span>
          </div>
        </a>
      </div>
      <div v-if="canShowMoreImages" class="photo-actions">
        <el-button size="small" plain @click="showMoreImages">
          再显示 {{ nextImageBatchSize }} 张照片
        </el-button>
        <span>已显示 {{ visibleImageItems.length }} / {{ availableImageItems.length }}</span>
      </div>
    </div>

    <div v-else-if="availableImageItems.length" class="photo-block">
      <div class="photo-strip">
        <a
          v-for="item in visibleImageItems"
          :key="item.url"
          :href="item.url"
          target="_blank"
          rel="noreferrer"
          class="photo-item"
        >
          <img
            :src="item.url"
            :alt="item.label"
            loading="lazy"
            decoding="async"
            fetchpriority="low"
            @error="markImageFailed(item.url)"
          />
          <span>{{ item.label }}</span>
        </a>
      </div>
      <div v-if="canShowMoreImages" class="photo-actions">
        <el-button size="small" plain @click="showMoreImages">
          再显示 {{ nextImageBatchSize }} 张照片
        </el-button>
        <span>已显示 {{ visibleImageItems.length }} / {{ availableImageItems.length }}</span>
      </div>
    </div>

    <div v-if="isDamagePhotoResult && rows.length" class="damage-section">
      <div class="section-title">
        <h4>二、重点对象</h4>
        <span>用于现场复核、隐患研判和照片归档</span>
      </div>
      <div class="focus-list">
        <article v-for="(row, index) in focusRows" :key="`${row.gqpbh || index}-${index}`" class="focus-item">
          <div class="focus-rank">{{ index + 1 }}</div>
          <div>
            <h5>{{ row.gqpmc || row.gqpbh || '未命名高切坡' }}</h5>
            <p>{{ row.ssqx || '所属区县待核实' }} · {{ row.gqpbh || '编号待核实' }}</p>
          </div>
          <el-tag type="warning" effect="plain">{{ row.abnormal_type || '异常待核实' }}</el-tag>
        </article>
      </div>
      <div class="advice-box">
        <strong>研判建议</strong>
        <p>建议优先复核照片中裂缝、落石、坡面破坏和挡墙开裂部位，结合近期雨情、巡查记录和专业监测位移变化，判断是否需要提高巡查频次或纳入重点处置清单。</p>
      </div>
    </div>

    <el-table
      v-if="rows.length"
      :data="rows"
      border
      stripe
      height="320"
      class="result-table"
    >
      <el-table-column
        v-for="column in visibleTableColumns"
        :key="column"
        :prop="column"
        :label="displayColumnLabel(column)"
        min-width="160"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <a
            v-if="isVisibleImageValue(row[column])"
            :href="buildImageUrl(row[column])"
            target="_blank"
            rel="noreferrer"
            class="image-link"
          >
            查看照片
          </a>
          <span v-else>{{ displayCellValue(row[column]) }}</span>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { buildBackendUrl, buildPhotoCacheUrl } from '../api/query'
import ReportBarChart from './ReportBarChart.vue'

const props = defineProps<{
  columns: string[]
  rows: Record<string, string>[]
  totalRows: number
}>()

const MIN_PHOTO_MONTH = 202506
const PHOTO_ROW_SCAN_LIMIT = 8
const PHOTO_INITIAL_LIMIT = 4
const PHOTO_BATCH_SIZE = 4

const failedImageUrls = ref(new Set<string>())
const visibleImageLimit = ref(PHOTO_INITIAL_LIMIT)

const COLUMN_LABELS: Record<string, string> = {
  gqpbh: '高切坡编号',
  gqpmc: '高切坡名称',
  ssqx: '所属区县',
  abnormal_type: '异常类型',
  abnormal_slope_count: '异常高切坡数量',
  abnormal_slope_count_label: '异常高切坡数量',
  abnormalSlopeCount: '异常高切坡数量',
  slope_count: '高切坡数量',
  hcs_count: '高切坡数量',
  professional_slope_count: '专业监测高切坡数量',
  professional_point_count: '专业监测点数量',
  qmqf_slope_count: '群测群防高切坡数量',
  qmqf_record_count: '群测群防监测记录数',
  monitor_count: '监测数量',
  overallSituation: '总体情况',
  hcSlopeStatus: '审核异常状态',
  statusReason: '异常原因',
  photoOn: '拍照时间',
  photoNo1: '现场照片1',
  photoNo2: '现场照片2',
  photoNo3: '现场照片3',
  crackImageUri: '裂缝照片',
  wallCrackingImageUri: '挡墙/道路开裂照片',
  createdOn: '记录时间',
  updatedOn: '更新时间',
  county: '区县',
  report_period: '报告期',
  file_name: '报告文件',
  page_no: '页码',
  key_monitor_points: '重点监测点',
  related_slope_codes: '关联高切坡编号',
  displacement_summary: '位移变化摘要',
  chart_location: '折线图位置',
  original_chart_url: '原始曲线增强图',
  plugin_chart_url: '插件重绘图',
  digitized_data_url: '提取数据',
  redrawn_chart_url: '高清折线图',
  chart_rebuild_status: '高清重绘状态',
  point_count: '监测点数量',
  max_recent_change_mm: '最大变化量(mm)',
  jcdbh: '监测点编号',
  latest_date: '最新监测日期',
  record_count: '记录数',
  bqxfxwy_mm: 'X向变化量(mm)',
  bqyfxwy_mm: 'Y向变化量(mm)',
  bqhfxwy_mm: 'H向变化量(mm)',
  recent_change_mm: '本点最大变化量(mm)',
  stability_level: '稳定性评价',
  stability_advice: '处置建议',
  displacement_chart_url: '位移变化图',
  created_at: '创建时间',
  updated_at: '更新时间',
  created_on: '记录时间',
  updated_on: '更新时间',
  name: '名称',
  code: '编号',
  location: '位置',
  address: '地址',
  remark: '备注',
  status: '状态',
  type: '类型',
  value: '数值',
  count: '数量',
}
const imageColumns = computed(() => props.columns.filter((column) => isImageColumn(column)))

const isDamagePhotoResult = computed(() => {
  return (
    availableImageItems.value.length > 0 &&
    props.columns.includes('abnormal_type') &&
    props.columns.some((column) => /photo|image|uri|鐓х墖/i.test(column))
  )
})

const visibleTableColumns = computed(() => {
  const businessColumns = props.columns.filter((column) => shouldShowBusinessColumn(column))
  if (businessColumns.length && !isDamagePhotoResult.value) {
    return removeEmptyColumns(businessColumns)
  }
  if (!isDamagePhotoResult.value) {
    return removeEmptyColumns(props.columns.filter((column) => !isUnknownEnglishColumn(column)))
  }
  const hiddenColumns = new Set([
    'photoNo1',
    'photoNo2',
    'photoNo3',
    'crackImageUri',
    'wallCrackingImageUri',
    'overallSituation',
    'statusReason',
    '异常原因',
    'hcSlopeStatus',
  ])
  return removeEmptyColumns(
    props.columns.filter(
      (column) => !hiddenColumns.has(column) && !/^is[A-Z]/.test(column) && shouldShowBusinessColumn(column),
    ),
  )
})

const monitoringScaleChartItems = computed(() => {
  if (!props.columns.includes('区县') || !props.columns.includes('群测群防高切坡数量')) {
    return []
  }
  return props.rows
    .filter((row) => !String(row['区县'] || '').includes('合计'))
    .map((row) => ({
      name: String(row['区县'] || ''),
      value: Number(row['群测群防高切坡数量'] || 0),
    }))
    .filter((item) => item.name && Number.isFinite(item.value))
})

const focusRows = computed(() => props.rows.slice(0, 6))

const imageItems = computed(() => {
  const items: Array<{
    url: string
    label: string
    slopeCode: string
    slopeName: string
    county: string
    abnormalType: string
  }> = []
  props.rows.slice(0, PHOTO_ROW_SCAN_LIMIT).forEach((row, rowIndex) => {
    imageColumns.value.forEach((column) => {
      const url = buildImageUrl(row[column])
      if (url && isAllowedPhotoDate(url)) {
        items.push({
          url,
          label: `${displayColumnLabel(column)} #${rowIndex + 1}`,
          slopeCode: String(row.gqpbh || ''),
          slopeName: String(row.gqpmc || ''),
          county: String(row.ssqx || ''),
          abnormalType: String(row.abnormal_type || ''),
        })
      }
    })
  })
  return items
})

const availableImageItems = computed(() => {
  return imageItems.value.filter((item) => !failedImageUrls.value.has(item.url))
})

const visibleImageItems = computed(() => {
  return availableImageItems.value.slice(0, visibleImageLimit.value)
})

const canShowMoreImages = computed(() => visibleImageItems.value.length < availableImageItems.value.length)

const nextImageBatchSize = computed(() => {
  return Math.min(PHOTO_BATCH_SIZE, availableImageItems.value.length - visibleImageItems.value.length)
})

watch(
  () => props.rows,
  () => {
    visibleImageLimit.value = PHOTO_INITIAL_LIMIT
    failedImageUrls.value = new Set<string>()
  },
)

function isImageColumn(column: string) {
  return /photo|image|img|pic|uri|chart|redrawn|照片|图片|折线图/i.test(column)
}

function displayColumnLabel(column: string) {
  return COLUMN_LABELS[column] || column
}

function hasChinese(value: string) {
  return /[\u4e00-\u9fa5]/.test(value)
}

function isUnknownEnglishColumn(column: string) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(column) && !COLUMN_LABELS[column]
}

function shouldShowBusinessColumn(column: string) {
  if (hasChinese(column) || COLUMN_LABELS[column]) {
    return true
  }
  return !isUnknownEnglishColumn(column)
}

function removeEmptyColumns(columns: string[]) {
  const rowCount = Math.max(props.rows.length, 1)
  return columns.filter((column) => {
    if (isAlwaysHiddenColumn(column)) {
      return false
    }
    const filledCount = props.rows.filter((row) => hasDisplayContent(row[column])).length
    if (!filledCount) {
      return false
    }
    if (isCoreBusinessColumn(column)) {
      return true
    }
    return filledCount / rowCount >= 0.15
  })
}

function isAlwaysHiddenColumn(column: string) {
  return ['statusReason', '异常原因'].includes(column)
}

function isCoreBusinessColumn(column: string) {
  const label = displayColumnLabel(column)
  return /濮撳悕|璐﹀彿|瑙掕壊|鍖哄幙|楂樺垏鍧＄紪鍙穦楂樺垏鍧″悕绉皘缂栧彿|鍚嶇О|寮傚父|鏁伴噺|鎵嬫満鍙穦鏃堕棿|鏃ユ湡|璇勪环|寤鸿/.test(label)
}

function hasDisplayContent(value?: string) {
  const raw = String(value ?? '').trim()
  if (!raw) {
    return false
  }
  const normalized = raw.replace(/\s+/g, '').toLowerCase()
  return !['null', 'none', 'undefined', '-', '--', '—', '暂无', '无', '未填', '待核实'].includes(normalized)
}

function isVisibleImageValue(value?: string) {
  const url = buildImageUrl(value)
  return Boolean(url && isAllowedPhotoDate(url) && !failedImageUrls.value.has(url))
}

function markImageFailed(url: string) {
  const next = new Set(failedImageUrls.value)
  next.add(url)
  failedImageUrls.value = next
}

function showMoreImages() {
  visibleImageLimit.value += PHOTO_BATCH_SIZE
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
  if (month) {
    return buildPhotoCacheUrl(`/u/mon/${month}/${filename}`, 'thumb')
  }

  return buildPhotoCacheUrl(`/u/mon/${normalized}`, 'thumb')
}

function isAllowedPhotoDate(url: string) {
  if (url.includes('/report-assets/')) {
    return true
  }
  const month = url.match(/\/(20\d{4})\//)?.[1] || url.match(/_(20\d{4})\d{8}_/)?.[1]
  if (!month) {
    return false
  }
  return Number(month) >= MIN_PHOTO_MONTH
}

function displayCellValue(value?: string) {
  const raw = String(value || '').trim()
  if (!raw || raw.toLowerCase() === 'null' || raw.toLowerCase() === 'none') {
    return '-'
  }
  if (raw === 'True' || raw === 'true' || raw === '1') {
    return '是'
  }
  if (raw === 'False' || raw === 'false' || raw === '0') {
    return '否'
  }
  return raw
}
</script>

<style scoped>
.result-card {
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid #e4e8ef;
  border-radius: 8px;
  background: #fff;
}

.result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid #edf1f6;
}

.result-header h3 {
  margin: 0;
  color: #1f2937;
  font-size: 15px;
}

.result-header p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 12px;
}

.damage-overview {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid #edf1f6;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}

.damage-overview h3 {
  margin: 4px 0 8px;
  color: #0f172a;
  font-size: 18px;
}

.damage-overview p {
  margin: 0;
  color: #53627a;
  font-size: 13px;
  line-height: 1.7;
}

.eyebrow {
  color: #1b5cff !important;
  font-size: 12px !important;
  font-weight: 700;
}

.damage-section {
  padding: 16px 20px;
  border-bottom: 1px solid #edf1f6;
  background: #fff;
}

.result-chart-block {
  padding: 16px 20px;
  border-bottom: 1px solid #edf1f6;
  background: #fff;
}

.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-title h4 {
  margin: 0;
  color: #111827;
  font-size: 15px;
}

.section-title span {
  color: #667085;
  font-size: 12px;
}

.damage-photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}

.damage-photo-card {
  overflow: hidden;
  border: 1px solid #e4e8ef;
  border-radius: 8px;
  color: #1f2937;
  text-decoration: none;
  background: #fff;
}

.damage-photo-card img {
  width: 100%;
  aspect-ratio: 4 / 3;
  background: #f1f5f9;
  object-fit: cover;
}

.damage-photo-card div {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.damage-photo-card strong {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.damage-photo-card span {
  overflow: hidden;
  color: #667085;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-list {
  display: grid;
  gap: 8px;
}

.focus-item {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid #e7edf6;
  border-radius: 8px;
  background: #f8fafc;
}

.focus-rank {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  color: #1b5cff;
  font-size: 13px;
  font-weight: 700;
  background: #e9f0ff;
}

.focus-item h5 {
  margin: 0 0 4px;
  color: #111827;
  font-size: 14px;
}

.focus-item p,
.advice-box p {
  margin: 0;
  color: #667085;
  font-size: 12px;
}

.advice-box {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #f4f8ff;
}

.advice-box strong {
  display: block;
  margin-bottom: 6px;
  color: #1e40af;
  font-size: 13px;
}

.photo-block {
  border-bottom: 1px solid #edf1f6;
  background: #f8fafc;
}

.photo-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(126px, 1fr));
  gap: 10px;
  padding: 14px 16px;
}

.photo-item {
  display: grid;
  gap: 6px;
  color: #344054;
  font-size: 12px;
  text-decoration: none;
}

.photo-item img {
  width: 100%;
  aspect-ratio: 4 / 3;
  border: 1px solid #d9e3f5;
  border-radius: 8px;
  background: #fff;
  object-fit: cover;
}

.photo-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 0 16px 14px;
  color: #667085;
  font-size: 12px;
}

.result-table {
  width: 100%;
}

.result-table :deep(.el-table__header th) {
  background: #f3f4f6;
  color: #111827;
  font-size: 14px;
  font-weight: 700;
}

.result-table :deep(.el-table__cell) {
  border-color: #d8dee9;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.65;
}

.result-table :deep(.el-table__row--striped .el-table__cell) {
  background: #fafafa;
}

.result-table :deep(.cell) {
  line-height: 1.65;
}

.image-link {
  color: #1b5cff;
  text-decoration: none;
}

.image-link:hover {
  text-decoration: underline;
}

@media (max-width: 640px) {
  .result-header {
    flex-direction: column;
  }

  .result-card {
    margin-right: -4px;
    margin-left: -4px;
  }

  .damage-overview,
  .section-title {
    flex-direction: column;
  }

  .damage-section,
  .result-chart-block {
    padding: 12px;
  }

  .damage-photo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .photo-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .focus-item {
    grid-template-columns: 28px minmax(0, 1fr);
  }

  .focus-item :deep(.el-tag) {
    grid-column: 1 / -1;
    width: fit-content;
  }

  .result-table {
    font-size: 12px;
  }

  .result-table :deep(.el-table__cell) {
    font-size: 12px;
  }

  .photo-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
