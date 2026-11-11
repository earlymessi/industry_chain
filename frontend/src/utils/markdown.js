/** 轻量 Markdown 渲染（标题、列表、加粗、段落），供知识库问答展示。 */

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInline(text) {
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
}

export function renderMarkdown(text) {
  if (!text) return ''
  const lines = String(text).split('\n')
  const parts = []
  let inList = false

  const closeList = () => {
    if (inList) {
      parts.push('</ul>')
      inList = false
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    const trimmed = line.trim()

    if (!trimmed) {
      closeList()
      continue
    }

    if (/^###\s+/.test(trimmed)) {
      closeList()
      parts.push(`<h4>${renderInline(trimmed.replace(/^###\s+/, ''))}</h4>`)
      continue
    }
    if (/^##\s+/.test(trimmed)) {
      closeList()
      parts.push(`<h3>${renderInline(trimmed.replace(/^##\s+/, ''))}</h3>`)
      continue
    }
    if (/^#\s+/.test(trimmed)) {
      closeList()
      parts.push(`<h2>${renderInline(trimmed.replace(/^#\s+/, ''))}</h2>`)
      continue
    }
    if (/^[-*]\s+/.test(trimmed)) {
      if (!inList) {
        parts.push('<ul>')
        inList = true
      }
      parts.push(`<li>${renderInline(trimmed.replace(/^[-*]\s+/, ''))}</li>`)
      continue
    }

    closeList()
    parts.push(`<p>${renderInline(trimmed)}</p>`)
  }

  closeList()
  return parts.join('')
}
