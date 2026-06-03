<template>
  <div class="assistant-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">高</div>
        <div>
          <h1>高切坡智能助手</h1>
          <p>业务数据查询与研判</p>
        </div>
      </div>

      <el-button class="new-chat" type="primary" @click="startNewChat">新建会话</el-button>

      <section class="side-section">
        <div class="side-title">常用场景</div>
        <button
          v-for="item in quickPrompts"
          :key="item"
          class="prompt-item"
          type="button"
          @click="submitPreset(item)"
        >
          {{ item }}
        </button>
      </section>

      <section class="side-section">
        <div class="side-title">历史会话</div>
        <button
          v-for="item in conversations"
          :key="item.id"
          class="history-item"
          :class="{ active: item.id === activeConversationId }"
          type="button"
          @click="activeConversationId = item.id"
        >
          <span class="history-title">{{ item.title }}</span>
          <small>{{ item.time }}</small>
          <i
            class="history-delete"
            role="button"
            tabindex="0"
            aria-label="删除会话"
            title="删除会话"
            @click.stop="deleteConversation(item.id)"
            @keydown.enter.stop.prevent="deleteConversation(item.id)"
            @keydown.space.stop.prevent="deleteConversation(item.id)"
          ></i>
        </button>
      </section>
    </aside>

    <main class="chat-main">
      <header class="chat-header">
        <div>
          <h2>高切坡业务问答</h2>
          <p>连接达梦数据库、监测记录、预警专报与现场照片资源</p>
        </div>
        <div class="header-actions">
          <button type="button" class="header-new-chat" @click="startNewChat">新会话</button>
          <div class="status-pill">
            <span class="status-dot"></span>
            数据服务就绪
          </div>
        </div>
      </header>

      <section ref="messageListRef" class="message-list">
        <div v-if="!activeMessages.length" class="welcome">
          <div class="welcome-badge">GQP Agent</div>
          <h3>今天想查看哪类高切坡业务情况？</h3>
          <p>你可以像使用千问或元宝一样提问，系统会返回报告、表格和可核验的业务数据。</p>
          <div class="welcome-grid">
            <button
              v-for="item in quickPrompts"
              :key="item"
              type="button"
              @click="submitPreset(item)"
            >
              {{ item }}
            </button>
          </div>
        </div>

        <article
          v-for="message in activeMessages"
          :key="message.id"
          class="message-row"
          :class="message.role"
        >
          <div class="avatar">{{ message.role === 'user' ? '我' : '坡' }}</div>
          <div class="message-body">
            <div class="message-meta">
              {{ message.role === 'user' ? '你' : '高切坡智能助手' }}
              <span>{{ message.time }}</span>
            </div>
            <div class="bubble">
              <pre>{{ message.content }}</pre>

              <ResultPanel
                v-if="!message.dashboard && !message.qmqfDashboard && !message.recentBrief && (message.columns?.length || message.rows?.length)"
                :columns="message.columns || []"
                :rows="message.rows || []"
                :total-rows="message.totalRows || 0"
              />
              <AttachmentPanel
                v-if="message.attachments?.length"
                :attachments="message.attachments || []"
                embedded
              />
              <DisplacementDashboard
                v-if="message.dashboard"
                class="message-dashboard"
              />
              <QmqfAbnormalDashboard
                v-if="message.qmqfDashboard"
                class="message-dashboard"
              />
              <RecentSlopeBrief
                v-if="message.recentBrief"
                class="message-dashboard"
              />
              <div v-if="message.followupText" class="followup-panel">
                <span>{{ message.followupText }}</span>
                <button type="button" @click="submitPreset(message.followupPrompt || message.followupText)">
                  继续生成
                </button>
              </div>
            </div>
          </div>
        </article>

        <article v-if="loading" class="message-row assistant">
          <div class="avatar">坡</div>
          <div class="message-body">
            <div class="message-meta">高切坡智能助手 <span>正在处理</span></div>
            <div class="bubble loading-bubble">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>{{ progressText }}</span>
            </div>
          </div>
        </article>
      </section>

      <footer class="composer">
        <QueryInput
          v-model:question="question"
          :loading="loading"
          @submit="handleSubmit"
        />
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import DisplacementDashboard from './components/DisplacementDashboard.vue'
import AttachmentPanel from './components/AttachmentPanel.vue'
import QueryInput from './components/QueryInput.vue'
import QmqfAbnormalDashboard from './components/QmqfAbnormalDashboard.vue'
import RecentSlopeBrief from './components/RecentSlopeBrief.vue'
import ResultPanel from './components/ResultPanel.vue'
import { streamQuery } from './api/query'
import type { QueryAttachment } from './types/query'

type ChatMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  time: string
  sql?: string
  columns?: string[]
  rows?: Record<string, string>[]
  totalRows?: number
  attachments?: QueryAttachment[]
  dashboard?: boolean
  qmqfDashboard?: boolean
  recentBrief?: boolean
  followupText?: string
  followupPrompt?: string
}

type Conversation = {
  id: number
  title: string
  time: string
  messages: ChatMessage[]
}

const quickPrompts = [
  '生成近期高切坡业务情况简报',
  '近期群测群防监测情况',
  '近期专业监测情况',
  '典型破坏状态下的高切坡现状照片',
]

const STORAGE_KEY = 'gqp-business-chat-history-v1'
const MAX_STORED_CONVERSATIONS = 12
const MAX_STORED_MESSAGES = 24
const MAX_STORED_ROWS = 20
const MAX_STORED_COLUMNS = 12

const conversations = ref<Conversation[]>([
  {
    id: 1,
    title: '高切坡业务问答',
    time: '当前',
    messages: [],
  },
])
const activeConversationId = ref(1)
const question = ref('')
const loading = ref(false)
const progressText = ref('正在理解问题并检索业务数据')
const messageListRef = ref<HTMLElement | null>(null)
let messageId = 1

const activeConversation = computed(() => {
  return conversations.value.find((item) => item.id === activeConversationId.value) || conversations.value[0]
})

const activeMessages = computed(() => activeConversation.value.messages)

const normalizeConversation = (conversation: Conversation): Conversation => ({
  id: Number(conversation.id) || Date.now(),
  title: String(conversation.title || '高切坡业务问答').slice(0, 30),
  time: String(conversation.time || ''),
  messages: (conversation.messages || []).slice(-MAX_STORED_MESSAGES).map((message) => ({
    id: Number(message.id) || Date.now(),
    role: message.role === 'assistant' ? 'assistant' : 'user',
    content: String(message.content || ''),
    time: String(message.time || ''),
    columns: (message.columns || []).slice(0, MAX_STORED_COLUMNS),
    rows: (message.rows || []).slice(0, MAX_STORED_ROWS),
    totalRows: Number(message.totalRows || 0),
    attachments: message.attachments || [],
    dashboard: Boolean(message.dashboard),
    qmqfDashboard: Boolean(message.qmqfDashboard),
    recentBrief: Boolean(message.recentBrief),
    followupText: message.followupText || '',
    followupPrompt: message.followupPrompt || '',
  })),
})

const trimConversations = (items: Conversation[]) => {
  const meaningful = items
    .map(normalizeConversation)
    .filter((item, index) => index === 0 || item.messages.length || item.title !== '新的业务会话')
  return meaningful.slice(0, MAX_STORED_CONVERSATIONS)
}

const saveConversations = () => {
  try {
    const payload = {
      activeConversationId: activeConversationId.value,
      conversations: trimConversations(conversations.value),
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch {
    // 本地存储容量不足时不影响当前会话使用。
  }
}

const loadConversations = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return
    }
    const payload = JSON.parse(raw)
    const stored = trimConversations(payload?.conversations || [])
    if (!stored.length) {
      return
    }
    conversations.value = stored
    const activeId = Number(payload?.activeConversationId)
    activeConversationId.value = stored.some((item) => item.id === activeId) ? activeId : stored[0].id
    const maxMessageId = stored.flatMap((item) => item.messages).reduce((max, message) => Math.max(max, message.id), 0)
    messageId = Math.max(messageId, maxMessageId + 1)
  } catch {
    localStorage.removeItem(STORAGE_KEY)
  }
}

const nowTime = () => {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

const scrollToBottom = async () => {
  await nextTick()
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

const scrollToLatestAssistantStart = async () => {
  await nextTick()
  const list = messageListRef.value
  if (!list) {
    return
  }
  const rows = list.querySelectorAll<HTMLElement>('.message-row.assistant')
  const latest = rows[rows.length - 1]
  if (!latest) {
    list.scrollTop = list.scrollHeight
    return
  }
  list.scrollTo({
    top: Math.max(0, latest.offsetTop - 12),
    behavior: 'smooth',
  })
}

const startNewChat = () => {
  const id = Date.now()
  conversations.value.unshift({
    id,
    title: '新的业务会话',
    time: '刚刚',
    messages: [],
  })
  activeConversationId.value = id
  question.value = ''
  saveConversations()
}

const deleteConversation = (id: number) => {
  const next = conversations.value.filter((item) => item.id !== id)
  if (!next.length) {
    const newId = Date.now()
    conversations.value = [
      {
        id: newId,
        title: '新的业务会话',
        time: '刚刚',
        messages: [],
      },
    ]
    activeConversationId.value = newId
    question.value = ''
    saveConversations()
    return
  }
  conversations.value = next
  if (activeConversationId.value === id) {
    activeConversationId.value = next[0].id
  }
  saveConversations()
}

const submitPreset = (value: string) => {
  question.value = value
  void handleSubmit()
}

const setConversationTitle = (text: string) => {
  const title = text.length > 18 ? `${text.slice(0, 18)}...` : text
  activeConversation.value.title = title
  activeConversation.value.time = nowTime()
}

const splitFollowup = (value: string) => {
  const text = String(value || '').trim()
  const patterns = [
    /\n\n(需要我继续[^？?]*[？?])\s*$/u,
    /\n\n(需要我给出[^？?]*[？?])\s*$/u,
    /\n\n(是否需要我[^？?]*[？?])\s*$/u,
  ]
  for (const pattern of patterns) {
    const match = text.match(pattern)
    if (match) {
      const followupText = match[1].trim()
      return {
        content: text.slice(0, match.index).trim(),
        followupText,
        followupPrompt: buildFollowupPrompt(followupText),
      }
    }
  }
  return { content: text, followupText: '', followupPrompt: '' }
}

const buildFollowupPrompt = (value: string) => {
  return value
    .replace(/^需要我继续/, '请继续')
    .replace(/^需要我给出/, '请给出')
    .replace(/^是否需要我/, '请')
    .replace(/[？?]\s*$/, '')
}

const applyAssistantContent = (message: ChatMessage, value: string) => {
  const parsed = splitFollowup(value)
  message.content = parsed.content || value
  message.followupText = parsed.followupText
  message.followupPrompt = parsed.followupPrompt
}

const setFollowup = (message: ChatMessage, text: string) => {
  if (message.followupText || !text) {
    return
  }
  message.followupText = text
  message.followupPrompt = buildFollowupPrompt(text)
}

const ensureBusinessFollowup = (message: ChatMessage, suggestion?: string | null) => {
  if (message.followupText) {
    return
  }
  const content = message.content || ''
  if (/^抱歉|暂时只能|不属于/.test(content)) {
    if (suggestion) {
      setFollowup(message, `需要我继续按高切坡业务范围重新组织问题吗？`)
    }
    return
  }
  if (message.recentBrief) {
    setFollowup(message, '需要我继续生成按区县展开的明细清单、现场复核对象或可下载的业务简报吗？')
    return
  }
  if (message.dashboard) {
    setFollowup(message, '需要我继续给出具体高切坡的监测点年度位移曲线、月度变化表或稳定性评价吗？')
    return
  }
  if (message.qmqfDashboard) {
    setFollowup(message, '需要我继续生成近期群测群防异常复核清单吗？')
    return
  }
  if (message.rows?.length || message.columns?.length) {
    setFollowup(message, '需要我继续按区县、编号、监测类型或时间范围进一步展开明细吗？')
    return
  }
  if (content.includes('风险') || content.includes('异常') || content.includes('预警')) {
    setFollowup(message, '需要我继续给出风险对象清单、区县排序或处置建议吗？')
    return
  }
  if (content.includes('专业监测') || content.includes('位移') || content.includes('曲线')) {
    setFollowup(message, '需要我继续给出监测点曲线、年度位移变化表或稳定性评价吗？')
    return
  }
  if (content.includes('群测群防') || content.includes('现场照片')) {
    setFollowup(message, '需要我继续给出现场异常照片、细项异常记录或复核建议清单吗？')
    return
  }
  if (content.includes('高切坡')) {
    setFollowup(message, '需要我继续给出高切坡明细、监测情况或现场复核对象吗？')
  }
}

const handleSubmit = async () => {
  const text = question.value.trim()
  if (!text || loading.value) {
    return
  }

  const userMessage: ChatMessage = {
    id: messageId++,
    role: 'user',
    content: text,
    time: nowTime(),
  }
  activeConversation.value.messages.push(userMessage)
  setConversationTitle(text)
  question.value = ''
  loading.value = true
  progressText.value = '正在理解问题并检索业务数据'
  await scrollToBottom()

  const assistantMessage: ChatMessage = {
    id: messageId++,
    role: 'assistant',
    content: '已收到问题，正在生成查询报告...',
    time: nowTime(),
    columns: [],
    rows: [],
    totalRows: 0,
    attachments: [],
  }

  try {
    await streamQuery(text, (event) => {
      if (event.type === 'progress') {
        progressText.value = event.message || '正在处理'
        return
      }

      if (event.type === 'sql') {
        return
      }

      if (event.type === 'summary') {
        applyAssistantContent(assistantMessage, event.summary || assistantMessage.content)
        return
      }

      if (event.type === 'final') {
        const res = event.data
        applyAssistantContent(assistantMessage, res.summary || res.result || '本次查询已完成，但没有生成文字报告。')
        assistantMessage.columns = res.columns || []
        assistantMessage.rows = res.rows || []
        assistantMessage.totalRows = res.total_rows || res.rows?.length || 0
        assistantMessage.attachments = res.attachments || []
        assistantMessage.dashboard = Boolean(
          res.columns?.includes('displacement_chart_url') || res.columns?.includes('displacement_dashboard_marker')
        )
        assistantMessage.qmqfDashboard = Boolean(res.columns?.includes('qmqf_dashboard_marker'))
        assistantMessage.recentBrief = Boolean(res.columns?.includes('recent_slope_brief_marker'))
        ensureBusinessFollowup(assistantMessage, res.suggestion)
        if (res.error) {
          assistantMessage.content = `${assistantMessage.content}\n\n提示：${res.error}`
        }
        return
      }

      if (event.type === 'error') {
        assistantMessage.content = `查询失败：${event.message}`
      }
    })
  } catch (err: any) {
    assistantMessage.content = err?.message || '请求失败，请检查后端服务是否启动。'
  } finally {
    activeConversation.value.messages.push(assistantMessage)
    loading.value = false
    saveConversations()
    await scrollToLatestAssistantStart()
  }
}

onMounted(() => {
  loadConversations()
})

watch(
  conversations,
  () => {
    saveConversations()
  },
  { deep: true },
)

watch(activeConversationId, () => {
  saveConversations()
})
</script>

<style scoped>
.assistant-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  height: 100vh;
  height: 100dvh;
  min-height: 620px;
  background: #f6f7fb;
  color: #1f2937;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
  padding: 18px;
  border-right: 1px solid #e4e8ef;
  background: #ffffff;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 8px;
  background: #1b5cff;
  color: #fff;
  font-weight: 800;
}

.brand h1 {
  margin: 0;
  font-size: 18px;
}

.brand p,
.chat-header p,
.welcome p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 13px;
}

.new-chat {
  width: 100%;
}

.side-section {
  display: grid;
  gap: 8px;
}

.side-title {
  color: #667085;
  font-size: 12px;
}

.prompt-item,
.history-item,
.welcome-grid button {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f5f7fb;
  color: #27364a;
  cursor: pointer;
  font: inherit;
  line-height: 1.45;
  padding: 10px 12px;
  text-align: left;
}

.prompt-item:hover,
.history-item:hover,
.history-item.active,
.welcome-grid button:hover {
  border-color: #cbd8ff;
  background: #eef3ff;
}

.history-item {
  display: grid;
  gap: 4px;
}

.history-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-delete {
  position: absolute;
  right: 8px;
  top: 8px;
  display: none;
  width: 22px;
  height: 22px;
  border: 1px solid #d7deea;
  border-radius: 6px;
  background: #fff;
  color: #667085;
}

.history-delete::before,
.history-delete::after {
  position: absolute;
  left: 10px;
  top: 5px;
  width: 1.5px;
  height: 10px;
  border-radius: 999px;
  background: currentColor;
  content: '';
}

.history-delete::before {
  transform: rotate(45deg);
}

.history-delete::after {
  transform: rotate(-45deg);
}

.history-item {
  position: relative;
}

.history-item:hover .history-delete,
.history-item:focus-within .history-delete {
  display: block;
}

.history-delete:hover {
  border-color: #fda29b;
  color: #b42318;
}

.history-item small {
  color: #8a96a8;
}

.chat-main {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  height: 100vh;
  height: 100dvh;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 28px;
  border-bottom: 1px solid #e4e8ef;
  background: rgba(255, 255, 255, 0.92);
}

.chat-header h2 {
  margin: 0;
  font-size: 20px;
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.header-new-chat {
  border: 1px solid #c9d7f8;
  border-radius: 8px;
  background: #fff;
  color: #1b5cff;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  padding: 8px 12px;
}

.header-new-chat:hover {
  background: #eef3ff;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  border: 1px solid #d9e3f5;
  border-radius: 999px;
  background: #fff;
  color: #3d4f6a;
  font-size: 13px;
  padding: 8px 12px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #17b26a;
}

.message-list {
  min-width: 0;
  overflow: auto;
  padding: 28px;
}

.welcome {
  max-width: 1180px;
  margin: 3vh auto 0;
  text-align: center;
}

.welcome-badge {
  display: inline-flex;
  border: 1px solid #dbe5ff;
  border-radius: 999px;
  background: #fff;
  color: #1b5cff;
  font-size: 13px;
  padding: 6px 12px;
}

.welcome h3 {
  margin: 18px 0 0;
  font-size: 30px;
  letter-spacing: 0;
}

.welcome-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 24px;
}

.message-row {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 12px;
  max-width: 980px;
  margin: 0 auto 22px;
}

.message-row.user {
  grid-template-columns: minmax(0, 1fr) 38px;
}

.message-row.user .avatar {
  grid-column: 2;
  background: #1b5cff;
}

.message-row.user .message-body {
  grid-column: 1;
  grid-row: 1;
  justify-self: end;
}

.avatar {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 8px;
  background: #0f766e;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
}

.message-body {
  min-width: 0;
  width: min(100%, 860px);
}

.message-meta {
  display: flex;
  gap: 10px;
  margin-bottom: 7px;
  color: #667085;
  font-size: 12px;
}

.bubble {
  border: 1px solid #e4e8ef;
  border-radius: 8px;
  background: #fff;
  padding: 16px;
  box-shadow: 0 10px 24px rgba(23, 35, 58, 0.05);
}

.message-row.user .bubble {
  background: #1b5cff;
  color: #fff;
}

.bubble pre {
  margin: 0;
  color: inherit;
  font-family: Arial, "Microsoft YaHei", sans-serif;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.loading-bubble {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #3d4f6a;
}

.sql-card {
  margin-top: 14px;
  border: 1px solid #e4e8ef;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px;
}

.card-title {
  margin-bottom: 8px;
  color: #475467;
  font-size: 13px;
  font-weight: 700;
}

.sql-card code {
  display: block;
  overflow: auto;
  color: #344054;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.message-dashboard {
  margin-top: 14px;
}

.followup-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  border: 1px solid #cfe0ff;
  border-radius: 8px;
  background: #f7faff;
  color: #27364a;
  padding: 12px;
}

.followup-panel span {
  min-width: 0;
  font-size: 13px;
  line-height: 1.6;
}

.followup-panel button {
  flex: 0 0 auto;
  border: 1px solid #1b5cff;
  border-radius: 6px;
  background: #1b5cff;
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  padding: 7px 12px;
}

.followup-panel button:hover {
  background: #174ee5;
}

.composer {
  padding: 16px 28px 22px;
  border-top: 1px solid #e4e8ef;
  background: rgba(246, 247, 251, 0.96);
}

@media (max-width: 860px) {
  .assistant-shell {
    grid-template-columns: 1fr;
    min-height: 100dvh;
  }

  .sidebar {
    display: none;
  }

  .chat-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
    padding: 16px;
  }

  .header-actions {
    justify-content: space-between;
    width: 100%;
  }

  .message-list {
    padding: 18px 12px;
  }

  .welcome {
    margin-top: 4vh;
  }

  .welcome h3 {
    font-size: 24px;
  }

  .welcome-grid {
    grid-template-columns: 1fr;
  }

  .composer {
    padding: 12px;
  }
}

@media (max-width: 640px) {
  .chat-header h2 {
    font-size: 18px;
  }

  .chat-header p {
    display: none;
  }

  .status-pill {
    padding: 6px 10px;
  }

  .header-new-chat {
    padding: 6px 10px;
  }

  .message-row,
  .message-row.user {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
    max-width: 100%;
    margin-bottom: 16px;
  }

  .message-list {
    padding: 12px;
  }

  .message-row .avatar {
    display: none;
  }

  .message-row.user .avatar {
    grid-column: 1;
  }

  .message-row.user .message-body {
    grid-column: 1;
    justify-self: stretch;
  }

  .message-body {
    width: 100%;
  }

  .message-row.user .bubble {
    margin-left: auto;
  }

  .avatar {
    width: 32px;
    height: 32px;
    font-size: 12px;
  }

  .bubble {
    padding: 12px;
  }

  .message-meta {
    flex-wrap: wrap;
  }

  .followup-panel {
    align-items: stretch;
    flex-direction: column;
  }

  .followup-panel button {
    width: 100%;
  }
}
</style>
