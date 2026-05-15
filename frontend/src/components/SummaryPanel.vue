<template>
  <el-card shadow="never" class="panel-card">
    <template #header>
      <div class="panel-header">
        <span>查询报告</span>
        <div class="header-actions">
          <el-button
            text
            type="primary"
            :disabled="!canShare || exporting"
            @click="shareQuery"
          >
            分享本次查询
          </el-button>
          <el-button
            text
            type="primary"
            :disabled="!canShare || exporting"
            @click="exportPdf"
          >
            {{ exporting ? '正在导出' : '导出 PDF' }}
          </el-button>
        </div>
      </div>
    </template>

    <pre class="summary-block">{{ summary || '暂无报告' }}</pre>
    <div v-if="summary.trim()" class="speech-inline">
      <SpeechPlayer :summary="summary" compact />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Capacitor } from '@capacitor/core'
import { Filesystem, Directory } from '@capacitor/filesystem'
import { Share } from '@capacitor/share'
import { ElMessage } from 'element-plus'
import SpeechPlayer from './SpeechPlayer.vue'

const props = defineProps<{
  question: string
  summary: string
  columns: string[]
  rows: Record<string, string>[]
}>()

const canShare = computed(() => {
  return Boolean(props.question.trim() || props.summary.trim() || props.rows.length)
})
const exporting = ref(false)
const MAX_EXPORT_ROWS = 20

const buildShareText = () => {
  const sections: string[] = ['高切坡智能查询分享']

  if (props.question.trim()) {
    sections.push(`问题：${props.question.trim()}`)
  }

  if (props.summary.trim()) {
    sections.push(`查询报告：${props.summary.trim()}`)
  }

  if (props.rows.length) {
    sections.push(`查询结果：共 ${props.rows.length} 条`)
    props.rows.slice(0, 10).forEach((row, index) => {
      const rowText = props.columns
        .map((column) => `${column}：${row[column] || '-'}`)
        .join('，')
      sections.push(`${index + 1}. ${rowText}`)
    })
    if (props.rows.length > 10) {
      sections.push('其余结果请在系统中查看。')
    }
  }

  return sections.join('\n\n')
}

const copyText = async (text: string) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

const buildExportTitle = () => {
  const now = new Date()
  const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate()
  ).padStart(2, '0')}`
  return `高切坡智能查询-${date}`
}

const createExportContainer = () => {
  const container = document.createElement('div')
  container.style.position = 'fixed'
  container.style.left = '-10000px'
  container.style.top = '0'
  container.style.width = Capacitor.isNativePlatform() ? '920px' : '1120px'
  container.style.padding = '40px'
  container.style.background = '#ffffff'
  container.style.color = '#1f2d3d'
  container.style.fontFamily =
    'Arial, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'
  container.style.boxSizing = 'border-box'

  const title = document.createElement('h1')
  title.textContent = '高切坡智能查询导出'
  title.style.margin = '0 0 24px'
  title.style.fontSize = '28px'
  title.style.fontWeight = '700'
  container.appendChild(title)

  const appendSection = (label: string, content: string) => {
    const section = document.createElement('section')
    section.style.marginBottom = '24px'

    const heading = document.createElement('h2')
    heading.textContent = label
    heading.style.margin = '0 0 12px'
    heading.style.fontSize = '18px'
    heading.style.fontWeight = '700'

    const body = document.createElement('div')
    body.textContent = content || '暂无内容'
    body.style.padding = '16px'
    body.style.border = '1px solid #dfe7f2'
    body.style.borderRadius = '8px'
    body.style.background = '#f8fbff'
    body.style.whiteSpace = 'pre-wrap'
    body.style.wordBreak = 'break-word'
    body.style.lineHeight = '1.8'
    body.style.fontSize = '14px'

    section.appendChild(heading)
    section.appendChild(body)
    container.appendChild(section)
  }

  appendSection('问题', props.question.trim())
  appendSection('查询报告', props.summary.trim())

  const resultSection = document.createElement('section')
  resultSection.style.marginBottom = '12px'

  const resultHeading = document.createElement('h2')
  resultHeading.textContent = `查询结果${props.rows.length ? `（共 ${props.rows.length} 条）` : ''}`
  resultHeading.style.margin = '0 0 12px'
  resultHeading.style.fontSize = '18px'
  resultHeading.style.fontWeight = '700'
  resultSection.appendChild(resultHeading)

  if (!props.rows.length) {
    const empty = document.createElement('div')
    empty.textContent = '暂无表格数据'
    empty.style.padding = '16px'
    empty.style.border = '1px solid #dfe7f2'
    empty.style.borderRadius = '8px'
    empty.style.background = '#ffffff'
    resultSection.appendChild(empty)
  } else {
    const exportRows = props.rows.slice(0, MAX_EXPORT_ROWS)
    const table = document.createElement('table')
    table.style.width = '100%'
    table.style.borderCollapse = 'collapse'
    table.style.tableLayout = 'fixed'
    table.style.fontSize = '12px'

    const thead = document.createElement('thead')
    const headRow = document.createElement('tr')
    props.columns.forEach((column) => {
      const th = document.createElement('th')
      th.textContent = column
      th.style.border = '1px solid #dfe7f2'
      th.style.padding = '10px 8px'
      th.style.background = '#f5f7fa'
      th.style.textAlign = 'left'
      th.style.wordBreak = 'break-word'
      headRow.appendChild(th)
    })
    thead.appendChild(headRow)
    table.appendChild(thead)

    const tbody = document.createElement('tbody')
    exportRows.forEach((row) => {
      const tr = document.createElement('tr')
      props.columns.forEach((column) => {
        const td = document.createElement('td')
        td.textContent = row[column] || '-'
        td.style.border = '1px solid #dfe7f2'
        td.style.padding = '8px 6px'
        td.style.verticalAlign = 'top'
        td.style.wordBreak = 'break-word'
        tr.appendChild(td)
      })
      tbody.appendChild(tr)
    })
    table.appendChild(tbody)
    resultSection.appendChild(table)

    if (props.rows.length > MAX_EXPORT_ROWS) {
      const note = document.createElement('p')
      note.textContent = `PDF 为控制体积仅展示前 ${MAX_EXPORT_ROWS} 条结果，其余结果请在系统中查看。`
      note.style.margin = '12px 0 0'
      note.style.color = '#5f6f86'
      note.style.fontSize = '12px'
      resultSection.appendChild(note)
    }
  }

  container.appendChild(resultSection)
  document.body.appendChild(container)
  return container
}

const exportPdf = async () => {
  if (!canShare.value) {
    ElMessage.warning('暂无可导出内容')
    return
  }

  exporting.value = true
  let container: HTMLDivElement | null = null

  try {
    const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
      import('html2canvas'),
      import('jspdf'),
    ])

    container = createExportContainer()
    const canvas = await html2canvas(container, {
      backgroundColor: '#ffffff',
      scale: Capacitor.isNativePlatform() ? 1.2 : 2,
      useCORS: true,
    })

    const imageData = canvas.toDataURL('image/jpeg', 0.9)
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const imageWidth = pageWidth - 20
    const imageHeight = (canvas.height * imageWidth) / canvas.width

    let remainingHeight = imageHeight
    let position = 10

    pdf.addImage(imageData, 'JPEG', 10, position, imageWidth, imageHeight)
    remainingHeight -= pageHeight - 20

    while (remainingHeight > 0) {
      position = remainingHeight - imageHeight + 10
      pdf.addPage()
      pdf.addImage(imageData, 'JPEG', 10, position, imageWidth, imageHeight)
      remainingHeight -= pageHeight - 20
    }

    const filename = `${buildExportTitle()}.pdf`

    if (Capacitor.isNativePlatform()) {
      const pdfBase64 = pdf.output('datauristring').split(',')[1]
      const writeResult = await Filesystem.writeFile({
        path: filename,
        data: pdfBase64,
        directory: Directory.Cache,
      })

      await Share.share({
        title: '高切坡智能查询导出',
        text: '已生成本次查询 PDF，可直接分享到微信、文件或邮件。',
        url: writeResult.uri,
        dialogTitle: '分享本次查询 PDF',
      })
      ElMessage.success('已生成 PDF，请选择分享位置')
      return
    }

    pdf.save(filename)
    ElMessage.success('已导出 PDF')
  } catch (error) {
    ElMessage.warning('导出 PDF 失败，请稍后重试')
  } finally {
    if (container) {
      document.body.removeChild(container)
    }
    exporting.value = false
  }
}

const shareQuery = async () => {
  const text = buildShareText()
  if (!text.trim()) {
    ElMessage.warning('暂无可分享内容')
    return
  }

  try {
    if (Capacitor.isNativePlatform()) {
      await Share.share({
        title: '高切坡智能查询',
        text,
      })
      return
    }

    if (navigator.share) {
      await navigator.share({
        title: '高切坡智能查询',
        text,
      })
      return
    }

    await copyText(text)
    ElMessage.success('已复制本次查询内容，可直接分享')
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      return
    }
    try {
      await copyText(text)
      ElMessage.success('分享未完成，已复制本次查询内容')
    } catch {
      ElMessage.warning('分享失败，请稍后重试')
    }
  }
}
</script>

<style scoped>
.panel-card {
  height: 100%;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.summary-block {
  min-height: 120px;
  margin: 0;
  color: #253044;
  font-family: Arial, Helvetica, sans-serif;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.speech-inline {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #edf2f7;
}

@media (max-width: 640px) {
  .panel-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .header-actions {
    gap: 0;
    flex-wrap: wrap;
  }
}
</style>
