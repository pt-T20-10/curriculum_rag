import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CONTENT_LEVEL } from '../../constants/textbookOptions'
import { createDefaultStructure, serializeStructureToMarkdown, validateStructure } from '../../utils/curriculumStructure'
import { CurriculumStructureEditor } from './CurriculumStructureEditor'

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

const SOURCE_GROUPS = [
  {
    key: 'english_academic',
    labelKey: 'textbook.form.sourceGroupEnglishAcademic',
    items: [
      ['en_academic_open_textbooks', 'OpenStax, LibreTexts, MIT OCW'],
      ['en_academic_universities', 'Stanford, Berkeley, CMU, Ivy League'],
    ],
  },
  {
    key: 'english_technical',
    labelKey: 'textbook.form.sourceGroupEnglishTechnical',
    items: [
      ['en_technical_official_docs', 'Official technical docs'],
    ],
  },
  {
    key: 'vietnamese_academic',
    labelKey: 'textbook.form.sourceGroupVietnameseAcademic',
    items: [
      ['vi_academic_universities', '.edu.vn, VNU, HUST, HCMUT, PTIT'],
    ],
  },
]

const SOURCE_MODE_OPTIONS = [
  ['system_default', 'textbook.form.sourceModeSystem'],
  ['custom_hybrid', 'textbook.form.sourceModeHybrid'],
  ['custom_only', 'textbook.form.sourceModeCustomOnly'],
]

const RECOMMENDED_CONFIG = {
  num_chapters: { min: 2, max: 12 },
  max_subsections_per_chapter: { min: 2, max: 8 },
}

const ABSOLUTE_CONFIG_LIMITS = {
  num_chapters: { min: 1, max: 50 },
  max_subsections_per_chapter: { min: 1, max: 30 },
}

const VI_DIACRITIC_RE = /[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]/i
const DOMAIN_RE = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i

const UNACCENTED_VI_PATTERNS = [
  /\bhoc\b/,
  /\blap\s+trinh\b/,
  /\bgiao\s+trinh\b/,
  /\bco\s+ban\b/,
  /\bcan\s+ban\b/,
  /\bcao\s+cap\b/,
  /\bnang\s+cao\b/,
  /\bnhap\s+mon\b/,
  /\bcho\s+nguoi\b/,
  /\bnguoi\s+moi\b/,
  /\bdai\s+hoc\b/,
  /\blop\s+\d+\b/,
  /\bung\s+dung\b/,
  /\bthuc\s+te\b/,
  /\bbai\s+tap\b/,
  /\bvi\s+du\b/,
  /\bmon\s+hoc\b/,
  /\bkhoa\s+hoc\b/,
  /\btoan\b/,
  /\bvat\s+ly\b/,
  /\bhoa\s+hoc\b/,
  /\bsinh\s+hoc\b/,
  /\blich\s+su\b/,
  /\bxac\s+suat\b/,
  /\bthong\s+ke\b/,
  /\bdu\s+lieu\b/,
  /\bmay\s+tinh\b/,
  /\btri\s+tue\b/,
  /\bnhan\s+tao\b/,
  /\btieng\s+viet\b/,
  /\btieng\s+anh\b/,
]

function parseIntegerInput(value) {
  if (value === '' || value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isInteger(parsed) ? parsed : NaN
}

function normalizeAscii(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9+#.\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function looksLikeUnaccentedVietnameseTopic(topic) {
  const rawTopic = String(topic || '').trim()
  if (!rawTopic || VI_DIACRITIC_RE.test(rawTopic)) {
    return false
  }

  const normalized = normalizeAscii(rawTopic)
  if (!normalized) {
    return false
  }

  return UNACCENTED_VI_PATTERNS.some(pattern => pattern.test(normalized))
}

function defaultSourcePreferences() {
  return {
    source_mode: 'system_default',
    selected_source_ids: [],
    custom_urls: [],
    custom_domains: [],
  }
}

function parseSourceLines(value, t) {
  const urls = []
  const domains = []
  const errors = []
  String(value || '').split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim()
    if (!line) return

    if (/^https?:\/\//i.test(line)) {
      try {
        const parsed = new URL(line)
        if (!parsed.hostname) throw new Error('missing hostname')
        if (!urls.includes(line)) urls.push(line)
      } catch {
        errors.push(t('textbook.form.sourceLineUrlInvalid', { line: index + 1 }))
      }
      return
    }

    if (line.includes('://') || line.includes('/') || line.includes('?') || line.includes('#')) {
      errors.push(t('textbook.form.sourceLineDomainInvalid', { line: index + 1 }))
      return
    }

    const domain = line.toLowerCase().replace(/^www\./, '')
    if (!DOMAIN_RE.test(domain)) {
      errors.push(t('textbook.form.sourceLineDomainInvalid', { line: index + 1 }))
      return
    }
    if (!domains.includes(domain)) domains.push(domain)
  })

  return { urls, domains, errors }
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
  const { i18n, t } = useTranslation()
  const [formData, setFormData] = useState({
    topic: '',
    planning_mode: 'auto',
    textbook_mode: 'standard',
    source_preferences: defaultSourcePreferences(),
    num_chapters: 3,
    content_level: CONTENT_LEVEL.MEDIUM,
    max_subsections_per_chapter: 5,
    enable_images: true,
    formula_policy: 'auto'
  })
  const [initialStructure, setInitialStructure] = useState(() => createDefaultStructure(t))
  const [sourceInput, setSourceInput] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [confirmWarnings, setConfirmWarnings] = useState([])
  const [pendingSubmitData, setPendingSubmitData] = useState(null)
  const isAdmin = user?.role === 'admin'

  const getConfigIssues = (data) => {
    const errors = {}
    const warnings = []

    const numericFields = [
      {
        name: 'num_chapters',
        minKey: 'textbook.form.chapterTooLow',
        maxKey: 'textbook.form.chapterTooHigh',
        warnLowKey: 'textbook.form.chapterLowWarning',
        warnHighKey: 'textbook.form.chapterHighWarning',
      },
      {
        name: 'max_subsections_per_chapter',
        minKey: 'textbook.form.subsectionTooLow',
        maxKey: 'textbook.form.subsectionTooHigh',
        warnLowKey: 'textbook.form.subsectionLowWarning',
        warnHighKey: 'textbook.form.subsectionHighWarning',
      },
    ]

    numericFields.forEach(({ name, minKey, maxKey, warnLowKey, warnHighKey }) => {
      const value = data[name]
      const absolute = ABSOLUTE_CONFIG_LIMITS[name]
      const recommended = RECOMMENDED_CONFIG[name]

      if (value === null) {
        errors[name] = t('textbook.form.numberRequired')
      } else if (Number.isNaN(value)) {
        errors[name] = t('textbook.form.numberInteger')
      } else if (value < absolute.min) {
        errors[name] = t(minKey, { min: absolute.min })
      } else if (value > absolute.max) {
        errors[name] = t(maxKey, { max: absolute.max })
      } else if (value < recommended.min) {
        warnings.push(t(warnLowKey, { value, min: recommended.min }))
      } else if (value > recommended.max) {
        warnings.push(t(warnHighKey, { value, max: recommended.max }))
      }
    })

    return { errors, warnings }
  }

  const getTopicWarnings = (data) => {
    const language = (i18n.resolvedLanguage || i18n.language || 'vi').split('-')[0]
    if (language !== 'vi') {
      return []
    }

    if (looksLikeUnaccentedVietnameseTopic(data.topic)) {
      return [t('textbook.form.unaccentedVietnameseWarning')]
    }

    return []
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!formData.topic.trim()) {
      return
    }

    const submitData = {
      ...formData,
      topic: formData.topic.trim(),
      num_chapters: parseIntegerInput(formData.num_chapters),
      max_subsections_per_chapter: parseIntegerInput(formData.max_subsections_per_chapter),
    }
    const shouldUseCustomSources = (formData.source_preferences?.source_mode || 'system_default') !== 'system_default'
    const parsedSources = shouldUseCustomSources
      ? parseSourceLines(sourceInput, t)
      : { urls: [], domains: [], errors: [] }
    const sourcePreferences = {
      ...defaultSourcePreferences(),
      ...(formData.source_preferences || {}),
      selected_source_ids: shouldUseCustomSources
        ? (formData.source_preferences?.selected_source_ids || [])
        : [],
      custom_urls: shouldUseCustomSources ? parsedSources.urls : [],
      custom_domains: shouldUseCustomSources ? parsedSources.domains : [],
    }
    submitData.source_preferences = sourcePreferences

    if (parsedSources.errors.length > 0) {
      setFieldErrors({ source_preferences: parsedSources.errors.join(' ') })
      return
    }
    if (
      sourcePreferences.source_mode === 'custom_only' &&
      sourcePreferences.selected_source_ids.length === 0 &&
      sourcePreferences.custom_urls.length === 0 &&
      sourcePreferences.custom_domains.length === 0
    ) {
      setFieldErrors({ source_preferences: t('textbook.form.sourceCustomOnlyRequired') })
      return
    }

    if (submitData.planning_mode === 'structured') {
      const structureError = validateStructure(initialStructure, t)
      if (structureError) {
        setFieldErrors({ initial_structure: structureError })
        return
      }
      const chapterCount = initialStructure.chapters.length
      const maxSubsectionCount = Math.max(
        ...initialStructure.chapters.map(chapter => chapter.subsections.length)
      )
      submitData.initial_structure_markdown = serializeStructureToMarkdown(initialStructure)
      submitData.num_chapters = chapterCount
      submitData.max_subsections_per_chapter = maxSubsectionCount
    }

    const { errors, warnings } = getConfigIssues(submitData)
    const topicWarnings = getTopicWarnings(submitData)

    if (fieldErrors.initial_structure) {
      setFieldErrors(prev => {
        const next = { ...prev }
        delete next.initial_structure
        return next
      })
    }
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) {
      return
    }

    if (warnings.length > 0 || topicWarnings.length > 0) {
      setConfirmWarnings([...topicWarnings, ...warnings])
      setPendingSubmitData(submitData)
      return
    }

    onSubmit(submitData)
  }

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }))
    if (fieldErrors[name]) {
      setFieldErrors(prev => {
        const next = { ...prev }
        delete next[name]
        return next
      })
    }
  }

  const setSourceMode = (mode) => {
    setFormData(prev => ({
      ...prev,
      source_preferences: {
        ...defaultSourcePreferences(),
        ...(prev.source_preferences || {}),
        source_mode: mode,
      },
    }))
  }

  const toggleSourceId = (sourceId) => {
    setFormData(prev => {
      const prefs = {
        ...defaultSourcePreferences(),
        ...(prev.source_preferences || {}),
      }
      const current = prefs.selected_source_ids || []
      const selected = current.includes(sourceId)
        ? current.filter(id => id !== sourceId)
        : [...current, sourceId]
      return {
        ...prev,
        source_preferences: {
          ...prefs,
          selected_source_ids: selected,
        },
      }
    })
  }

  const sourcePrefs = {
    ...defaultSourcePreferences(),
    ...(formData.source_preferences || {}),
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
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.planningMode')}</span>
                <span className="font-semibold text-gray-800">
                  {t(
                    (submittedConfig?.planning_mode || formData.planning_mode) === 'structured'
                      ? 'textbook.form.planningModeStructured'
                      : 'textbook.form.planningModeAuto'
                  )}
                </span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.textbookMode')}</span>
                <span className="font-semibold text-gray-800">
                  {t(
                    (submittedConfig?.textbook_mode || formData.textbook_mode) === 'practice'
                      ? 'textbook.form.textbookModePractice'
                      : 'textbook.form.textbookModeStandard'
                  )}
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
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.sourceSettings')}</span>
                <span className="font-semibold text-gray-800">
                  {t(`textbook.form.sourceModeValue.${submittedConfig?.source_preferences?.source_mode || 'system_default'}`)}
                </span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-gray-500">{t('textbook.form.formulas')}</span>
                <span className="font-semibold text-gray-800">
                  {(submittedConfig?.formula_policy || formData.formula_policy) === 'include'
                    ? t('app.yes')
                    : t('app.no')}
                </span>
              </div>
              {submittedConfig?.source_preferences && (
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-gray-500">{t('textbook.form.customSources')}</span>
                  <span className="font-semibold text-gray-800">
                    {(
                      (submittedConfig.source_preferences.custom_urls?.length || 0) +
                      (submittedConfig.source_preferences.custom_domains?.length || 0) +
                      (submittedConfig.source_preferences.selected_source_ids?.length || 0)
                    )}
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
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {/* Topic Input */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('textbook.form.topic')} <span className="text-red-500">*</span>
        </label>
        <div className="mb-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2">
          <p className="text-xs font-semibold text-blue-900">
            {t('textbook.form.topicGuideTitle')}
          </p>
          <p className="mt-1 text-xs text-blue-800">
            {t('textbook.form.topicGuideText')}
          </p>
        </div>
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

      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-start gap-3">
          <input
            type="checkbox"
            id="formula_policy"
            checked={formData.formula_policy === 'include'}
            onChange={(e) => {
              setFormData(prev => ({
                ...prev,
                formula_policy: e.target.checked ? 'include' : 'auto',
              }))
            }}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            disabled={loading}
          />
          <div>
            <label htmlFor="formula_policy" className="text-sm font-medium text-gray-700">
              {t('textbook.form.formulas')}
            </label>
            <p className="mt-1 text-xs text-gray-500">
              {t('textbook.form.formulasHint')}
            </p>
          </div>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('textbook.form.textbookMode')}
        </label>
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-1">
          {[
            ['standard', 'textbook.form.textbookModeStandard'],
            ['practice', 'textbook.form.textbookModePractice'],
          ].map(([value, labelKey]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFormData(prev => ({ ...prev, textbook_mode: value }))}
              disabled={loading}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                formData.textbook_mode === value
                  ? 'bg-white text-blue-700 shadow-sm ring-1 ring-blue-200'
                  : 'text-gray-600 hover:bg-white/70'
              }`}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-gray-500">
          {formData.textbook_mode === 'practice'
            ? t('textbook.form.textbookModePracticeHint')
            : t('textbook.form.textbookModeStandardHint')}
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('textbook.form.planningMode')}
        </label>
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-1">
          {[
            ['auto', 'textbook.form.planningModeAuto'],
            ['structured', 'textbook.form.planningModeStructured'],
          ].map(([value, labelKey]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFormData(prev => ({ ...prev, planning_mode: value }))}
              disabled={loading}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                formData.planning_mode === value
                  ? 'bg-white text-blue-700 shadow-sm ring-1 ring-blue-200'
                  : 'text-gray-600 hover:bg-white/70'
              }`}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-gray-500">
          {formData.planning_mode === 'structured'
            ? t('textbook.form.planningModeStructuredHint')
            : t('textbook.form.planningModeAutoHint')}
        </p>
      </div>

      {formData.planning_mode === 'structured' && (
        <div className="space-y-3 rounded-lg border border-blue-100 bg-blue-50/40 p-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">
              {t('textbook.structure.title')}
            </h3>
            <p className="mt-1 text-xs text-gray-600">
              {t('textbook.structure.description')}
            </p>
          </div>
          {fieldErrors.initial_structure && (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
              {fieldErrors.initial_structure}
            </p>
          )}
          <CurriculumStructureEditor
            value={initialStructure}
            onChange={(next) => {
              setInitialStructure(next)
              if (fieldErrors.initial_structure) {
                setFieldErrors(prev => {
                  const updated = { ...prev }
                  delete updated.initial_structure
                  return updated
                })
              }
            }}
            disabled={loading}
          />
        </div>
      )}

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
          {formData.planning_mode === 'auto' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('textbook.form.chapters')}
              </label>
              <input
                type="number"
                name="num_chapters"
                value={formData.num_chapters}
                onChange={handleChange}
                step={1}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={loading}
              />
              {fieldErrors.num_chapters && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.num_chapters}</p>
              )}
              <p className="mt-1 text-xs text-gray-500">
                {t('textbook.form.chaptersHint')}
              </p>
            </div>
          )}

          <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('textbook.form.sourceSettings')}
              </label>
              <div className="grid grid-cols-1 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-1 sm:grid-cols-3">
                {SOURCE_MODE_OPTIONS.map(([value, labelKey]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSourceMode(value)}
                    disabled={loading}
                    className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                      sourcePrefs.source_mode === value
                        ? 'bg-white text-blue-700 shadow-sm ring-1 ring-blue-200'
                        : 'text-gray-600 hover:bg-white/70'
                    }`}
                  >
                    {t(labelKey)}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-gray-500">
                {t(`textbook.form.sourceModeHint.${sourcePrefs.source_mode}`)}
              </p>
            </div>

            {sourcePrefs.source_mode !== 'system_default' && (
              <>
                <div className="space-y-3">
                  {SOURCE_GROUPS.map(group => (
                    <div key={group.key}>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                        {t(group.labelKey)}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {group.items.map(([sourceId, label]) => {
                          const checked = sourcePrefs.selected_source_ids.includes(sourceId)
                          return (
                            <button
                              key={sourceId}
                              type="button"
                              onClick={() => toggleSourceId(sourceId)}
                              disabled={loading}
                              className={`rounded-md border px-3 py-2 text-xs font-medium transition-colors ${
                                checked
                                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                                  : 'border-gray-200 bg-white text-gray-700 hover:border-blue-200'
                              }`}
                            >
                              {label}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('textbook.form.customSources')}
                  </label>
                  <textarea
                    value={sourceInput}
                    onChange={(e) => {
                      setSourceInput(e.target.value)
                      if (fieldErrors.source_preferences) {
                        setFieldErrors(prev => {
                          const next = { ...prev }
                          delete next.source_preferences
                          return next
                        })
                      }
                    }}
                    placeholder={t('textbook.form.customSourcesPlaceholder')}
                    className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    rows={4}
                    disabled={loading}
                  />
                  {fieldErrors.source_preferences && (
                    <p className="mt-1 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
                      {fieldErrors.source_preferences}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-gray-500">
                    {t('textbook.form.customSourcesHint')}
                  </p>
                </div>
              </>
            )}
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

          {formData.planning_mode === 'auto' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('textbook.form.maxSubsections')}
              </label>
              <input
                type="number"
                name="max_subsections_per_chapter"
                value={formData.max_subsections_per_chapter}
                onChange={handleChange}
                step={1}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={loading}
              />
              {fieldErrors.max_subsections_per_chapter && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.max_subsections_per_chapter}</p>
              )}
              <p className="mt-1 text-xs text-gray-500">
                {t('textbook.form.maxSubsectionsHint')}
              </p>
            </div>
          )}

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
        disabled={loading || !formData.topic.trim() || (user && !isAdmin && user.credits < 1)}
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

      {confirmWarnings.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
            onClick={() => {
              setConfirmWarnings([])
              setPendingSubmitData(null)
            }}
          />
          <div className="relative bg-white rounded-lg shadow-2xl max-w-lg w-full mx-4 p-6">
            <div className="flex items-center justify-center w-12 h-12 mx-auto mb-4 bg-yellow-100 rounded-full">
              <svg className="w-6 h-6 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <h3 className="text-xl font-bold text-gray-900 text-center mb-2">
              {t('textbook.form.confirmBeforeCreateTitle')}
            </h3>
            <p className="text-sm text-gray-600 text-center mb-4">
              {t('textbook.form.confirmBeforeCreateDescription')}
            </p>
            <div className="space-y-2 mb-6">
              {confirmWarnings.map((warning, index) => (
                <div key={index} className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
                  {warning}
                </div>
              ))}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setConfirmWarnings([])
                  setPendingSubmitData(null)
                }}
                className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-300 transition-colors"
              >
                {t('textbook.form.reviewConfig')}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (pendingSubmitData) {
                    onSubmit(pendingSubmitData)
                  }
                  setConfirmWarnings([])
                  setPendingSubmitData(null)
                }}
                className="flex-1 px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                {t('textbook.form.confirmCreate')}
              </button>
            </div>
          </div>
        </div>
      )}
    </form>
  )
}
