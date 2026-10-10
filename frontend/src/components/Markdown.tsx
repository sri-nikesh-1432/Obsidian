import type { ReactNode } from 'react'

/**
 * A deliberately small markdown renderer for assistant answers: headings,
 * bullet/numbered lists, fenced code blocks and inline **bold** / *italic* /
 * `code`. No dependency, no raw HTML — text is rendered as text.
 */

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let last = 0
  let match: RegExpExecArray | null
  let i = 0
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-i${i++}`
    if (token.startsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      nodes.push(
        <code key={key} className="rounded bg-ivory-deep px-1.5 py-0.5 text-[12.5px] font-mono text-cognac-deep">
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    }
    last = match.index + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let code: string[] | null = null
  let paragraph: string[] = []

  const flushList = (key: string) => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    blocks.push(
      <Tag
        key={key}
        className={`my-2 space-y-1 pl-5 ${list.ordered ? 'list-decimal' : 'list-disc'}`}
      >
        {list.items.map((it, idx) => (
          <li key={idx}>{renderInline(it, `${key}-${idx}`)}</li>
        ))}
      </Tag>,
    )
    list = null
  }

  const flushParagraph = (key: string) => {
    if (!paragraph.length) return
    blocks.push(
      <p key={key} className="my-2 leading-relaxed">
        {renderInline(paragraph.join(' '), key)}
      </p>,
    )
    paragraph = []
  }

  lines.forEach((raw, index) => {
    const line = raw.trimEnd()
    const key = `b${index}`

    if (line.trim().startsWith('```')) {
      if (code === null) {
        flushParagraph(key)
        flushList(key)
        code = []
      } else {
        blocks.push(
          <pre key={key} className="my-3 overflow-auto rounded-xl bg-charcoal/95 p-3.5 text-[12.5px] leading-relaxed text-[#f4efe5] scrollbar-thin">
            <code>{code.join('\n')}</code>
          </pre>,
        )
        code = null
      }
      return
    }
    if (code !== null) {
      code.push(raw)
      return
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      flushParagraph(key)
      flushList(key)
      const level = heading[1].length
      const size = level === 1 ? 'text-base' : level === 2 ? 'text-[15px]' : 'text-sm'
      blocks.push(
        <div key={key} className={`mt-3 mb-1 font-semibold text-editorial ${size}`}>
          {renderInline(heading[2], key)}
        </div>,
      )
      return
    }

    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+\.\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      flushParagraph(key)
      const ordered = Boolean(numbered)
      if (!list || list.ordered !== ordered) {
        flushList(key)
        list = { ordered, items: [] }
      }
      list.items.push((bullet ?? numbered)![1])
      return
    }

    if (!line.trim()) {
      flushParagraph(key)
      flushList(key)
      return
    }
    paragraph.push(line.trim())
  })

  flushParagraph('final')
  flushList('final')

  return <div className="text-sm">{blocks}</div>
}
