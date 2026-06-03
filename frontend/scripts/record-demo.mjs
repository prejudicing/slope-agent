import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(__dirname, '..')
const outDir = path.resolve(projectRoot, '..', 'backend', 'generated', 'demo_videos')
const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const appUrl = process.env.DEMO_URL || 'http://127.0.0.1:8000/'

const questions = [
  '生成近期高切坡业务情况简报',
  '近期哪些高切坡值得重点关注',
  '近期哪个区县高切坡风险等级更高',
  '哪些高切坡位移变化量较大？',
]

const profiles = {
  desktop: {
    viewport: { width: 1440, height: 900 },
    videoSize: { width: 1440, height: 900 },
    isMobile: false,
  },
  mobile: {
    viewport: { width: 390, height: 844 },
    videoSize: { width: 390, height: 844 },
    isMobile: true,
  },
}

async function ensureReady(page) {
  await page.goto(appUrl, { waitUntil: 'networkidle', timeout: 60000 })
  await page.waitForTimeout(1800)
}

async function addPointer(page) {
  await page.addStyleTag({
    content: `
      #demo-cursor {
        position: fixed;
        z-index: 999999;
        width: 18px;
        height: 18px;
        border: 3px solid #1d4ed8;
        border-radius: 50%;
        background: rgba(37, 99, 235, 0.18);
        pointer-events: none;
        transform: translate(-50%, -50%);
        transition: left .28s ease, top .28s ease, transform .18s ease;
      }
      #demo-caption {
        position: fixed;
        left: 24px;
        bottom: 22px;
        z-index: 999998;
        padding: 10px 14px;
        border-radius: 6px;
        color: #0f172a;
        background: rgba(255,255,255,.92);
        border: 1px solid rgba(148,163,184,.55);
        box-shadow: 0 8px 24px rgba(15,23,42,.14);
        font: 600 18px/1.5 "Microsoft YaHei", sans-serif;
        max-width: calc(100vw - 48px);
        pointer-events: none;
      }
      @media (max-width: 600px) {
        #demo-caption {
          left: 12px;
          right: 12px;
          bottom: 12px;
          font-size: 14px;
        }
      }
    `,
  })
  await page.evaluate(() => {
    const cursor = document.createElement('div')
    cursor.id = 'demo-cursor'
    cursor.style.left = '50%'
    cursor.style.top = '50%'
    document.body.appendChild(cursor)
    const caption = document.createElement('div')
    caption.id = 'demo-caption'
    caption.textContent = '高切坡智能问答业务演示'
    document.body.appendChild(caption)
  })
}

async function movePointer(page, locator) {
  const box = await locator.boundingBox()
  if (!box) return
  await page.evaluate(({ x, y }) => {
    const cursor = document.querySelector('#demo-cursor')
    if (cursor) {
      cursor.style.left = `${x}px`
      cursor.style.top = `${y}px`
    }
  }, { x: box.x + box.width / 2, y: box.y + box.height / 2 })
  await page.waitForTimeout(350)
}

async function setCaption(page, text) {
  await page.evaluate((value) => {
    const caption = document.querySelector('#demo-caption')
    if (caption) caption.textContent = value
  }, text)
}

async function clickNewConversation(page) {
  const buttons = page.getByRole('button', { name: /新会话/ })
  if (await buttons.count()) {
    const button = buttons.first()
    await movePointer(page, button)
    await button.click()
    await page.waitForTimeout(1100)
  }
}

async function reviewAnswer(page, isMobile) {
  await page.evaluate(() => {
    const list = document.querySelector('.message-list')
    const rows = Array.from(document.querySelectorAll('.message-row.assistant'))
    const target = rows[rows.length - 1]
    if (list && target) {
      list.scrollTo({ top: Math.max(0, target.offsetTop - 12), behavior: 'smooth' })
    }
  })
  await page.waitForTimeout(isMobile ? 3400 : 2400)

  if (!isMobile) {
    await page.evaluate(() => {
      const list = document.querySelector('.message-list')
      if (list) list.scrollBy({ top: 560, behavior: 'smooth' })
    })
    await page.waitForTimeout(6200)
    return
  }

  for (let i = 0; i < 7; i += 1) {
    const moved = await page.evaluate(() => {
      const list = document.querySelector('.message-list')
      const rows = Array.from(document.querySelectorAll('.message-row.assistant'))
      const target = rows[rows.length - 1]
      if (!list || !target) return false
      const targetBottom = target.offsetTop + target.scrollHeight + 48
      const visibleBottom = list.scrollTop + list.clientHeight
      if (visibleBottom >= targetBottom || visibleBottom >= list.scrollHeight - 8) {
        return false
      }
      list.scrollBy({ top: Math.max(260, Math.floor(list.clientHeight * 0.58)), behavior: 'smooth' })
      return true
    })
    if (!moved) break
    await page.waitForTimeout(2800)
  }
}

async function askQuestion(page, question, index, profileName) {
  await setCaption(page, `问题 ${index + 1}：${question}`)
  const input = page.locator('textarea, input[type="text"]').last()
  await input.waitFor({ state: 'visible', timeout: 30000 })
  await movePointer(page, input)
  await input.fill(question)
  await page.waitForTimeout(650)
  const sendButton = page.getByRole('button', { name: /发送/ }).last()
  await movePointer(page, sendButton)
  await sendButton.click()
  await page.waitForTimeout(24000)
  await reviewAnswer(page, profileName === 'mobile')
}

async function record(profileName) {
  await fs.mkdir(outDir, { recursive: true })
  const profile = profiles[profileName]
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromePath,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const context = await browser.newContext({
    viewport: profile.viewport,
    isMobile: profile.isMobile,
    deviceScaleFactor: profile.isMobile ? 2 : 1,
    recordVideo: {
      dir: outDir,
      size: profile.videoSize,
    },
  })
  const page = await context.newPage()
  await ensureReady(page)
  await addPointer(page)
  await page.waitForTimeout(1800)

  for (let i = 0; i < questions.length; i += 1) {
    if (i > 0) {
      await setCaption(page, '新建会话，进入下一项业务问题')
      await clickNewConversation(page)
    }
    await askQuestion(page, questions[i], i, profileName)
  }

  await setCaption(page, '演示结束：支持业务简报、风险研判、专业监测和移动端访问')
  await page.waitForTimeout(3200)
  const video = page.video()
  await context.close()
  await browser.close()
  const sourcePath = await video.path()
  const targetPath = path.join(outDir, `gqp_demo_${profileName}.webm`)
  await fs.copyFile(sourcePath, targetPath)
  await fs.rm(sourcePath, { force: true })
  return targetPath
}

const profileName = process.argv[2] || 'desktop'
if (!profiles[profileName]) {
  console.error(`Unknown profile: ${profileName}`)
  process.exit(1)
}

record(profileName)
  .then((target) => {
    console.log(JSON.stringify({ profile: profileName, video: target }, null, 2))
  })
  .catch((error) => {
    console.error(error)
    process.exit(1)
  })
