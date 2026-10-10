import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderLock, FolderUp, Search } from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { DocumentList, DocumentMeta, StorageStatus } from '../../lib/types'
import { formatBytes } from '../../lib/format'
import { Button, EmptyState, Input, PageHeader, Select, Spinner } from '../../components/ui'
import DocumentCard from '../../components/DocumentCard'
import UploadDialog from '../../components/UploadDialog'
import ShareDialog from '../../components/ShareDialog'
import StorageMeter from '../../components/StorageMeter'

type Filter = 'all' | 'private' | 'public' | 'profile' | 'shared'
type Sort = 'newest' | 'oldest' | 'name' | 'size'

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'private', label: 'Private' },
  { value: 'public', label: 'Public' },
  { value: 'profile', label: 'On profile' },
  { value: 'shared', label: 'Shared' },
]

export default function Vault() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [docs, setDocs] = useState<DocumentMeta[] | null>(null)
  const [storage, setStorage] = useState<StorageStatus | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<Sort>('newest')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [shareDoc, setShareDoc] = useState<DocumentMeta | null>(null)
  const [totalBytes, setTotalBytes] = useState(0)

  const load = useCallback(async () => {
    try {
      const data = await api<DocumentList>('/documents')
      setDocs(data.documents)
      setTotalBytes(data.total_bytes)
      if (data.storage) setStorage(data.storage)
    } catch {
      setDocs([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const visible = useMemo(() => {
    let list = docs ?? []
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      list = list.filter((d) => d.filename.toLowerCase().includes(q))
    }
    if (filter === 'private') list = list.filter((d) => d.visibility === 'private')
    if (filter === 'public') list = list.filter((d) => d.visibility === 'public')
    if (filter === 'profile') list = list.filter((d) => d.profile_visible)
    if (filter === 'shared') list = list.filter((d) => d.share_count > 0)
    const sorted = [...list]
    if (sort === 'name') sorted.sort((a, b) => a.filename.localeCompare(b.filename))
    else if (sort === 'size') sorted.sort((a, b) => b.size_bytes - a.size_bytes)
    else if (sort === 'oldest') sorted.sort((a, b) => a.created_at.localeCompare(b.created_at))
    else sorted.sort((a, b) => b.created_at.localeCompare(a.created_at))
    return sorted
  }, [docs, query, filter, sort])

  if (docs === null) return <Spinner label="Opening your vault…" />

  return (
    <div className="fade-up">
      <PageHeader
        title="Documents"
        subtitle={`${docs.length} encrypted document${docs.length === 1 ? '' : 's'} · ${formatBytes(totalBytes)} at rest`}
        actions={
          <Button variant="accent" onClick={() => setUploadOpen(true)}>
            <FolderUp size={15} /> Upload
          </Button>
        }
      />

      {storage && (
        <div className="mb-4">
          <StorageMeter storage={storage} onUpgrade={() => navigate('/app/storage')} />
        </div>
      )}

      {/* toolbar */}
      <div className="panel-solid rounded-2xl p-3 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-faint" />
          <Input
            placeholder="Search by filename…"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search documents"
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`rounded-full border px-3 py-1.5 text-[13px] transition-all focus-ring ${
                filter === f.value
                  ? 'border-cognac/70 bg-cognac/8 text-cognac-deep'
                  : 'border-beige bg-white/70 text-graphite hover:border-faint/60'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <Select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort documents" className="w-auto">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="name">Name A–Z</option>
          <option value="size">Largest first</option>
        </Select>
      </div>

      {/* grid */}
      {visible.length === 0 ? (
        <div className="mt-5">
          <EmptyState
            icon={<FolderLock size={22} />}
            title={docs.length === 0 ? 'Your vault is empty' : 'No documents match'}
            description={
              docs.length === 0
                ? 'Upload certificates, resumes, marksheets and reports. Each file is encrypted with its own key before storage.'
                : 'Try a different search term or clear the filters.'
            }
            action={
              docs.length === 0 ? (
                <Button variant="accent" onClick={() => setUploadOpen(true)}>
                  Upload document
                </Button>
              ) : (
                <Button
                  variant="soft"
                  onClick={() => {
                    setQuery('')
                    setFilter('all')
                  }}
                >
                  Clear filters
                </Button>
              )
            }
          />
        </div>
      ) : (
        <div className="mt-5 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visible.map((doc) => (
            <DocumentCard
              key={doc.document_id}
              doc={doc}
              onChanged={load}
              onShare={(d) => setShareDoc(d)}
            />
          ))}
        </div>
      )}

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => void load()}
        aiEnabled={!!user?.ai_enabled}
      />
      <ShareDialog open={!!shareDoc} doc={shareDoc} onClose={() => setShareDoc(null)} />
    </div>
  )
}
