import { useMemo, useState } from 'react'
import { FiExternalLink, FiFileText, FiInfo, FiLink } from 'react-icons/fi'
import { useTranslation } from 'react-i18next'

function qualityClass(quality) {
  if (quality === 'sufficient') {
    return 'bg-green-50 text-green-700 border-green-200'
  }
  if (quality === 'insufficient') {
    return 'bg-amber-50 text-amber-700 border-amber-200'
  }
  if (quality === 'best_effort') {
    return 'bg-amber-50 text-amber-700 border-amber-200'
  }
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

function statusClass(status) {
  if (['embedded', 'ready', 'completed'].includes(status)) return 'bg-green-50 text-green-700 border-green-200'
  if (status === 'verified') return 'bg-green-50 text-green-700 border-green-200'
  if (status === 'pending') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (status === 'warning') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (status === 'failed') return 'bg-red-50 text-red-700 border-red-200'
  if (status === 'discarded') return 'bg-red-50 text-red-700 border-red-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

function safeDomain(source) {
  if (source?.domain) return source.domain
  try {
    return new URL(source?.url || '').hostname
  } catch {
    return source?.url || ''
  }
}

function uploadedSourceId(url = '') {
  const match = String(url || '').match(/^uploaded:\/\/([^/]+)/)
  return match?.[1] || ''
}

function uploadedFilename(url = '') {
  const match = String(url || '').match(/^uploaded:\/\/[^/]+\/(.+)$/)
  return match?.[1] ? decodeURIComponent(match[1]) : ''
}

function sourceKeyFromMaterial(material) {
  if (material?.kind === 'user_file') {
    return `uploaded://${material.id}/${material.filename || 'source'}`
  }
  return material?.url || material?.id || ''
}

function sourceKeyFromAudit(source) {
  return source?.url || ''
}

function sourceTitle(material, source) {
  const apa = material?.apa || {}
  if (material?.kind === 'user_file' || String(source?.url || '').startsWith('uploaded://')) {
    return apa.title || material?.filename || uploadedFilename(source?.url) || source?.url
  }
  return apa.title || safeDomain(source || material) || source?.url || material?.url || ''
}

function sourceSubtitle(material, source) {
  if (material?.kind === 'user_file' || String(source?.url || '').startsWith('uploaded://')) {
    return material?.filename || uploadedFilename(source?.url) || source?.url
  }
  return source?.url || material?.url || ''
}

function buildDisplaySources(auditSources, sourceMaterials) {
  const byId = new Map()
  const byUrl = new Map()
  for (const material of sourceMaterials) {
    if (material?.id) byId.set(String(material.id), material)
    if (material?.url) byUrl.set(String(material.url), material)
  }

  const rows = new Map()
  for (const source of auditSources) {
    const key = sourceKeyFromAudit(source)
    const material = String(source?.url || '').startsWith('uploaded://')
      ? byId.get(uploadedSourceId(source.url))
      : byUrl.get(String(source?.url || ''))
    rows.set(key, {
      key,
      url: source.url,
      kind: material?.kind || (String(source?.url || '').startsWith('uploaded://') ? 'user_file' : 'web'),
      type: material?.type || '',
      title: sourceTitle(material, source),
      subtitle: sourceSubtitle(material, source),
      status: material?.status || source.status || 'pass',
      auditStatus: source.status || 'pass',
      count: source.count || material?.chunk_count || 0,
      score: typeof source.avg_score === 'number' ? source.avg_score : null,
      sample: source.sample || '',
      warnings: Array.isArray(material?.warnings) ? material.warnings : [],
      apa: material?.apa || {},
      apaNeedsReview: Boolean(material?.apa_needs_review || material?.apa?.needs_review),
      documentCount: material?.document_count || 0,
      source,
      material,
    })
  }

  for (const material of sourceMaterials) {
    const key = sourceKeyFromMaterial(material)
    if (!key || rows.has(key)) continue
    rows.set(key, {
      key,
      url: material.url || key,
      kind: material.kind,
      type: material.type || '',
      title: sourceTitle(material, null),
      subtitle: sourceSubtitle(material, null),
      status: material.status || 'pending',
      auditStatus: '',
      count: material.chunk_count || 0,
      score: null,
      sample: '',
      warnings: Array.isArray(material.warnings) ? material.warnings : [],
      apa: material.apa || {},
      apaNeedsReview: Boolean(material.apa_needs_review || material.apa?.needs_review),
      documentCount: material.document_count || 0,
      source: null,
      material,
    })
  }

  return Array.from(rows.values())
}

function SourceDetailModal({ source, onClose, t }) {
  if (!source) return null
  const apa = source.apa || {}
  const warnings = source.warnings || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-label={t('app.close')}
      />
      <div className="relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
              {t('textbook.contentSidebar.sourceAudit.uploadedFile')}
            </p>
            <h3 className="mt-1 break-words text-base font-bold text-gray-900">
              {source.title}
            </h3>
            <p className="mt-1 break-all text-xs text-gray-500">{source.subtitle}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            {t('app.close')}
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded border border-gray-200 bg-gray-50 p-2">
            <p className="text-gray-500">{t('textbook.contentSidebar.sourceAudit.statusLabel')}</p>
            <p className="mt-1 font-semibold text-gray-800">
              {t(`textbook.contentSidebar.sourceAudit.status.${source.status}`, {
                defaultValue: source.status || '-',
              })}
            </p>
            {source.apaNeedsReview && (
              <p className="mt-1 text-[11px] font-semibold text-amber-700">
                {t('textbook.contentSidebar.sourceAudit.apaNeedsReview')}
              </p>
            )}
          </div>
          <div className="rounded border border-gray-200 bg-gray-50 p-2">
            <p className="text-gray-500">{t('textbook.contentSidebar.sourceAudit.retrievedChunks')}</p>
            <p className="mt-1 font-semibold text-gray-800">{source.count || 0}</p>
          </div>
          <div className="rounded border border-gray-200 bg-gray-50 p-2">
            <p className="text-gray-500">{t('textbook.contentSidebar.sourceAudit.documents')}</p>
            <p className="mt-1 font-semibold text-gray-800">{source.documentCount || 0}</p>
          </div>
          <div className="rounded border border-gray-200 bg-gray-50 p-2">
            <p className="text-gray-500">{t('textbook.contentSidebar.sourceAudit.fileType')}</p>
            <p className="mt-1 font-semibold uppercase text-gray-800">{source.type || '-'}</p>
          </div>
        </div>

        <div className="mt-4 space-y-2 text-xs">
          <p className="font-semibold text-gray-800">
            {t('textbook.contentSidebar.sourceAudit.apaMetadata')}
          </p>
          <div className="rounded border border-gray-200 bg-gray-50 p-3 text-gray-600">
            <p>{t('textbook.contentSidebar.sourceAudit.author')}: {apa.author || '-'}</p>
            <p>{t('textbook.contentSidebar.sourceAudit.year')}: {apa.year || 'n.d.'}</p>
            <p>{t('textbook.contentSidebar.sourceAudit.publisher')}: {apa.publisher || '-'}</p>
          </div>
        </div>

        {warnings.length > 0 && (
          <div className="mt-4 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            <p className="font-semibold">{t('textbook.contentSidebar.sourceAudit.warnings')}</p>
            <ul className="mt-1 space-y-1">
              {warnings.map((warning, index) => (
                <li key={`${warning}:${index}`}>- {warning}</li>
              ))}
            </ul>
          </div>
        )}

        {source.sample && (
          <div className="mt-4 rounded border border-gray-200 bg-white p-3 text-xs text-gray-600">
            <p className="mb-1 font-semibold text-gray-800">
              {t('textbook.contentSidebar.sourceAudit.sample')}
            </p>
            <p className="leading-5">{source.sample}</p>
          </div>
        )}

        <p className="mt-4 rounded border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-blue-800">
          {t('textbook.contentSidebar.sourceAudit.uploadedFileNote')}
        </p>
      </div>
    </div>
  )
}

export function SourceAuditSection({ sourceAudit, sourceMaterials = [], className = '' }) {
  const { t } = useTranslation()
  const [selectedSource, setSelectedSource] = useState(null)
  const displaySources = useMemo(
    () => buildDisplaySources(
      Array.isArray(sourceAudit?.sources) ? sourceAudit.sources : [],
      Array.isArray(sourceMaterials) ? sourceMaterials : [],
    ),
    [sourceAudit, sourceMaterials],
  )
  const hasSources = displaySources.length > 0
  const quality = sourceAudit?.context_quality || 'unknown'
  const sourceCount = Math.max(sourceAudit?.unique_sources || 0, displaySources.length)

  return (
    <section className={`flex min-h-0 flex-col overflow-hidden border-b border-gray-200 px-4 py-3 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-bold text-gray-800">
          {t('textbook.contentSidebar.sourceAudit.title')}
        </h3>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${qualityClass(quality)}`}>
          {t(`textbook.contentSidebar.sourceAudit.quality.${quality}`, {
            defaultValue: quality,
          })}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-2 text-center">
        <div className="rounded border border-gray-200 bg-gray-50 px-2 py-2">
          <div className="text-[11px] text-gray-500">
            {t('textbook.contentSidebar.sourceAudit.sources')}
          </div>
          <div className="text-sm font-bold text-gray-800">
            {sourceCount}
          </div>
        </div>
        <div className="rounded border border-gray-200 bg-gray-50 px-2 py-2">
          <div className="text-[11px] text-gray-500">
            {t('textbook.contentSidebar.sourceAudit.chunks')}
          </div>
          <div className="text-sm font-bold text-gray-800">
            {sourceAudit?.total_chunks || 0}
          </div>
        </div>
        <div className="rounded border border-green-200 bg-green-50 px-2 py-2">
          <div className="text-[11px] text-green-700">
            {t('textbook.contentSidebar.sourceAudit.verifiedChunks')}
          </div>
          <div className="text-sm font-bold text-green-800">
            {sourceAudit?.verified_chunks || 0}
          </div>
        </div>
        <div className="rounded border border-gray-200 bg-gray-50 px-2 py-2">
          <div className="text-[11px] text-gray-500">
            {t('textbook.contentSidebar.sourceAudit.retrievals')}
          </div>
          <div className="text-sm font-bold text-gray-800">
            {sourceAudit?.total_retrievals || 0}
          </div>
        </div>
      </div>

      {quality === 'best_effort' && (
        <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-4 text-amber-700">
          {t('textbook.contentSidebar.sourceAudit.bestEffortNote')}
        </p>
      )}

      {!hasSources ? (
        <p className="mt-3 text-xs text-gray-500">
          {t('textbook.contentSidebar.sourceAudit.empty')}
        </p>
      ) : (
        <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {displaySources.map((source) => {
            const isUploadedFile = source.kind === 'user_file' || String(source.url || '').startsWith('uploaded://')
            const score = typeof source.score === 'number'
              ? source.score.toFixed(2)
              : null
            const typeLabel = isUploadedFile
              ? (source.type || 'file').toUpperCase()
              : t('textbook.contentSidebar.sourceAudit.web')
            const body = (
              <>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-1.5 truncate font-medium text-gray-800">
                    {isUploadedFile ? <FiFileText className="h-3.5 w-3.5 shrink-0" /> : <FiLink className="h-3.5 w-3.5 shrink-0" />}
                    <span className="truncate">{source.title}</span>
                  </span>
                  <div className="flex shrink-0 items-center gap-1">
                    {score && (
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">
                        {score}
                      </span>
                    )}
                    <span className={`rounded border px-1.5 py-0.5 text-[11px] ${statusClass(source.status)}`}>
                      {t(`textbook.contentSidebar.sourceAudit.status.${source.status}`, {
                        defaultValue: source.status || 'pass',
                      })}
                    </span>
                    {source.apaNeedsReview && (
                      <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">
                        {t('textbook.contentSidebar.sourceAudit.apaShort')}
                      </span>
                    )}
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600" title={t('textbook.contentSidebar.sourceAudit.retrievedChunks')}>
                      {source.count}
                    </span>
                  </div>
                </div>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <span className="truncate text-[11px] text-gray-500">
                    {source.subtitle}
                  </span>
                  <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">
                    {typeLabel}
                  </span>
                </div>
                {source.sample && (
                  <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-gray-600">
                    {source.sample}
                  </div>
                )}
                {source.warnings.length > 0 && (
                  <div className="mt-1 flex items-center gap-1 text-[11px] text-amber-700">
                    <FiInfo className="h-3 w-3 shrink-0" />
                    <span className="truncate">{source.warnings[0]}</span>
                  </div>
                )}
              </>
            )
            return isUploadedFile ? (
              <button
                key={source.key}
                type="button"
                onClick={() => setSelectedSource(source)}
                className="block w-full rounded border border-gray-200 bg-white px-3 py-2 text-left text-xs hover:border-blue-300 hover:bg-blue-50"
                title={source.subtitle}
              >
                {body}
              </button>
            ) : (
              <a
                key={source.key}
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded border border-gray-200 bg-white px-3 py-2 text-xs hover:border-blue-300 hover:bg-blue-50"
                title={source.url}
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">{body}</div>
                  <FiExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" />
                </div>
              </a>
            )
          })}
        </div>
      )}
      <SourceDetailModal
        source={selectedSource}
        onClose={() => setSelectedSource(null)}
        t={t}
      />
    </section>
  )
}
