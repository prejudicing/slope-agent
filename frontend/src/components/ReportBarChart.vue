<template>
  <div class="report-bar">
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { BarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'

echarts.use([GridComponent, TooltipComponent, BarChart, CanvasRenderer])

const props = defineProps<{
  title: string
  unit?: string
  items: Array<{ name: string; value: number }>
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

const rows = computed(() => props.items.filter((item) => item.name && Number.isFinite(Number(item.value))).slice(0, 8))
const integerUnit = computed(() => ['处', '个', '条'].includes(props.unit || ''))

function formatChartValue(value: number) {
  if (integerUnit.value) {
    return String(Math.round(value))
  }
  return Number(value).toFixed(1)
}

function renderChart() {
  if (!chartEl.value || !rows.value.length) {
    return
  }
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  }
  chart.setOption(
    {
      animation: false,
      backgroundColor: '#ffffff',
      title: {
        text: props.title,
        left: 18,
        top: 14,
        textStyle: {
          color: '#111827',
          fontSize: 17,
          fontWeight: 700,
          fontFamily: 'Microsoft YaHei, SimHei, sans-serif',
        },
      },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: unknown) => `${formatChartValue(Number(value))}${props.unit || ''}`,
      },
      grid: {
        left: 58,
        right: 24,
        top: 64,
        bottom: 46,
      },
      xAxis: {
        type: 'category',
        data: rows.value.map((item) => item.name),
        axisLabel: {
          color: '#334155',
          fontSize: 12,
          interval: 0,
          rotate: rows.value.length > 4 ? 22 : 0,
          fontFamily: 'Microsoft YaHei, SimSun, serif',
        },
        axisLine: { lineStyle: { color: '#6b7280' } },
      },
      yAxis: {
        type: 'value',
        name: props.unit ? `单位：${props.unit}` : '',
        minInterval: integerUnit.value ? 1 : 0,
        axisLabel: {
          color: '#334155',
          fontSize: 13,
          formatter: (value: number) => formatChartValue(value),
          fontFamily: 'Microsoft YaHei, SimSun, serif',
        },
        splitLine: { lineStyle: { color: '#e5edf5' } },
        nameTextStyle: { color: '#374151', fontSize: 12 },
      },
      series: [
        {
          type: 'bar',
          data: rows.value.map((item) => item.value),
          barMaxWidth: 38,
          itemStyle: {
            color: '#2f5597',
            borderRadius: [2, 2, 0, 0],
          },
          label: {
            show: true,
            position: 'top',
            color: '#111827',
            fontSize: 12,
            formatter: (params: any) => `${formatChartValue(Number(params.value))}${props.unit || ''}`,
          },
        },
      ],
    },
    true,
  )
}

watch(() => [props.title, props.unit, props.items], () => nextTick(renderChart), { deep: true })

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
.report-bar {
  height: 300px;
  border: 1px solid #d6dde8;
  background: #fff;
}

.chart-canvas {
  width: 100%;
  height: 100%;
}
</style>
