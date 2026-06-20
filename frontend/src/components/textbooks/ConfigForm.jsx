import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CONTENT_LEVEL } from '../../constants/textbookOptions'

const CONTENT_LEVEL_LABEL_KEYS = {
  [CONTENT_LEVEL.SHORT]: 'textbook.form.levelShort',
  [CONTENT_LEVEL.MEDIUM]: 'textbook.form.levelMedium',
  [CONTENT_LEVEL.LONG]: 'textbook.form.levelLong',
  [CONTENT_LEVEL.VERY_LONG]: 'textbook.form.levelVeryLong',
}

const CONTENT_LEVEL_HINT_KEYS = {
  [CONTENT_LEVEL.SHORT]: 'textbook.form.levelShortHint',
  [CONTENT_LEVEL.MEDIUM]: 'textbook.form.levelMediumHint',
  [CONTENT_LEVEL.LONG]: 'textbook.form.levelLongHint',
  [CONTENT_LEVEL.VERY_LONG]: 'textbook.form.levelVeryLongHint',
}

const LANGUAGE_LABEL_KEYS = {
  vi: 'textbook.language.vi',
  en: 'textbook.language.en',
}

export function ConfigForm({
  onSubmit,
  loading,
  error,
  user,
  configExpanded,
  onToggleConfig,
  isActive = false,
  currentTopic = '',
  submittedConfig = null // ⭐ NEW - actual submitted config
}) {
  const { t } = useTranslation()
  const [formData, setFormData] = useState({
    topic: '',
    num_chapters: 3,
    content_level: CONTENT_LEVEL.MEDIUM,
    max_subsections_per_chapter: 5,
    enable_images: true
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!formData.topic.trim()) {
      return
    }
    onSubmit(formData)
  }

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }))
  }

  if (isActive) {
    // Show user's original query immediately; fall back to AI-generated title if query unavailable
    const displayQuery = submittedConfig?.topic || currentTopic || ''
    // Show AI title separately only if it's been generated and differs from the query
    const aiTitle = currentTopic && displayQuery && currentTopic !== displayQuery ? currentTopic : null

    return (
      <div className="space-y-4">
        {/* Topic banner — always shows user's query immediately */}
        <div className="p-4 bg-blue-50 border border-blue-100 rounded-lg">
          <p className="text-xs font-semibold text-blue-500 uppercase tracking-wider mb-2">
            📚 {t('textbook.form.generating')}
          </p>
          <p className="font-bold text-gray-900 text-base leading-relaxed">
            {displayQuery || '…'}
          </p>
          {aiTitle && (
            <p className="text-xs text-blue-600 mt-2">
              ✨ {t('textbook.form.aiTitle')}: <span className="font-medium">{aiTitle}</span>
            </p>
          )}
        </div>

        {/* Config toggle */}
        <button
          onClick={onToggleConfig}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
        >
          <svg
            className={`w-4 h-4 transition-transform ${configExpanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="font-medium">⚙️ {t('textbook.form.config')}</span>
          <span className="text-xs text-gray-500">({t('textbook.form.locked')})</span>
        </button>

        {configExpanded && (
          <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-3 opacity-70">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.chapters')}</span>
                <span className="font-semibold text-gray-800">{submittedConfig?.num_chapters || formData.num_chapters}</span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.contentLength')}</span>
                <span className="font-semibold text-gray-800">
                  {t(CONTENT_LEVEL_LABEL_KEYS[submittedConfig?.content_level || formData.content_level] || 'textbook.form.levelMedium')}
                </span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.maxSubsections')}</span>
                <span className="font-semibold text-gray-800">{submittedConfig?.max_subsections_per_chapter || formData.max_subsections_per_chapter}</span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.images')}</span>
                <span className="font-semibold text-gray-800">
                  {(submittedConfig?.enable_images !== undefined ? submittedConfig.enable_images : formData.enable_images) ? t('app.yes') : t('app.no')}
                </span>
              </div>
              {submittedConfig?.language && (
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-gray-500">{t('textbook.form.textbookLanguage')}</span>
                  <span className="font-semibold text-gray-800">
                    {t(LANGUAGE_LABEL_KEYS[submittedConfig.language] || 'textbook.language.vi')}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Topic Input */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('textbook.form.topic')} <span className="text-red-500">*</span>
        </label>
        <textarea
          name="topic"
          value={formData.topic}
          onChange={handleChange}
          placeholder={t('textbook.form.topicPlaceholder')}
          className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none transition-all"
          rows={3}
          disabled={loading}
          required
        />
        <p className="mt-1 text-xs text-gray-500">
          {t('textbook.form.topicHint')}
        </p>
      </div>

      {/* Advanced Config Toggle */}
      <button
        type="button"
        onClick={onToggleConfig}
        className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
      >
        <svg
          className={`w-4 h-4 transition-transform ${configExpanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-medium">⚙️ {t('textbook.form.advanced')}</span>
      </button>

      {/* Advanced Config */}
      {configExpanded && (
        <div className="space-y-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
          {/* Number of Chapters */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('textbook.form.chapters')}
            </label>
            <input
              type="number"
              name="num_chapters"
              value={formData.num_chapters}
              onChange={handleChange}
              min={2}
              max={12}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={loading}
            />
            <p className="mt-1 text-xs text-gray-500">
              {t('textbook.form.chaptersHint')}
            </p>
          </div>

          {/* Content Level */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('textbook.form.contentLength')}
            </label>
            <select
              name="content_level"
              value={formData.content_level}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={loading}
            >
              {Object.entries(CONTENT_LEVEL_LABEL_KEYS).map(([value, labelKey]) => (
                <option key={value} value={value}>{t(labelKey)}</option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-500">
              {t(CONTENT_LEVEL_HINT_KEYS[formData.content_level] || 'textbook.form.levelMediumHint')}
            </p>
          </div>

          {/* Subsections per Chapter */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('textbook.form.maxSubsections')}
            </label>
            <input
              type="number"
              name="max_subsections_per_chapter"
              value={formData.max_subsections_per_chapter}
              onChange={handleChange}
              min={2}
              max={8}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={loading}
            />
            <p className="mt-1 text-xs text-gray-500">
              {t('textbook.form.maxSubsectionsHint')}
            </p>
          </div>

          {/* Enable Images */}
          <div>
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="enable_images"
                name="enable_images"
                checked={formData.enable_images}
                onChange={handleChange}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                disabled={loading}
              />
              <label htmlFor="enable_images" className="text-sm font-medium text-gray-700">
                {t('textbook.form.images')}
              </label>
            </div>
            
            {/* Warning when images enabled */}
            {formData.enable_images && (
              <div className="mt-2 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
                <div className="flex gap-2">
                  <svg className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-yellow-800">
                      ⚠️ {t('textbook.form.imageWarningTitle')}
                    </p>
                    <p className="text-xs text-yellow-700 mt-1">
                      {t('textbook.form.imageWarningText')}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-600 font-medium text-sm">❌ {error.message}</p>
          {error.suggestions && error.suggestions.length > 0 && (
            <div className="mt-2">
              <p className="text-red-700 text-sm font-medium">💡 {t('textbook.validationSuggestions')}</p>
              <ul className="mt-1 text-red-700 text-sm space-y-1">
                {error.suggestions.map((suggestion, idx) => (
                  <li key={idx}>• {suggestion}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Credits Display */}
      {user && (
        <div className="flex items-center justify-between p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <span className="text-sm text-blue-900">
            💳 {t('textbook.form.creditsAvailable')} <span className="font-bold">{user.credits}</span>
          </span>
          <span className="text-xs text-blue-700">{t('textbook.form.createCost')}</span>
        </div>
      )}

      {/* Submit Button */}
      <button
        type="submit"
        disabled={loading || !formData.topic.trim() || (user && user.credits < 1)}
        className="w-full py-3 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 focus:ring-4 focus:ring-blue-200 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            {t('textbook.form.submitting')}
          </span>
        ) : (
          `🚀 ${t('textbook.form.submit')}`
        )}
      </button>
    </form>
  )
}
