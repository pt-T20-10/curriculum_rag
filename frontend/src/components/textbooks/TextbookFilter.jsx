import { useTranslation } from 'react-i18next'

export function TextbookFilter({ filters, onFilterChange }) {
  const { t } = useTranslation()
  const contentTypes = [
    { value: '', label: t('textbook.filter.allTypesShort') },
    { value: 'scholarly', label: `📚 ${t('textbook.contentType.scholarly')}` },
    { value: 'technical', label: `🔧 ${t('textbook.contentType.technical')}` },
    { value: 'practical', label: `💼 ${t('textbook.contentType.practical')}` },
    { value: 'lifestyle', label: `🌱 ${t('textbook.contentType.lifestyle')}` },
  ]

  const statuses = [
    { value: '', label: t('textbook.filter.allStatuses') },
    { value: 'pending', label: t('textbook.status.pending') },
    { value: 'generating', label: t('textbook.status.generating') },
    { value: 'completed', label: t('textbook.status.completed') },
    { value: 'failed', label: t('textbook.status.failed') },
  ]

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
      <div className="flex flex-col sm:flex-row gap-4">
        {/* Content Type Filter */}
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('textbook.filter.contentType')}
          </label>
          <select
            value={filters.content_type || ''}
            onChange={(e) => onFilterChange('content_type', e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
          >
            {contentTypes.map(type => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </div>

        {/* Status Filter */}
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('textbook.filter.status')}
          </label>
          <select
            value={filters.status || ''}
            onChange={(e) => onFilterChange('status', e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
          >
            {statuses.map(status => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </div>

        {/* Clear Filters */}
        {(filters.content_type || filters.status) && (
          <div className="flex items-end">
            <button
              onClick={() => onFilterChange('clear')}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              {t('textbook.filter.clear')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
