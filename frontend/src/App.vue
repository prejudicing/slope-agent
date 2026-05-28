<template>
  <div class="chat-page">
    <header class="chat-topbar">
      <h1>高切坡系统智能体</h1>
      <button
        type="button"
        class="topbar-action"
        title="重置页面"
        @click="resetPage"
      >
        <el-icon><Plus /></el-icon>
      </button>
    </header>

    <main class="chat-main">
      <section class="agent-banner">
        <div class="banner-brand">
          <img :src="heroImage" alt="高切坡AI助手" class="brand-icon" />
          <h2>高切坡AI助手</h2>
        </div>
      </section>

      <section v-if="!hasTurns" class="welcome-panel">
        <div class="welcome-bubble">你好，我是高切坡AI助手，请问有什么可以帮你！</div>
        <div class="starter-list">
          <button
            v-for="item in starterQuestions"
            :key="item"
            type="button"
            class="starter-chip"
            @click="useStarter(item)"
          >
            {{ item }}
          </button>
        </div>
      </section>

      <section class="conversation-list">
        <template v-for="entry in feedItems" :key="entry.id">
          <div v-if="entry.kind === 'marker'" class="context-divider">
            <span>{{ entry.text }}</span>
          </div>

          <template v-else>
            <div class="message-row user-row">
              <div class="message-body user-body">
                <div class="speaker-name">{{ isLatestTurn(entry.id) ? '当前提问' : '用户提问' }}</div>
                <div class="message-bubble user-bubble">{{ entry.question }}</div>
              </div>
              <div class="message-avatar user-avatar">我</div>
            </div>

            <div class="message-row assistant-row">
              <img :src="heroImage" alt="高切坡智能体" class="message-avatar assistant-avatar" />
              <div class="message-body assistant-stack">
                <div class="speaker-name">高切坡AI助手</div>
                <div class="assistant-response-frame">
                  <div v-if="entry.loading" class="loading-bubble">
                    <el-icon class="loading-icon is-loading"><Loading /></el-icon>
                    <span class="loading-text">思考中...</span>
                  </div>
                  <button
                    v-if="entry.loading && activeTurnId === entry.id"
                    type="button"
                    class="stop-response-button"
                    @click="stopActiveQuery"
                  >
                    停止响应
                  </button>

                  <el-alert
                    v-if="entry.error"
                    :title="entry.error"
                    type="error"
                    show-icon
                    class="turn-error"
                  />

                  <template v-if="!entry.loading && !entry.error && !isCardResponse(entry)">
                    <div class="message-bubble assistant-bubble assistant-reply-bubble">
                      <div class="assistant-reply-text">
                        {{ entry.summary || '暂时没有可返回的内容。' }}
                      </div>
                      <div v-if="entry.suggestion" class="assistant-suggestion">
                        {{ entry.suggestion }}
                      </div>
                    </div>
                  </template>

                  <template v-else>
                    <SummaryPanel
                      v-if="entry.summary.trim() || (!entry.loading && !entry.error)"
                      :question="entry.question"
                      :summary="entry.summary"
                      :columns="entry.columns"
                      :rows="entry.rows"
                      :total-rows="entry.totalRows"
                      embedded
                    />

                    <ResultPanel
                      v-if="entry.rows.length || entry.totalRows"
                      :columns="entry.columns"
                      :rows="entry.rows"
                      :total-rows="entry.totalRows"
                      embedded
                    />

                    <AttachmentPanel
                      v-if="entry.attachments.length"
                      :attachments="entry.attachments"
                      embedded
                    />
                  </template>
                </div>
              </div>
            </div>
          </template>
        </template>
      </section>
    </main>

    <footer class="composer-wrap">
      <div class="composer-shell">
        <QueryInput
          v-model:question="composerQuestion"
          :loading="loading"
          placeholder="发送消息"
          @clear="clearConversation"
          @submit="handleSubmit"
        />
      </div>
      <div class="footer-copy">高切坡智能查询</div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, Plus } from '@element-plus/icons-vue'
import QueryInput from './components/QueryInput.vue'
import AttachmentPanel from './components/AttachmentPanel.vue'
import ResultPanel from './components/ResultPanel.vue'
import SummaryPanel from './components/SummaryPanel.vue'
import heroImage from './assets/hero.png'
import { streamQuery } from './api/query'
import type { ConversationHistoryTurn, QueryAttachment } from './types/query'

interface QueryTurn {
  id: number
  kind: 'turn'
  question: string
  status: string
  queryType: string
  summary: string
  suggestion: string
  columns: string[]
  rows: Record<string, string>[]
  totalRows: number
  attachments: QueryAttachment[]
  error: string
  loading: boolean
}

interface ContextMarker {
  id: number
  kind: 'marker'
  text: string
}

type FeedItem = QueryTurn | ContextMarker

const composerQuestion = ref('')
const feedItems = ref<FeedItem[]>([])
const activeAbortController = ref<AbortController | null>(null)
const activeTurnId = ref<number | null>(null)
const cancelledTurnIds = ref<Set<number>>(new Set())

const starterQuestions = [
  '对比一下各区县高切坡异常数量',
  '查询渝北区高切坡基本信息',
  '我想知道哪些高切坡处于异常状态，并告诉我属于哪一种异常类型',
  '帮我分析 2024 年预警高切坡的分布情况',
  '查询最近30天的预警专报记录',
]

const loading = computed(() =>
  feedItems.value.some((item) => item.kind === 'turn' && item.loading)
)

const hasTurns = computed(() =>
  feedItems.value.some((item) => item.kind === 'turn')
)

const isCardResponse = (entry: QueryTurn) =>
  ['db_query', 'template_query', 'result_analysis'].includes(entry.queryType)

const isLatestTurn = (id: number) => {
  const turns = feedItems.value.filter((item): item is QueryTurn => item.kind === 'turn')
  if (!turns.length) {
    return false
  }
  return turns[turns.length - 1].id === id
}

const getConversationHistory = (): ConversationHistoryTurn[] => {
  return feedItems.value
    .filter((item): item is QueryTurn => item.kind === 'turn')
    .slice(-4)
    .map((item) => ({
      question: item.question,
      summary: item.summary,
      total_rows: item.totalRows,
    }))
}

const useStarter = (question: string) => {
  if (loading.value) {
    return
  }
  composerQuestion.value = question
  void handleSubmit()
}

const clearConversation = () => {
  if (!feedItems.value.length || loading.value) {
    return
  }

  feedItems.value = [
    {
      id: Date.now(),
      kind: 'marker',
      text: '上下文已清除，重新开始对话',
    },
  ]
  composerQuestion.value = ''
  ElMessage.success('上下文已清除')
}

const resetPage = () => {
  if (loading.value) {
    return
  }
  feedItems.value = []
  composerQuestion.value = ''
  ElMessage.success('页面已重置')
}

const stopActiveQuery = () => {
  if (activeTurnId.value == null) {
    return
  }

  cancelledTurnIds.value.add(activeTurnId.value)
  activeAbortController.value?.abort()

  const turn = feedItems.value.find(
    (item): item is QueryTurn => item.kind === 'turn' && item.id === activeTurnId.value
  )
  if (turn) {
    turn.loading = false
    turn.status = 'cancelled'
    turn.queryType = ''
    turn.summary = '已停止响应。'
    turn.suggestion = ''
    turn.columns = []
    turn.rows = []
    turn.totalRows = 0
    turn.attachments = []
    turn.error = ''
  }

  activeAbortController.value = null
  activeTurnId.value = null
  ElMessage.info('已停止当前响应')
}

const handleSubmit = async () => {
  if (loading.value) {
    return
  }

  const trimmedQuestion = composerQuestion.value.trim()
  if (!trimmedQuestion) {
    return
  }

  const history = getConversationHistory()
  const abortController = new AbortController()
  const turn = reactive<QueryTurn>({
    id: Date.now(),
    kind: 'turn',
    question: trimmedQuestion,
    status: 'loading',
    queryType: '',
    summary: '',
    suggestion: '',
    columns: [],
    rows: [],
    totalRows: 0,
    attachments: [],
    error: '',
    loading: true,
  })

  feedItems.value.push(turn)
  composerQuestion.value = ''
  activeAbortController.value = abortController
  activeTurnId.value = turn.id

  try {
    await streamQuery(
      trimmedQuestion,
      (event) => {
        if (cancelledTurnIds.value.has(turn.id)) {
          return
        }

        if (event.type === 'summary') {
          turn.summary = event.summary || ''
          return
        }

        if (event.type === 'final') {
          const res = event.data
          turn.status = res.status || 'success'
          turn.queryType = res.query_type || ''
          turn.summary = res.summary || res.result || turn.summary
          turn.suggestion = res.suggestion || ''
          turn.columns = res.columns || []
          turn.rows = res.rows || []
          turn.totalRows = res.total_rows || res.rows?.length || 0
          turn.attachments = res.attachments || []
          turn.error = res.error || ''
          return
        }

        if (event.type === 'error') {
          turn.error = event.message
        }
      },
      history,
      {
        signal: abortController.signal,
        isCancelled: () => cancelledTurnIds.value.has(turn.id),
      }
    )
  } catch (err: any) {
    if (cancelledTurnIds.value.has(turn.id) || err?.name === 'AbortError') {
      turn.summary = turn.summary || '已停止响应。'
      turn.error = ''
    } else {
      turn.error = err?.message || '请求失败'
    }
  } finally {
    turn.loading = false
    if (activeTurnId.value === turn.id) {
      activeAbortController.value = null
      activeTurnId.value = null
    }
  }
}
</script>

<style scoped>
.chat-page {
  min-height: 100vh;
  padding: 16px 16px 150px;
  background: #fff;
}

.chat-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1280px;
  margin: 0 auto 18px;
}

.chat-topbar h1 {
  margin: 0;
  color: #161616;
  font-size: 20px;
  font-weight: 600;
  text-align: left;
}

.topbar-action {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #3b3b3b;
  cursor: pointer;
  font-size: 22px;
}

.topbar-action:hover {
  background: #f3f4f8;
}

.chat-main {
  max-width: 1280px;
  margin: 0 auto;
}

.agent-banner {
  margin-bottom: 34px;
}

.banner-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
}

.banner-brand h2 {
  margin: 0;
  color: #111;
  font-size: 30px;
  font-weight: 700;
  text-align: center;
}

.brand-icon {
  width: 52px;
  height: 52px;
  border-radius: 8px;
  object-fit: cover;
}

.welcome-panel {
  display: grid;
  justify-items: center;
  gap: 14px;
  margin-bottom: 26px;
  text-align: center;
}

.welcome-bubble {
  width: min(100%, 1100px);
  padding: 18px 20px;
  border-radius: 8px;
  background: #f3f2fb;
  color: #2f2f2f;
  font-size: 18px;
  line-height: 1.65;
  text-align: left;
}

.starter-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  width: min(100%, 1100px);
}

.starter-chip {
  width: min(100%, 520px);
  padding: 14px 18px;
  border: 1px solid #dbdce2;
  border-radius: 8px;
  background: #fff;
  color: #1f1f1f;
  cursor: pointer;
  font: inherit;
  font-size: 16px;
  text-align: left;
}

.starter-chip:hover {
  background: #f8f8fc;
}

.conversation-list {
  display: grid;
  gap: 22px;
}

.message-row {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.message-avatar {
  flex: 0 0 auto;
  width: 48px;
  height: 48px;
  border-radius: 8px;
}

.assistant-avatar {
  object-fit: cover;
}

.user-avatar {
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, #d6f4ff 0%, #b9dff9 100%);
  color: #1f4a63;
  font-size: 16px;
  font-weight: 700;
}

.message-body {
  flex: 1 1 auto;
  min-width: 0;
}

.speaker-name {
  margin-bottom: 8px;
  color: #555;
  font-size: 16px;
}

.message-bubble {
  border-radius: 8px;
  padding: 18px 20px;
  color: #1f1f1f;
  font-size: 17px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  background: #f3f2fb;
}

.user-row {
  justify-content: flex-end;
}

.user-body {
  max-width: min(100%, 1040px);
  text-align: right;
}

.user-body .speaker-name {
  text-align: left;
}

.user-bubble {
  background: #d7d8ff;
  text-align: left;
}

.assistant-stack {
  display: grid;
  gap: 12px;
}

.assistant-response-frame {
  display: grid;
  gap: 12px;
  padding: 14px;
  border-radius: 8px;
  background: #f3f2fb;
}

.assistant-reply-bubble {
  width: min(100%, 1100px);
}

.assistant-reply-text {
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-suggestion {
  margin-top: 10px;
  color: #5f6675;
  font-size: 14px;
  line-height: 1.6;
}

.loading-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  width: fit-content;
  min-width: 0;
  padding: 14px 16px;
  border-radius: 8px;
  background: #f3f2fb;
}

.loading-icon {
  color: #7f84ef;
  font-size: 16px;
}

.loading-text {
  color: #5e6172;
  font-size: 15px;
}

.stop-response-button {
  width: fit-content;
  min-width: 0;
  margin: 4px auto 0;
  padding: 12px 24px;
  border: 1px solid #d9dbe6;
  border-radius: 8px;
  background: #fff;
  color: #3f4454;
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(22, 28, 45, 0.08);
}

.stop-response-button:hover {
  background: #f8f9fc;
}

.turn-error {
  border-radius: 8px;
}

.context-divider {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #8a8a8a;
  font-size: 14px;
}

.context-divider::before,
.context-divider::after {
  content: '';
  flex: 1 1 auto;
  height: 1px;
  background: #dedee4;
}

.composer-wrap {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  padding: 10px 16px 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0) 0%, #ffffff 38%, #ffffff 100%);
}

.composer-shell {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0;
  border: 0;
  background: transparent;
}

.footer-copy {
  margin-top: 8px;
  color: #9a9a9a;
  font-size: 12px;
  text-align: center;
}

@media (min-width: 1080px) {
  .conversation-list {
    gap: 28px;
  }

  .message-row {
    gap: 18px;
  }

  .message-bubble {
    font-size: 18px;
  }
}

@media (max-width: 640px) {
  .chat-page {
    padding-right: 12px;
    padding-left: 12px;
    padding-bottom: 172px;
  }

  .chat-topbar h1 {
    font-size: 18px;
  }

  .banner-brand h2 {
    font-size: 24px;
  }

  .welcome-bubble,
  .message-bubble {
    padding: 16px;
    font-size: 16px;
  }

  .message-avatar {
    width: 40px;
    height: 40px;
  }

  .speaker-name {
    font-size: 15px;
  }

}
</style>
