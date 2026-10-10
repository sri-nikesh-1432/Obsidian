import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, Clock3, Download, FileText, Pencil, Save, Share2, ShieldCheck,
  Trash2, Unlock, Lock,
} from 'lucide-react'
import { api, ApiError, base64ToBlob, triggerDownload } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { ActivityEvent, DocumentMeta, Share } from '../../lib/types'
import { eventLabel, formatBytes, formatDate, relativeTime } from '../../lib/format'
import {
  Badge, Button, ConfirmDialog, PageHeader, Spinner, Textarea, Toggle,
} from '../../components/ui'
import ShareDialog from '../../components/ShareDialog'
import { useToast } from '../../store/toast'

export default function DocumentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const { user } = useAuth()

  const [doc, setDoc] = useState<DocumentMeta | null>(null)
  const [shares, setShares] = useState<Share[]>([])
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [preview, setPreview] = useState<{ url?: string; text?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [shareOpen, setShareOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    try {
      const data = await api<{ document: DocumentMeta; is_owner: boolean }>(`/documents/${id}`)
      setDoc(data.document)
      const [s, a] = await Promise.allSettled([
        api<{ shares: Share[] }>(`/documents/${id}/shares`),
        api<{ events: ActivityEvent[] }>(`/documents/${id}/activity`),
      ])
      if (s.status === 'fulfilled') setShares(s.value.shares)
      if (a.status === 'fulfilled') setEvents(a.value.events)
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not load the document.')
      navigate('/app/vault')
    } finally {
      setLoading(false)
    }
  }, [id, navigate, toast])

  useEffect(() => {
    void load()
  }, [load])

  // preview (decrypted through the authorized endpoint)
  useEffect(() => {
    if (!doc) return
    let url: string | null = null
    const fetchPreview = async () => {
      try {
        const data = await api<{ content_base64: string; mime_type: string }>(
          `/documents/${doc.document_id}/content`,
        )
        if (doc.mime_type.startsWith('image/')) {
          const blob = base64ToBlob(data.content_base64, doc.mime_type)
          url = URL.createObjectURL(blob)
          setPreview({ url })
        } else if (doc.mime_type === 'application/pdf') {
          const blob = base64ToBlob(data.content_base64, doc.mime_type)
          url = URL.createObjectURL(blob)
          setPreview({ url })
        } else if (doc.mime_type.startsWith('text/') || ['json', 'csv'].includes(doc.extension)) {
          const bytes = Uint8Array.from(atob(data.content_base64), (c) => c.charCodeAt(0))
          const text = new TextDecoder().decode(bytes)
          setPreview({ text: text.slice(0, 20000) })
          setEditText(text)
        } else {
          setPreview(null)
        }
      } catch {
        setPreview(null)
      }
    }
    void fetchPreview()
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [doc?.document_id, doc?.mime_type, doc?.extension]) // eslint-disable-line react-hooks/exhaustive-deps

  const download = async () => {
    if (!doc) return
    try {
      const data = await api<{ content_base64: string; mime_type: string; filename: string }>(
        `/documents/${doc.document_id}/content?download=1`,
      )
      triggerDownload(data.content_base64, data.mime_type, data.filename)
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Download failed.')
    }
  }

  const patch = async (body: Record<string, unknown>, success: string) => {
    try {
      const data = await api<{ document: DocumentMeta }>(`/documents/${id}`, {
        method: 'PATCH',
        body,
      })
      setDoc((prev) => ({ ...prev!, ...data.document }))
      toast.push('success', success)
      void load()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Update failed.')
    }
  }

  const saveEdit = async () => {
    if (!doc) return
    setBusy(true)
    try {
      const bytes = new TextEncoder().encode(editText)
      let binary = ''
      bytes.forEach((b) => (binary += String.fromCharCode(b)))
      await api(`/documents/${doc.document_id}/content`, {
        method: 'PUT',
        body: { content_base64: btoa(binary) },
      })
      toast.push('success', 'Document updated — re-encrypted with a fresh key.')
      setEditing(false)
      void load()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Save failed.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!doc) return
    setBusy(true)
    try {
      await api(`/documents/${doc.document_id}`, { method: 'DELETE' })
      toast.push('success', 'Document deleted and links revoked.')
      navigate('/app/vault')
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Delete failed.')
    } finally {
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  if (loading || !doc) return <Spinner label="Decrypting metadata…" />

  const activeShares = shares.filter((s) => s.status === 'active')

  return (
    <div className="fade-up">
      <button
        onClick={() => navigate('/app/vault')}
        className="flex items-center gap-1.5 text-[13px] text-muted hover:text-cognac-deep transition-colors focus-ring rounded mb-4"
      >
        <ArrowLeft size={14} /> Back to documents
      </button>

      <PageHeader
        title={doc.filename}
        subtitle={`${doc.extension.toUpperCase() || 'FILE'} · ${formatBytes(doc.size_bytes)} · uploaded ${formatDate(doc.created_at)}`}
        actions={
          <>
            {doc.is_text && (
              <Button variant="soft" onClick={() => setEditing((v) => !v)}>
                <Pencil size={14} /> {editing ? 'Close editor' : 'Edit'}
              </Button>
            )}
            <Button variant="soft" onClick={() => setShareOpen(true)}>
              <Share2 size={14} /> Share
            </Button>
            <Button variant="primary" onClick={download}>
              <Download size={14} /> Download
            </Button>
            <Button variant="danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} />
            </Button>
          </>
        }
      />

      <div className="grid lg:grid-cols-3 gap-4">
        {/* preview */}
        <div className="lg:col-span-2 panel-solid rounded-2xl p-4 min-h-[380px]">
          <div className="flex items-center justify-between mb-3">
            <div className="eyebrow">Preview</div>
            <Badge tone="success" icon={<ShieldCheck size={11} />}>Decrypted on request</Badge>
          </div>

          {editing ? (
            <div>
              <Textarea
                rows={16}
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="font-mono text-[13px]"
              />
              <div className="flex justify-end gap-2 mt-3">
                <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                <Button variant="primary" loading={busy} onClick={saveEdit}>
                  <Save size={14} /> Save & re-encrypt
                </Button>
              </div>
            </div>
          ) : preview?.text !== undefined ? (
            <pre className="whitespace-pre-wrap wrap-anywhere text-[13px] leading-relaxed text-graphite bg-ivory-deep/50 rounded-xl p-4 max-h-[520px] overflow-auto scrollbar-thin">
              {preview.text}
            </pre>
          ) : preview?.url && doc.mime_type === 'application/pdf' ? (
            <iframe
              title="PDF preview"
              src={preview.url}
              className="w-full h-[560px] rounded-xl border hairline bg-white"
            />
          ) : preview?.url && doc.mime_type.startsWith('image/') ? (
            <img src={preview.url} alt={doc.filename} className="max-h-[520px] mx-auto rounded-xl" />
          ) : (
            <div className="py-16 text-center text-muted">
              <FileText size={26} className="mx-auto text-faint" />
              <p className="text-sm mt-3">Preview is not available for this file type.</p>
              <Button variant="soft" size="sm" className="mt-4" onClick={download}>
                Download to view
              </Button>
            </div>
          )}
        </div>

        {/* metadata */}
        <div className="space-y-4">
          <div className="panel-solid rounded-2xl p-5">
            <div className="eyebrow">Document details</div>
            <dl className="mt-3 space-y-2.5 text-[13px]">
              {[
                ['Type', doc.mime_type || '—'],
                ['Size', formatBytes(doc.size_bytes)],
                ['Encryption', doc.encryption],
                ['Integrity', doc.integrity || '—'],
                ['Uploaded', formatDate(doc.created_at)],
                ['Modified', formatDate(doc.updated_at)],
                ['Active links', String(activeShares.length)],
                ['RAG status', doc.rag_status || '—'],
              ].map(([k, v]) => (
                <div key={k} className="flex items-start justify-between gap-3">
                  <dt className="text-muted shrink-0">{k}</dt>
                  <dd className="text-right font-medium break-all">{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="panel-solid rounded-2xl p-5 space-y-4">
            <div className="eyebrow">Visibility</div>
            <Toggle
              checked={doc.visibility === 'private'}
              onChange={(v) => patch({ visibility: v ? 'private' : 'public' }, v ? 'Now private' : 'Now public')}
              label={doc.visibility === 'private' ? 'Private document' : 'Public document'}
              description={
                doc.visibility === 'private'
                  ? 'Only you can open it — unless you share it explicitly.'
                  : 'Visible as public content under platform policy.'
              }
            />
            <div className="h-px bg-beige" />
            <Toggle
              checked={doc.profile_visible}
              onChange={(v) => patch({ profile_visible: v }, v ? 'Shown on your profile' : 'Removed from profile')}
              label="Show on my profile"
              description="Faculty and recruiters can open it only when your profile is visible."
            />
            {user?.ai_enabled && (
              <>
                <div className="h-px bg-beige" />
                <Toggle
                  checked={doc.rag_eligible}
                  onChange={(v) => patch({ rag_eligible: v }, v ? 'Queued for indexing' : 'Removed from knowledge base')}
                  label="Personal AI indexing"
                  description="Text content is indexed only inside your own partition."
                />
              </>
            )}
            <div className="flex items-center gap-2 text-[13px] text-muted pt-1">
              {doc.visibility === 'private' ? <Lock size={13} className="text-success" /> : <Unlock size={13} className="text-warning" />}
              {doc.visibility === 'private' ? 'Stored privately' : 'Publicly visible'}
            </div>
          </div>
        </div>
      </div>

      {/* shares + activity */}
      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        <div className="panel-solid rounded-2xl p-5">
          <div className="flex items-center justify-between">
            <div className="eyebrow">Share links</div>
            <Button variant="soft" size="sm" onClick={() => setShareOpen(true)}>Manage</Button>
          </div>
          {shares.length === 0 ? (
            <p className="text-sm text-muted mt-3">No shares yet — this document is yours alone.</p>
          ) : (
            <div className="mt-3 space-y-2">
              {shares.slice(0, 6).map((s) => (
                <div key={s.share_id} className="flex items-center justify-between text-[13px] rounded-xl border hairline bg-white/70 px-3.5 py-2.5">
                  <div className="min-w-0">
                    <div className="font-medium">
                      {s.mode === 'link' ? 'Anyone with link' : s.grantee_email}
                    </div>
                    <div className="text-xs text-faint">
                      {s.permission} · {s.access_count} accesses
                    </div>
                  </div>
                  <Badge tone={s.status === 'active' ? 'success' : s.status === 'expired' ? 'warning' : 'danger'}>
                    {s.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="panel-solid rounded-2xl p-5">
          <div className="eyebrow flex items-center gap-2"><Clock3 size={12} /> Activity</div>
          {events.length === 0 ? (
            <p className="text-sm text-muted mt-3">No recorded events for this document.</p>
          ) : (
            <div className="mt-3 space-y-2.5">
              {events.slice(0, 8).map((e) => (
                <div key={e.event_id} className="flex items-center justify-between text-[13px]">
                  <span className="text-graphite">{eventLabel(e.event_type)}</span>
                  <span className="text-faint">{relativeTime(e.timestamp)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <ShareDialog open={shareOpen} doc={doc} onClose={() => setShareOpen(false)} />
      <ConfirmDialog
        open={confirmDelete}
        danger
        title="Delete document?"
        message="The encrypted object is removed from S3, all share links are revoked, and personal knowledge-base entries are deleted."
        confirmLabel="Delete permanently"
        loading={busy}
        onConfirm={remove}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}
