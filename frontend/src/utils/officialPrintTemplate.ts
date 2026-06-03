export type PrintStat = {
  label: string
  value: string
}

export type PrintPhoto = {
  url: string
  label?: string
}

export type PrintObject = {
  title: string
  tag: string
  desc?: string
  body?: string
  photos?: PrintPhoto[]
}

export type OfficialPrintOptions = {
  title: string
  meta: string
  summaryParagraphs: string[]
  stats?: PrintStat[]
  objectsTitle: string
  objects: PrintObject[]
  conclusionTitle?: string
  conclusionParagraphs?: string[]
}

export function buildOfficialPrintHtml(options: OfficialPrintOptions) {
  const generatedOn = new Date().toLocaleDateString('zh-CN')
  const stats = options.stats || []
  const objects = options.objects || []
  const conclusionTitle = options.conclusionTitle || '三、工作建议'
  const conclusionParagraphs = options.conclusionParagraphs || []

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(options.title)}</title>
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
      grid-template-columns: repeat(${Math.min(Math.max(stats.length, 1), 3)}, 1fr);
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
      font-family: "SimHei", "黑体", sans-serif;
      font-size: 22px;
      line-height: 1.45;
    }
    .summary span {
      color: #374151;
      font-size: 14px;
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
      line-height: 1.55;
    }
    .tag {
      display: inline-block;
      margin-bottom: 8px;
      border: 1px solid #b91c1c;
      color: #b91c1c;
      font-family: "SimHei", "黑体", sans-serif;
      font-size: 16px;
      line-height: 1.5;
      padding: 2px 8px;
    }
    .desc {
      margin: 0 0 8px;
      color: #374151;
      text-indent: 0;
    }
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
      height: 175px;
      object-fit: cover;
      border: 1px solid #d1d5db;
    }
    figcaption {
      color: #4b5563;
      font-size: 13px;
      line-height: 1.6;
      text-align: center;
    }
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
    <h1>${escapeHtml(options.title)}</h1>
    <div class="meta">${escapeHtml(options.meta)}&nbsp;&nbsp;&nbsp;&nbsp;生成日期：${escapeHtml(generatedOn)}</div>
    <section>
      <h2>一、总体情况</h2>
      ${options.summaryParagraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join('')}
      ${stats.length ? `<div class="summary">${stats.map((item) => `
        <div><span>${escapeHtml(item.label)}</span><b>${escapeHtml(item.value)}</b></div>
      `).join('')}</div>` : ''}
    </section>
    <section>
      <h2>${escapeHtml(options.objectsTitle)}</h2>
      ${objects.map((item) => `
        <article class="object">
          <h3>${escapeHtml(item.title)}</h3>
          <span class="tag">${escapeHtml(item.tag)}</span>
          ${item.desc ? `<p class="desc">${escapeHtml(item.desc)}</p>` : ''}
          ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ''}
          ${item.photos?.length ? `<div class="photos">${item.photos.map((photo, index) => `
            <figure>
              <img src="${escapeAttr(photo.url)}" alt="${escapeAttr(photo.label || `现场照片 ${index + 1}`)}" />
              <figcaption>${escapeHtml(photo.label || `现场照片 ${index + 1}`)}</figcaption>
            </figure>
          `).join('')}</div>` : ''}
        </article>
      `).join('')}
    </section>
    ${conclusionParagraphs.length ? `<section>
      <h2>${escapeHtml(conclusionTitle)}</h2>
      ${conclusionParagraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join('')}
    </section>` : ''}
    <div class="print-tip">请在弹出的打印窗口中选择“另存为 PDF”。</div>
  </main>
</body>
</html>`
}

export function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function escapeAttr(value: unknown) {
  return escapeHtml(value).replace(/`/g, '&#96;')
}
