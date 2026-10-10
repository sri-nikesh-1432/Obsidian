import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Download, FileText, FileSpreadsheet, FileImage, File, Link2, Lock, MoreHorizontal,
  Unlock, UserCheck,
} from 'lucide-react'
import type { DocumentMeta } from '../lib/types'
import { formatBytes, formatDateShort } from '../lib/format'
import { Badge, ConfirmDialog } from './ui'
import { api, triggerDownload } from '../lib/api'
import { useToast } from '../store/toast'

export function fileIcon(mime: string, ext: string) {
  if (mime === 'application/pdf') return FileText
  if (mime.startsWith('image/')) return FileImage
  if (['csv', 'xlsx', 'json'].includes(ext)) return FileSpreadsheet
  return File
}

interface Props {
  doc: DocumentMeta
  onChanged: () => void
  onShare: (doc: DocumentMeta) => void
}

export default function DocumentCard({ doc, onChanged, onShare }: Props) {
  const navigate = useNavigate()
  const toast = useToast()
  const [menu, setMenu] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(doc.filename)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const Icon = fileIcon(doc.mime_type, doc.extension)

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const rename = async () => {
    if (!name.trim() || name === doc.filename) {
      setRenaming(false)
      return
    }
    try {
      await api(`/documents/${doc.document_id}`, { method: 'PATCH', body: { filename: name.trim() } })
      toast.push('success', 'Document renamed.')
      onChanged()
    } catch (err: any) {
      toast.push('error', err?.message ?? 'Rename failed.')
    }
    setRenaming(false)
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api(`/documents/${doc.document_id}`, { method: 'DELETE' })
      toast.push('success', 'Document deleted and its links revoked.')
      onChanged()
    } catch (err: any) {
      toast.push('error', err?.message ?? 'Delete failed.')
    } finally {
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  const download = async () => {
    try {
      const data = await api<{ content_base64: string; mime_type: string; filename: string }>(
        `/documents/${doc.document_id}/content?download=1`,
      )
      triggerDownload(data.content_base64, data.mime_type, data.filename)
    } catch (err: any) {
      toast.push('error', err?.message ?? 'Download failed.')
    }
  }

  return (
    <>
      <div className="panel-solid rounded-2xl p-4 group hover:shadow-[var(--shadow-lift)] transition-shadow relative">
        <div className="flex items-start justify-between gap-2">
          <button
            onClick={() => navigate(`/app/vault/${doc.document_id}`)}
            className="flex-1 text-left focus-ring rounded-lg"
          >
            <div className="w-10 h-10 rounded-xl bg-ivory-deep flex items-center justify-center text-cognac group-hover:bg-cognac/10 transition-colors">
              <Icon size={17} strokeWidth={1.8} />
            </div>
            <div className="mt-3 text-sm font-medium leading-snug break-words line-clamp-2">
              {doc.filename}
            </div>
            <div className="text-xs text-faint mt-1">
              {doc.extension.toUpperCase() || 'FILE'} · {formatBytes(doc.size_bytes)} · {formatDateShort(doc.created_at)}
            </div>
          </button>

          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setMenu((v) => !v)}
              className="text-faint hover:text-graphite rounded-md p-1.5 focus-ring opacity-60 group-hover:opacity-100 transition-opacity"
              aria-label="Document actions"
            >
              <MoreHorizontal size={16} />
            </button>
            {menu && (
              <div className="absolute right-0 mt-1 w-44 glass rounded-xl p-1.5 z-30 fade-up text-sm">
                <button className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/80 transition-colors" onClick={() => { setMenu(false); navigate(`/app/vault/${doc.document_id}`) }}>
                  Details
                </button>
                <button className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/80 transition-colors" onClick={() => { setMenu(false); download() }}>
                  Download
                </button>
                <button className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/80 transition-colors" onClick={() => { setMenu(false); setRenaming(true) }}>
                  Rename
                </button>
                <button className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/80 transition-colors" onClick={() => { setMenu(false); onShare(doc) }}>
                  Share
                </button>
                <div className="h-px bg-beige/70 my-1" />
                <button className="w-full text-left px-3 py-2 rounded-lg text-danger hover:bg-danger/5 transition-colors" onClick={() => { setMenu(false); setConfirmDelete(true) }}>
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {doc.visibility === 'private' ? (
            <Badge tone="neutral" icon={<Lock size={11} />}>Private</Badge>
          ) : (
            <Badge tone="info" icon={<Unlock size={11} />}>Public</Badge>
          )}
          {doc.profile_visible && <Badge tone="accent" icon={<UserCheck size={11} />}>On profile</Badge>}
          {doc.active_share_count > 0 && (
            <Badge tone="success" icon={<Link2 size={11} />}>{doc.active_share_count} active</Badge>
          )}
          {doc.rag_status === 'indexed' && <Badge tone="info">Indexed</Badge>}
        </div>

        <div className="mt-3 pt-3 border-t hairline flex items-center justify-between">
          <button
            onClick={() => navigate(`/app/vault/${doc.document_id}`)}
            className="text-[13px] text-graphite hover:text-cognac-deep transition-colors focus-ring rounded"
          >
            Open
          </button>
          <div className="flex items-center gap-1">
            <button onClick={() => onShare(doc)} className="btn btn-ghost btn-sm focus-ring">
              Share
            </button>
            <button onClick={download} className="btn btn-soft btn-sm focus-ring" title="Download">
              <Download size={13} />
            </button>
          </div>
        </div>

        {renaming && (
          <div className="absolute inset-0 bg-warm/95 backdrop-blur-sm rounded-2xl p-4 flex flex-col justify-center gap-3 z-20">
            <div className="eyebrow">Rename document</div>
            <input
              autoFocus
              className="field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && rename()}
              maxLength={180}
            />
            <div className="flex gap-2 justify-end">
              <button className="btn btn-ghost btn-sm" onClick={() => { setName(doc.filename); setRenaming(false) }}>Cancel</button>
              <button className="btn btn-primary btn-sm" onClick={rename}>Save</button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        danger
        title="Delete this document?"
        message="The encrypted object is removed from storage, every share link is revoked immediately, and any personal knowledge-base entries are deleted. This cannot be undone."
        confirmLabel="Delete permanently"
        loading={busy}
        onConfirm={remove}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  )
}
