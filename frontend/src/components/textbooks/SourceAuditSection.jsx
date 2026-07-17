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
  if (status === 'verified') return 'bg-green-50 text-green-700 border-green-200'
  if (status === 'warning') return 'bg-amber-50 text-amber-700 border-amber-200'
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

export function SourceAuditSection({ sourceAudit, className = '' }) {
  const { t } = useTranslation()
  const sources = Array.isArray(sourceAudit?.sources) ? sourceAudit.sources : []
  const hasSources = sources.length > 0
  const quality = sourceAudit?.context_quality || 'unknown'

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
            {sourceAudit?.unique_sources || 0}
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
          {sources.map((source) => {
            const domain = safeDomain(source)
            const score = typeof source.avg_score === 'number'
              ? source.avg_score.toFixed(2)
              : null
            return (
              <a
                key={source.url}
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded border border-gray-200 bg-white px-3 py-2 text-xs hover:border-blue-300 hover:bg-blue-50"
                title={source.url}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-gray-800">{domain}</span>
                  <div className="flex shrink-0 items-center gap-1">
                    {score && (
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">
                        {score}
                      </span>
                    )}
                    <span className={`rounded border px-1.5 py-0.5 text-[11px] ${statusClass(source.status)}`}>
                      {source.status || 'pass'}
                    </span>
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
                      {source.count}
                    </span>
                  </div>
                </div>
                <div className="mt-1 truncate text-[11px] text-gray-500">
                  {source.url}
                </div>
                {source.sample && (
                  <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-gray-600">
                    {source.sample}
                  </div>
                )}
              </a>
            )
          })}
        </div>
      )}
    </section>
  )
}
