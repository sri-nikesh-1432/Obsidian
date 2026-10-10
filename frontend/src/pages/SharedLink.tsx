import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Clock3, Download, FileText, Link2, Lock, Pencil, Save, ShieldOff } from 'lucide-react'
import { api, ApiError, base64ToBlob, triggerDownload } from '../lib/api'
import { expiryLabel, formatBytes, formatDate } from '../lib/format'
import { Badge, Button, Spinner, Textarea } from '../components/ui'

interface ShareMeta {
  document: {
    document_id: string
    filename: string
    mime_type: string
    size_bytes: number
    created_at: string
    encryption: string
  }
  permission: 'viewer' | 'editor'
  expires_at: string
}

export default function SharedLink() {
  const { token = '' } = useParams<{ token: string }>()
  const [meta, setMeta] = useState<ShareMeta | null>(null)
  const [error, setError] = useState<{ title: string; message: string } | null>(null)
  const [content, setContent] = useState<{ url?: string; text?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [isText, setIsText] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api<ShareMeta>(`/s/${encodeURIComponent(token)}`)
      setMeta(data)

      const c = await api<{ content_base64: string; mime_type: string }>(
        `/s/${encodeURIComponent(token)}/content`,
      )
      const ext = data.document.filename.split('.').pop()?.toLowerCase() ?? ''
      if (data.document.mime_type.startsWith('image/')) {
        setContent({ url: URL.createObjectURL(base64ToBlob(c.content_base64, data.document.mime_type)) })
      } else if (data.document.mime_type === 'application/pdf') {
        setContent({ url: URL.createObjectURL(base64ToBlob(c.content_base64, data.document.mime_type)) })
      } else if (data.document.mime_type.startsWith('text/') || ['json', 'csv', 'md', 'log'].includes(ext)) {
        const bytes = Uint8Array.from(atob(c.content_base64), (ch) => ch.charCodeAt(0))
        const t = new TextDecoder().decode(bytes)
        setContent({ text: t })
        setText(t)
        setIsText(true)
      } else {
        setContent(null)
      }
    } catch (err) {
      if (err instanceof ApiError) {
        const titles: Record<string, string> = {
          SHARE_EXPIRED: 'This link has expired',
          SHARE_REVOKED: 'This link is no longer active',
          SHARE_UNAVAILABLE: 'This link is unavailable',
          RATE_LIMITED: 'Too many attempts',
        }
        setError({ title: titles[err.code] ?? 'Access denied', message: err.message })
      } else {
        setError({ title: 'Something went wrong', message: 'The link could not be opened.' })
      }
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    void load()
  }, [load])

  const download = async () => {
    if (!meta) return
    setBusy(true)
    try {
      const c = await api<{ content_base64: string; mime_type: string; filename: string }>(
        `/s/${encodeURIComponent(token)}/content`,
      )
      triggerDownload(c.content_base64, c.mime_type, c.filename)
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Download failed.')
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    setBusy(true)
    try {
      const bytes = new TextEncoder().encode(text)
      let binary = ''
      bytes.forEach((b) => (binary += String.fromCharCode(b)))
      await api(`/s/${encodeURIComponent(token)}/content`, {
        method: 'PUT',
        body: { content_base64: btoa(binary) },
      })
      setContent({ text })
      setEditing(false)
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Save failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen">
      <header className="glass sticky top-0 z-40 border-b border-white/60">
        <div className="max-w-4xl mx-auto px-5 h-16 flex items-center justify-between">
          <span className="text-[13px] font-semibold tracking-[0.3em]">OBSIDIAN</span>
          <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
            <Link2 size={13} className="text-cognac" /> Secure share
          </span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-5 py-10">
        {loading ? (
          <Spinner label="Validating link…" />
        ) : error ? (
          <div className="glass rounded-2xl p-8 text-center max-w-md mx-auto fade-up">
            <div className="w-11 h-11 rounded-2xl bg-danger/10 text-danger mx-auto flex items-center justify-center">
              <ShieldOff size={20} />
            </div>
            <h1 className="mt-4 text-xl font-semibold text-editorial">{error.title}</h1>
            <p className="mt-2 text-sm text-muted">{error.message}</p>
            <p className="text-xs text-faint mt-4">
              Expiry and revocation are enforced server-side — the document itself is untouched.
            </p>
          </div>
        ) : meta ? (
          <div className="fade-up">
            <div className="glass rounded-2xl p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="eyebrow">Shared document</div>
                  <h1 className="mt-1.5 text-xl font-semibold text-editorial break-all">
                    {meta.document.filename}
                  </h1>
                  <div className="mt-2 flex flex-wrap gap-2 text-[13px] text-muted">
                    <span>{formatBytes(meta.document.size_bytes)}</span>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1.5">
                      <Lock size={12} className="text-success" /> {meta.document.encryption}
                    </span>
                    <span>·</span>
                    <span>owner-controlled access</span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <Badge tone="accent">{meta.permission === 'editor' ? 'Editor' : 'Viewer'}</Badge>
                  {meta.expires_at ? (
                    <Badge tone="warning" icon={<Clock3 size={11} />}>
                      {expiryLabel(meta.expires_at)} · {formatDate(meta.expires_at)}
                    </Badge>
                  ) : (
                    <Badge tone="neutral">No expiry</Badge>
                  )}
                </div>
              </div>

              <div className="mt-5 flex flex-wrap gap-2">
                <Button variant="primary" onClick={download} loading={busy}>
                  <Download size={15} /> Download
                </Button>
                {meta.permission === 'editor' && isText && (
                  <Button variant="soft" onClick={() => setEditing((v) => !v)}>
                    <Pencil size={14} /> {editing ? 'Close editor' : 'Edit document'}
                  </Button>
                )}
              </div>
            </div>

            <div className="panel-solid rounded-2xl p-5 mt-4">
              <div className="eyebrow mb-3">Preview</div>
              {editing ? (
                <div>
                  <Textarea rows={16} value={text} onChange={(e) => setText(e.target.value)} className="font-mono text-[13px]" />
                  <div className="flex justify-end gap-2 mt-3">
                    <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                    <Button variant="primary" loading={busy} onClick={save}>
                      <Save size={14} /> Save
                    </Button>
                  </div>
                </div>
              ) : content?.text !== undefined ? (
                <pre className="whitespace-pre-wrap wrap-anywhere text-[13px] leading-relaxed text-graphite bg-ivory-deep/50 rounded-xl p-4 max-h-[560px] overflow-auto scrollbar-thin">
                  {content.text}
                </pre>
              ) : content?.url && meta.document.mime_type === 'application/pdf' ? (
                <iframe title="Preview" src={content.url} className="w-full h-[600px] rounded-xl border hairline" />
              ) : content?.url ? (
                <img src={content.url} alt={meta.document.filename} className="max-h-[520px] mx-auto rounded-xl" />
              ) : (
                <div className="py-12 text-center text-muted text-sm">
                  <FileText size={24} className="mx-auto text-faint" />
                  <p className="mt-3">Preview unavailable — use download to view this file.</p>
                </div>
              )}
            </div>

            <p className="text-xs text-faint text-center mt-6">
              This access was audited by the document owner. The link can stop working at any
              time if the owner revokes it.
            </p>
          </div>
        ) : null}
      </main>
    </div>
  )
}
