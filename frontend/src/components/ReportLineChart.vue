<template>
  <div class="report-chart">
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphicComponent, GridComponent, LegendComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from 'echarts/components'
import { LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'

echarts.use([GraphicComponent, GridComponent, LegendComponent, MarkLineComponent, MarkPointComponent, TooltipComponent, LineChart, CanvasRenderer])

type SeriesRow = {
  date: string
  x?: number
  y?: number
  h?: number
}

const props = defineProps<{
  title: string
  subtitle?: string
  rows: SeriesRow[]
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

const labels = computed(() => props.rows.map((row) => String(row.date || '').slice(0, 7)))
const allValues = computed(() =>
  props.rows.flatMap((row) => ['x', 'y', 'h'].map((key) => Number(row[key as 'x' | 'y' | 'h'] || 0))),
)
const maxAbsValue = computed(() => Math.max(1, ...allValues.value.map((value) => Math.abs(value))))
const maxChangePoint = computed(() => {
  const directions: Array<{ key: 'x' | 'y' | 'h'; name: string }> = [
    { key: 'x', name: 'X向位移变化量' },
    { key: 'y', name: 'Y向位移变化量' },
    { key: 'h', name: 'H向位移变化量' },
  ]
  let result = {
    key: 'x' as 'x' | 'y' | 'h',
    seriesName: 'X向位移变化量',
    date: labels.value[0] || '',
    value: 0,
  }
  props.rows.forEach((row) => {
    directions.forEach((direction) => {
      const value = Number(row[direction.key])
      if (Number.isFinite(value) && Math.abs(value) > Math.abs(result.value)) {
        result = {
          key: direction.key,
          seriesName: direction.name,
          date: String(row.date || '').slice(0, 7),
          value,
        }
      }
    })
  })
  return result
})

function values(key: 'x' | 'y' | 'h') {
  return props.rows.map((row) => {
    const value = Number(row[key])
    return Number.isFinite(value) ? Number(value.toFixed(2)) : 0
  })
}

function buildOption() {
  const thresholdLines = [
    { yAxis: 10, name: '10mm 缓慢变形关注线' },
    { yAxis: 20, name: '20mm 明显变形关注线' },
    { yAxis: -10, name: '-10mm 缓慢变形关注线' },
    { yAxis: -20, name: '-20mm 明显变形关注线' },
  ].filter((item) => Math.abs(item.yAxis) <= Math.max(22, maxAbsValue.value * 1.18))

  return {
    animation: false,
    backgroundColor: '#ffffff',
    color: ['#1f5fbf', '#21825b', '#c0362c'],
    title: {
      text: props.title,
      subtext: props.subtitle || 'X/Y/H 三向位移变化量，单位：mm',
      left: 18,
      top: 14,
      textStyle: {
        color: '#111827',
        fontSize: 18,
        fontWeight: 700,
        fontFamily: 'Microsoft YaHei, SimHei, sans-serif',
      },
      subtextStyle: {
        color: '#4b5563',
        fontSize: 13,
        lineHeight: 20,
        fontFamily: 'Microsoft YaHei, SimSun, serif',
      },
    },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => `${Number(value).toFixed(2)} mm`,
      axisPointer: {
        type: 'line',
        lineStyle: { color: '#94a3b8', width: 1 },
      },
    },
    legend: {
      top: 76,
      left: 18,
      itemWidth: 28,
      itemHeight: 4,
      textStyle: {
        color: '#334155',
        fontSize: 13,
        fontFamily: 'Microsoft YaHei, SimSun, serif',
      },
      data: ['X向位移变化量', 'Y向位移变化量', 'H向位移变化量'],
    },
    grid: {
      left: 82,
      right: 42,
      top: 124,
      bottom: 76,
      containLabel: false,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels.value,
      name: '监测月份',
      nameLocation: 'middle',
      nameGap: 38,
      axisLabel: {
        color: '#334155',
        fontSize: 13,
        interval: 0,
        rotate: labels.value.length > 10 ? 28 : 0,
        margin: 14,
        fontFamily: 'Microsoft YaHei, SimSun, serif',
      },
      axisLine: { lineStyle: { color: '#6b7280' } },
      axisTick: { alignWithLabel: true, lineStyle: { color: '#9ca3af' } },
      nameTextStyle: {
        color: '#374151',
        fontSize: 13,
        fontWeight: 700,
        fontFamily: 'Microsoft YaHei, SimSun, serif',
      },
    },
    yAxis: {
      type: 'value',
      name: '位移变化量（mm）',
      nameLocation: 'middle',
      nameGap: 52,
      splitNumber: 6,
      axisLabel: {
        color: '#334155',
        fontSize: 14,
        formatter: (value: number) => value.toFixed(1),
        fontFamily: 'Microsoft YaHei, SimSun, serif',
      },
      axisLine: { show: true, lineStyle: { color: '#6b7280' } },
      axisTick: { show: true, lineStyle: { color: '#9ca3af' } },
      splitLine: { lineStyle: { color: '#e5edf5', type: 'solid' } },
      nameTextStyle: {
        color: '#374151',
        fontSize: 14,
        fontWeight: 700,
        fontFamily: 'Microsoft YaHei, SimSun, serif',
      },
    },
    graphic: [
      {
        type: 'text',
        right: 34,
        bottom: 16,
        style: {
          text: `数据序列 ${props.rows.length} 期；阈值线用于辅助研判，最终以现场复核和连续趋势为准。`,
          fill: '#64748b',
          fontSize: 12,
          fontFamily: 'Microsoft YaHei, SimSun, serif',
        },
      },
    ],
    series: [
      withMaxMarker({
        name: 'X向位移变化量',
        type: 'line',
        data: values('x'),
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2.8 },
        markLine: {
          symbol: 'none',
          silent: true,
          label: {
            formatter: '{b}',
            color: '#92400e',
            fontSize: 11,
          },
          lineStyle: {
            color: '#f59e0b',
            type: 'dashed',
            width: 1.4,
          },
          data: thresholdLines,
        },
      }, 'x'),
      withMaxMarker({
        name: 'Y向位移变化量',
        type: 'line',
        data: values('y'),
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2.8 },
      }, 'y'),
      withMaxMarker({
        name: 'H向位移变化量',
        type: 'line',
        data: values('h'),
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2.8 },
      }, 'h'),
    ],
  }
}

function withMaxMarker(series: Record<string, unknown>, key: 'x' | 'y' | 'h') {
  if (maxChangePoint.value.key !== key || !maxChangePoint.value.date) {
    return series
  }
  return {
    ...series,
    markPoint: {
      symbol: 'pin',
      symbolSize: 72,
      label: {
        formatter: () => `${maxChangePoint.value.value.toFixed(1)}mm`,
        color: '#fff',
        fontSize: 12,
        fontWeight: 700,
      },
      itemStyle: {
        color: '#b91c1c',
      },
      data: [
        {
          name: '最大变化点',
          coord: [maxChangePoint.value.date, Number(maxChangePoint.value.value.toFixed(2))],
        },
      ],
    },
  }
}

function renderChart() {
  if (!chartEl.value || !props.rows.length) {
    return
  }
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  }
  chart.setOption(buildOption(), true)
}

watch(
  () => [props.rows, props.title, props.subtitle],
  () => nextTick(renderChart),
  { deep: true },
)

onMounted(() => {
  void nextTick(renderChart)
  if (chartEl.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.report-chart {
  min-width: 920px;
  height: 620px;
  border: 1px solid #d6dde8;
  background: #fff;
}

.chart-canvas {
  width: 100%;
  height: 100%;
}

@media (max-width: 640px) {
  .report-chart {
    min-width: 680px;
    height: 460px;
  }
}
</style>
