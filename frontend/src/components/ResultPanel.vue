<template>
  <el-card shadow="never" class="panel-card result-card">
    <template #header>
      <div class="panel-header">
        <span>查询结果</span>
        <span v-if="totalRows" class="row-count">{{ totalRows }} 条</span>
      </div>
    </template>

    <el-empty v-if="!rows.length" description="暂无表格数据" />
    <div v-else-if="totalRows > rows.length" class="result-note">
      当前仅展示前 {{ rows.length }} 条，完整结果共 {{ totalRows }} 条。
    </div>
    <el-table v-if="rows.length" :data="rows" border stripe height="360" class="result-table desktop-table">
      <el-table-column
        v-for="column in columns"
        :key="column"
        :prop="column"
        :label="column"
        min-width="160"
        show-overflow-tooltip
      />
    </el-table>
    <div v-if="rows.length" class="mobile-results">
      <div v-for="(row, index) in rows" :key="index" class="result-item">
        <div class="result-index">第 {{ index + 1 }} 条</div>
        <dl>
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ row[column] || '-' }}</dd>
          </template>
        </dl>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
// columns/rows 来自后端对最后一次成功 SQL 的真实回查结果。
defineProps<{
  columns: string[]
  rows: Record<string, string>[]
  totalRows: number
}>()
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

.row-count {
  color: #5f6f86;
  font-size: 13px;
  font-weight: 400;
}

.result-card :deep(.el-card__body) {
  padding: 0;
  overflow: hidden;
}

.result-note {
  padding: 12px 16px 0;
  color: #5f6f86;
  font-size: 13px;
}

.result-table {
  width: 100%;
}

.mobile-results {
  display: none;
}

@media (max-width: 640px) {
  .desktop-table {
    display: none;
  }

  .mobile-results {
    display: grid;
    gap: 10px;
    max-height: 460px;
    overflow: auto;
    padding: 12px;
  }

  .result-item {
    border: 1px solid #dfe7f2;
    border-radius: 8px;
    background: #fff;
    padding: 12px;
  }

  .result-index {
    margin-bottom: 8px;
    color: #1f2d3d;
    font-size: 14px;
    font-weight: 700;
  }

  dl {
    display: grid;
    grid-template-columns: 90px minmax(0, 1fr);
    gap: 7px 10px;
    margin: 0;
  }

  dt {
    color: #5f6f86;
    font-size: 12px;
  }

  dd {
    min-width: 0;
    margin: 0;
    color: #253044;
    font-size: 12px;
    overflow-wrap: anywhere;
  }
}
</style>
