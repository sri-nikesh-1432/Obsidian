import { useRef, useState } from 'react'
import { CloudUpload, FileUp, Lock } from 'lucide-react'
import { api, ApiError, fileToBase64 } from '../lib/api'
import type { DocumentMeta } from '../lib/types'
import { formatBytes } from '../lib/format'
import { Button, ChoiceRow, Modal, Toggle } from './ui'
import { useToast } from '../store/toast'

interface Props {
  open: boolean
  onClose: () => void
  onUploaded: (doc: DocumentMeta) => void
  aiEnabled: boolean
}

const MAX_MB = 8

export default function UploadDialog({ open, onClose, onUploaded, aiEnabled }: Props) {
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [visibility, setVisibility] = useState<'private' | 'public'>('private')
  const [profileVisible, setProfileVisible] = useState(false)
  const [ragEligible, setRagEligible] = useState(true)
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)

  const reset = () => {
    setFile(null)
    setVisibility('private')
    setProfileVisible(false)
    setRagEligible(true)
    setError('')
    setStage('')
    setBusy(false)
  }

  const close = () => {
    if (busy) return
    reset()
    onClose()
  }

  const pick = (f: File | null | undefined) => {
    if (!f) return
    setError('')
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`File exceeds the ${MAX_MB} MB upload limit.`)
      return
    }
    setFile(f)
  }

  const submit = async () => {
    if (!file) return
    setBusy(true)
    setError('')
    setStage('Validating file…')
    try {
      const content_base64 = await fileToBase64(file)
      setStage('Encrypting with AES-256-GCM…')
      const data = await api<{ document: DocumentMeta }>('/documents', {
        method: 'POST',
        body: {
          filename: file.name,
          content_base64,
          visibility,
          profile_visible: profileVisible,
          rag_eligible: aiEnabled && ragEligible,
        },
      })
      setStage('Stored securely.')
      toast.push('success', `${file.name} encrypted and stored.`)
      onUploaded(data.document)
      reset()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Upload document"
      subtitle="Encrypted before it leaves the server boundary."
      width="max-w-xl"
    >
      {/* dropzone */}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]) }}
        className={`rounded-2xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
          dragging ? 'border-cognac bg-cognac/5' : 'border-beige-dark bg-white/60 hover:border-faint'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv,.docx,.xlsx,.pptx,.rtf,.json,.log"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        {file ? (
          <div className="flex items-center justify-center gap-3">
            <FileUp size={18} className="text-cognac" />
            <div className="text-left">
              <div className="text-sm font-medium">{file.name}</div>
              <div className="text-xs text-faint">{formatBytes(file.size)} · ready to encrypt</div>
            </div>
          </div>
        ) : (
          <>
            <CloudUpload size={22} className="mx-auto text-cognac" />
            <div className="text-sm font-medium mt-2">Drop a file here, or click to browse</div>
            <div className="text-xs text-faint mt-1">
              PDF, images, text, Office files · max {MAX_MB} MB
            </div>
          </>
        )}
      </div>

      <div className="mt-5 grid sm:grid-cols-2 gap-4">
        <div>
          <span className="text-[13px] font-medium text-graphite">Document visibility</span>
          <div className="mt-2">
            <ChoiceRow
              name="visibility"
              value={visibility}
              onChange={setVisibility}
              options={[
                { value: 'private', label: 'Private', description: 'Only you, unless you share it.' },
                { value: 'public', label: 'Public', description: 'Can be surfaced publicly.' },
              ]}
            />
          </div>
        </div>
        <div className="space-y-3">
          <div className="rounded-xl border hairline bg-white/70 px-4 py-3">
            <Toggle
              checked={profileVisible}
              onChange={setProfileVisible}
              label="Show on my profile"
              description="Faculty & recruiters can open it if your profile is visible."
            />
          </div>
          {aiEnabled && (
            <div className="rounded-xl border hairline bg-white/70 px-4 py-3">
              <Toggle
                checked={ragEligible}
                onChange={setRagEligible}
                label="Index for personal AI"
                description="Adds text content to your private knowledge base."
              />
            </div>
          )}
        </div>
      </div>

      <div className="mt-4 rounded-xl bg-ivory-deep/70 border hairline px-4 py-3 flex items-start gap-2.5 text-[13px] text-muted">
        <Lock size={14} className="text-success mt-0.5 shrink-0" />
        <span>
          A unique AES-256-GCM key is generated for this file and wrapped by AWS KMS.
          {profileVisible && ' Profile-visible documents can be opened by faculty and recruiters when your profile is visible.'}
          {aiEnabled && ragEligible && ' Text content is indexed only inside your personal knowledge base.'}
        </span>
      </div>

      {error && (
        <div className="mt-4 rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-3">
        <div className="text-xs text-muted flex items-center gap-2">
          {stage && <span className="spinner" />}
          {stage}
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="accent" onClick={submit} loading={busy} disabled={!file}>
            Upload & encrypt
          </Button>
        </div>
      </div>
    </Modal>
  )
}
