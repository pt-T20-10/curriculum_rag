import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { textbooksAPI } from '../../api/textbooks'
import { CONTENT_LEVEL } from '../../constants/textbookOptions'
import {
  createDefaultStructure,
  countLeafSubsections,
  getMissingChildSections,
  getChapterPageBudgetIssues,
  inferStructureDepth,
  normalizeStructureForApi,
  serializeStructureToMarkdown,
  validateStructure,
} from '../../utils/curriculumStructure'
import { CurriculumStructureEditor } from './CurriculumStructureEditor'

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
  max_child_subsections_per_section: { min: 1, max: 5 },
}

const ABSOLUTE_CONFIG_LIMITS = {
  num_chapters: { min: 1, max: 50 },
  max_subsections_per_chapter: { min: 1, max: 30 },
  max_child_subsections_per_section: { min: 1, max: 20 },
}

const ADVANCED_ERROR_KEYS = new Set([
  'num_chapters',
  'max_subsections_per_chapter',
  'max_child_subsections_per_section',
  'source_preferences',
])

const MIN_PAGES_PER_SUBSECTION = 1
const IMAGE_PAGE_OVERHEAD_PER_SUBSECTION = 0.25
const PAGE_COMPATIBILITY_WARNING_MULTIPLIER = 1.25

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

function isMissingPageValue(value) {
  return value === '' || value === null || value === undefined
}

function hasMissingStructurePageTargets(structure) {
  return (structure?.chapters || []).some(chapter => (
    isMissingPageValue(chapter.target_pages) ||
    (chapter.subsections || []).some(subsection => (
      isMissingPageValue(subsection.target_pages) ||
      (subsection.children || []).some(child => isMissingPageValue(child.target_pages))
    ))
  ))
}

function estimateContentIntroPages(textbookMode) {
  return (textbookMode || 'standard') === 'practice' ? 0 : 1
}

function getPageCompatibility(data) {
  const targetPages = data.target_pages
  if (!Number.isInteger(targetPages)) return null

  const chapters = data.initial_structure?.chapters
  const chapterCount = Array.isArray(chapters)
    ? chapters.length
    : data.num_chapters
  const subsectionCounts = Array.isArray(chapters)
    ? chapters.map(chapter => countLeafSubsections([chapter]))
    : []
  const subsectionCount = subsectionCounts.length > 0
    ? subsectionCounts.reduce((sum, count) => sum + count, 0)
    : chapterCount * data.max_subsections_per_chapter * (
      data.structure_depth === 'level2'
        ? data.max_child_subsections_per_section
        : 1
    )
  const safeChapterCount = Math.max(1, chapterCount || 1)
  const safeSubsectionCount = Math.max(1, subsectionCount || 1)
  const contentIntroPages = estimateContentIntroPages(data.textbook_mode)
  const bodyPages = targetPages - contentIntroPages
  const minPagesPerSubsection = MIN_PAGES_PER_SUBSECTION + (
    data.enable_images ? IMAGE_PAGE_OVERHEAD_PER_SUBSECTION : 0
  )
  const minBodyPages = Math.max(
    safeChapterCount,
    safeSubsectionCount * minPagesPerSubsection,
  )

  return {
    bodyPages,
    chapterCount: safeChapterCount,
    subsectionCount: safeSubsectionCount,
    minTotalPages: Math.ceil(contentIntroPages + minBodyPages),
    recommendedTotalPages: Math.ceil(contentIntroPages + (minBodyPages * PAGE_COMPATIBILITY_WARNING_MULTIPLIER)),
  }
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
    max_child_subsections_per_section: 3,
    structure_depth: 'level1',
    target_pages: '',
    page_plan_confirmed: false,
    enable_images: true,
    formula_policy: 'auto'
  })
  const [initialStructure, setInitialStructure] = useState(() => createDefaultStructure(t, 'level1'))
  const [sourceInput, setSourceInput] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [confirmWarnings, setConfirmWarnings] = useState([])
  const [pendingSubmitData, setPendingSubmitData] = useState(null)
  const [pendingStructuredPageData, setPendingStructuredPageData] = useState(null)
  const [pendingMissingChildData, setPendingMissingChildData] = useState(null)
  const [missingChildSections, setMissingChildSections] = useState([])
  const [structureUpload, setStructureUpload] = useState({
    loading: false,
    fileName: '',
    warnings: [],
    unparsedItems: [],
    error: '',
  })
  const [highlightedErrorKey, setHighlightedErrorKey] = useState('')
  const formRef = useRef(null)
  const lastErrorSignatureRef = useRef('')
  const isAdmin = user?.role === 'admin'

  const errorFields = useMemo(() => Object.keys(fieldErrors), [fieldErrors])
  const firstErrorKey = errorFields[0] || (error ? 'api_error' : '')

  useEffect(() => {
    const timers = []
    if (!firstErrorKey) {
      lastErrorSignatureRef.current = ''
      timers.push(window.setTimeout(() => setHighlightedErrorKey(''), 0))
      return () => timers.forEach(timer => window.clearTimeout(timer))
    }

    const signature = JSON.stringify({
      fields: errorFields,
      message: error?.message || '',
    })
    if (signature === lastErrorSignatureRef.current) return
    lastErrorSignatureRef.current = signature

    if (!configExpanded && errorFields.some(key => ADVANCED_ERROR_KEYS.has(key))) {
      onToggleConfig?.()
    }

    timers.push(window.setTimeout(() => setHighlightedErrorKey(firstErrorKey), 0))
    timers.push(window.setTimeout(() => {
      const target = formRef.current?.querySelector('[data-error-active="true"]')
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 80))
    timers.push(window.setTimeout(() => {
      setHighlightedErrorKey('')
    }, 2600))
    return () => timers.forEach(timer => window.clearTimeout(timer))
  }, [firstErrorKey, errorFields, error?.message, configExpanded, onToggleConfig])

  const errorScrollAttrs = (key) => ({
    'data-error-key': key,
    'data-error-active': (fieldErrors[key] || (key === 'api_error' && error)) ? 'true' : undefined,
  })

  const errorHighlightClass = (key) => (
    `scroll-mt-24 rounded-lg transition-shadow ${
      highlightedErrorKey === key ? 'ring-2 ring-red-300 ring-offset-2' : ''
    }`
  )

  const inputClassName = (key, baseClassName) => (
    `${baseClassName} ${
      fieldErrors[key]
        ? 'border-red-300 bg-red-50 focus:border-red-500 focus:ring-red-100'
        : ''
    }`
  )

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
      {
        name: 'max_child_subsections_per_section',
        minKey: 'textbook.form.childSubsectionTooLow',
        maxKey: 'textbook.form.childSubsectionTooHigh',
        warnLowKey: 'textbook.form.childSubsectionLowWarning',
        warnHighKey: 'textbook.form.childSubsectionHighWarning',
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

    if (data.target_pages === null || data.target_pages === undefined || data.target_pages === '') {
      errors.target_pages = t('textbook.form.targetPagesRequired')
    } else if (Number.isNaN(data.target_pages)) {
      errors.target_pages = t('textbook.form.numberInteger')
    } else if (data.target_pages < 5) {
      errors.target_pages = t('textbook.form.targetPagesTooLow', { min: 5 })
    } else if (data.target_pages > 2000) {
      errors.target_pages = t('textbook.form.targetPagesTooHigh', { max: 2000 })
    }

    if (!errors.target_pages) {
      const compatibility = getPageCompatibility(data)
      if (compatibility) {
        if (compatibility.bodyPages <= 0 || data.target_pages < compatibility.minTotalPages) {
          errors.target_pages = t('textbook.form.targetPagesIncompatible', {
            min: compatibility.minTotalPages,
            chapters: compatibility.chapterCount,
            sections: compatibility.subsectionCount,
          })
        } else if (data.target_pages < compatibility.recommendedTotalPages) {
          warnings.push(t('textbook.form.targetPagesTightWarning', {
            recommended: compatibility.recommendedTotalPages,
            chapters: compatibility.chapterCount,
            sections: compatibility.subsectionCount,
          }))
        }
      }
    }

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

  const queueSubmitConfirmation = (data, warnings = []) => {
    setConfirmWarnings([
      t('textbook.form.reviewGateNotice'),
      ...(warnings || []),
    ])
    setPendingSubmitData(data)
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
      max_child_subsections_per_section: parseIntegerInput(formData.max_child_subsections_per_section),
      target_pages: parseIntegerInput(formData.target_pages),
      page_plan_confirmed: Boolean(formData.page_plan_confirmed),
      fill_missing_child_subsections: false,
    }
    let structuredMissingChildren = []
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
      const inferredDepth = inferStructureDepth(initialStructure)
      structuredMissingChildren = getMissingChildSections(initialStructure)
      const structureForValidation = {
        ...initialStructure,
        structure_depth: structuredMissingChildren.length > 0 ? 'level1' : inferredDepth,
      }
      const structureError = validateStructure(structureForValidation, t)
      if (structureError) {
        setFieldErrors({ initial_structure: structureError })
        return
      }
      const pageBudgetIssues = getChapterPageBudgetIssues(initialStructure.chapters, t)
      if (pageBudgetIssues.length > 0) {
        setFieldErrors({ initial_structure: pageBudgetIssues[0] })
        return
      }
      const chapterCount = initialStructure.chapters.length
      const maxSubsectionCount = Math.max(
        ...initialStructure.chapters.map(chapter => chapter.subsections.length)
      )
      const maxChildCount = Math.max(
        1,
        ...initialStructure.chapters.flatMap(chapter => (
          (chapter.subsections || []).map(subsection => (subsection.children || []).length || 1)
        ))
      )
      submitData.initial_structure_markdown = serializeStructureToMarkdown(initialStructure)
      submitData.structure_depth = inferredDepth
      submitData.initial_structure = normalizeStructureForApi(
        { ...initialStructure, structure_depth: inferredDepth },
        submitData.target_pages,
      )
      submitData.num_chapters = chapterCount
      submitData.max_subsections_per_chapter = maxSubsectionCount
      submitData.max_child_subsections_per_section = maxChildCount
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

    const combinedWarnings = [...topicWarnings, ...warnings]

    if (
      submitData.planning_mode === 'structured' &&
      structuredMissingChildren.length > 0
    ) {
      setMissingChildSections(structuredMissingChildren)
      setPendingMissingChildData({
        submitData,
        warnings: combinedWarnings,
      })
      return
    }

    if (
      submitData.planning_mode === 'structured' &&
      hasMissingStructurePageTargets(initialStructure)
    ) {
      setPendingStructuredPageData({
        submitData,
        warnings: combinedWarnings,
      })
      return
    }

    queueSubmitConfirmation(submitData, combinedWarnings)
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

  const setStructureDepth = (depth) => {
    setFormData(prev => ({
      ...prev,
      structure_depth: depth,
    }))
    setInitialStructure(createDefaultStructure(t, depth))
    if (fieldErrors.initial_structure) {
      setFieldErrors(prev => {
        const next = { ...prev }
        delete next.initial_structure
        return next
      })
    }
  }

  const clearInitialStructure = () => {
    setInitialStructure({
      structure_depth: formData.structure_depth || 'level1',
      chapters: [],
    })
    setMissingChildSections([])
    setStructureUpload(prev => ({
      ...prev,
      loading: false,
      fileName: '',
      warnings: [],
      unparsedItems: [],
      error: '',
    }))
    setFieldErrors(prev => {
      const next = { ...prev }
      delete next.initial_structure
      return next
    })
  }

  const handleStructureFileUpload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    const allowed = ['.docx', '.pdf']
    const lowerName = file.name.toLowerCase()
    if (!allowed.some(ext => lowerName.endsWith(ext))) {
      setStructureUpload({
        loading: false,
        fileName: file.name,
        warnings: [],
        unparsedItems: [],
        error: t('textbook.form.structureUploadUnsupported'),
      })
      return
    }

    const payload = new FormData()
    payload.append('file', file)
    setStructureUpload({
      loading: true,
      fileName: file.name,
      warnings: [],
      unparsedItems: [],
      error: '',
    })

    try {
      const response = await textbooksAPI.parseStructureFile(payload)
      const parsed = response.data || {}
      const curriculum = parsed.curriculum || {}
      const nextStructure = {
        ...curriculum,
        structure_depth: parsed.structure_depth || inferStructureDepth(curriculum),
      }
      setInitialStructure(nextStructure)
      setMissingChildSections([])
      setFormData(prev => ({
        ...prev,
        planning_mode: 'structured',
        structure_depth: nextStructure.structure_depth || 'level1',
        target_pages: parsed.target_pages ? String(parsed.target_pages) : prev.target_pages,
        topic: !prev.topic.trim() && parsed.topic ? parsed.topic : prev.topic,
      }))
      setFieldErrors(prev => {
        const next = { ...prev }
        delete next.initial_structure
        if (parsed.target_pages) {
          delete next.target_pages
        }
        return next
      })
      setStructureUpload({
        loading: false,
        fileName: file.name,
        warnings: parsed.warnings || [],
        unparsedItems: parsed.unparsed_items || [],
        error: '',
      })
    } catch (err) {
      const detail = err.response?.data?.detail
      setStructureUpload({
        loading: false,
        fileName: file.name,
        warnings: [],
        unparsedItems: [],
        error: typeof detail === 'string'
          ? detail
          : t('textbook.form.structureUploadError'),
      })
    }
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
                <span className="text-xs text-gray-500">{t('textbook.form.targetPages')}</span>
                <span className="font-semibold text-gray-800">
                  {submittedConfig?.target_pages || formData.target_pages}
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
    <form ref={formRef} onSubmit={handleSubmit} className="space-y-4" noValidate>
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

      {formData.planning_mode === 'auto' && (
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('textbook.form.structureDepth')}
        </label>
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-1">
          {[
            ['level1', 'textbook.form.structureDepthLevel1'],
            ['level2', 'textbook.form.structureDepthLevel2'],
          ].map(([value, labelKey]) => (
            <button
              key={value}
              type="button"
              onClick={() => setStructureDepth(value)}
              disabled={loading}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                formData.structure_depth === value
                  ? 'bg-white text-blue-700 shadow-sm ring-1 ring-blue-200'
                  : 'text-gray-600 hover:bg-white/70'
              }`}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-gray-500">
          {formData.structure_depth === 'level2'
            ? t('textbook.form.structureDepthLevel2Hint')
            : t('textbook.form.structureDepthLevel1Hint')}
        </p>
      </div>
      )}

      <div
        {...errorScrollAttrs('target_pages')}
        className={errorHighlightClass('target_pages')}
      >
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('textbook.form.targetPages')} <span className="text-red-500">*</span>
        </label>
        <input
          type="number"
          name="target_pages"
          value={formData.target_pages}
          onChange={handleChange}
          step={1}
          min={5}
          className={inputClassName(
            'target_pages',
            'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100',
          )}
          disabled={loading}
          required
        />
        {fieldErrors.target_pages && (
          <p className="mt-1 text-xs text-red-600">{fieldErrors.target_pages}</p>
        )}
        <p className="mt-1 text-xs text-gray-500">
          {t('textbook.form.targetPagesHint')}
        </p>
      </div>

      {formData.planning_mode === 'structured' && (
        <div
          {...errorScrollAttrs('initial_structure')}
          className={`space-y-3 rounded-lg border p-4 ${errorHighlightClass('initial_structure')} ${
            fieldErrors.initial_structure
              ? 'border-red-200 bg-red-50/50'
              : 'border-blue-100 bg-blue-50/40'
          }`}
        >
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
          <div className="rounded-lg border border-gray-200 bg-white p-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-gray-900">
                  {t('textbook.form.structureUploadTitle')}
                </p>
                <p className="mt-1 text-xs text-gray-500">
                  {t('textbook.form.structureUploadHint')}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={clearInitialStructure}
                  disabled={loading || structureUpload.loading}
                  className="inline-flex items-center justify-center rounded-lg border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t('textbook.form.structureClearButton')}
                </button>
                <label className={`inline-flex cursor-pointer items-center justify-center rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                  structureUpload.loading || loading
                    ? 'cursor-not-allowed border-gray-200 bg-gray-100 text-gray-400'
                    : 'border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100'
                }`}>
                  {structureUpload.loading
                    ? t('textbook.form.structureUploadReading')
                    : t('textbook.form.structureUploadButton')}
                  <input
                    type="file"
                    accept=".docx,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf"
                    className="sr-only"
                    onChange={handleStructureFileUpload}
                    disabled={loading || structureUpload.loading}
                  />
                </label>
              </div>
            </div>
            {structureUpload.fileName && !structureUpload.error && (
              <p className="mt-2 text-xs text-gray-500">
                {t('textbook.form.structureUploadFile', { file: structureUpload.fileName })}
              </p>
            )}
            {structureUpload.error && (
              <p className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
                {structureUpload.error}
              </p>
            )}
            {structureUpload.warnings.length > 0 && (
              <div className="mt-2 space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {structureUpload.warnings.map((warning, index) => (
                  <p key={index}>{warning}</p>
                ))}
              </div>
            )}
            {structureUpload.unparsedItems.length > 0 && (
              <details className="mt-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                <summary className="cursor-pointer font-medium text-gray-700">
                  {t('textbook.form.structureUploadUnparsed', {
                    count: structureUpload.unparsedItems.length,
                  })}
                </summary>
                <ul className="mt-2 space-y-1">
                  {structureUpload.unparsedItems.slice(0, 10).map((item, index) => (
                    <li key={index}>- {item}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          <CurriculumStructureEditor
            value={initialStructure}
            onChange={(next) => {
              setInitialStructure(next)
              if (missingChildSections.length > 0) {
                setMissingChildSections([])
              }
              if (fieldErrors.initial_structure) {
                setFieldErrors(prev => {
                  const updated = { ...prev }
                  delete updated.initial_structure
                  return updated
                })
              }
            }}
            disabled={loading}
            structureDepth={formData.structure_depth}
            allowChildControls={formData.planning_mode === 'structured'}
            missingChildSections={missingChildSections}
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
            <div
              {...errorScrollAttrs('num_chapters')}
              className={errorHighlightClass('num_chapters')}
            >
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('textbook.form.chapters')}
              </label>
              <input
                type="number"
                name="num_chapters"
                value={formData.num_chapters}
                onChange={handleChange}
                step={1}
                className={inputClassName(
                  'num_chapters',
                  'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                )}
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

                <div
                  {...errorScrollAttrs('source_preferences')}
                  className={errorHighlightClass('source_preferences')}
                >
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
                    className={inputClassName(
                      'source_preferences',
                      'w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500',
                    )}
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

          {formData.planning_mode === 'auto' && (
            <div
              {...errorScrollAttrs('max_subsections_per_chapter')}
              className={errorHighlightClass('max_subsections_per_chapter')}
            >
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('textbook.form.maxSubsections')}
              </label>
              <input
                type="number"
                name="max_subsections_per_chapter"
                value={formData.max_subsections_per_chapter}
                onChange={handleChange}
                step={1}
                className={inputClassName(
                  'max_subsections_per_chapter',
                  'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                )}
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

          {formData.planning_mode === 'auto' && formData.structure_depth === 'level2' && (
            <div
              {...errorScrollAttrs('max_child_subsections_per_section')}
              className={errorHighlightClass('max_child_subsections_per_section')}
            >
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('textbook.form.maxChildSubsections')}
              </label>
              <input
                type="number"
                name="max_child_subsections_per_section"
                value={formData.max_child_subsections_per_section}
                onChange={handleChange}
                step={1}
                className={inputClassName(
                  'max_child_subsections_per_section',
                  'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                )}
                disabled={loading}
              />
              {fieldErrors.max_child_subsections_per_section && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.max_child_subsections_per_section}</p>
              )}
              <p className="mt-1 text-xs text-gray-500">
                {t('textbook.form.maxChildSubsectionsHint')}
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
        <div
          {...errorScrollAttrs('api_error')}
          className={`p-4 bg-red-50 border border-red-200 rounded-lg ${errorHighlightClass('api_error')}`}
        >
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

      {pendingMissingChildData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
            onClick={() => setPendingMissingChildData(null)}
          />
          <div className="relative w-full max-w-lg mx-4 bg-white rounded-2xl shadow-2xl p-6">
            <h3 className="text-xl font-bold text-gray-900 text-center mb-2">
              {t('textbook.form.missingChildSectionsTitle')}
            </h3>
            <p className="text-sm text-gray-600 text-center mb-4">
              {t('textbook.form.missingChildSectionsDescription')}
            </p>
            <div className="mb-4 max-h-32 overflow-y-auto rounded-lg border border-red-100 bg-red-50 p-3 text-xs text-red-700">
              {missingChildSections.map(item => (
                <div key={item.label}>
                  {item.label}{item.title ? ` - ${item.title}` : ''}
                </div>
              ))}
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 mb-6">
              {t('textbook.form.missingChildSectionsNote')}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setPendingMissingChildData(null)
                  setFieldErrors({
                    initial_structure: t('textbook.form.missingChildSectionsManualHint'),
                  })
                }}
                className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-300 transition-colors"
              >
                {t('textbook.form.missingChildSectionsManual')}
              </button>
              <button
                type="button"
                onClick={() => {
                  const pending = pendingMissingChildData
                  setPendingMissingChildData(null)
                  if (!pending?.submitData) return
                  const submitWithFill = {
                    ...pending.submitData,
                    structure_depth: 'level2',
                    fill_missing_child_subsections: true,
                  }
                  queueSubmitConfirmation(submitWithFill, pending.warnings || [])
                }}
                className="flex-1 px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                {t('textbook.form.missingChildSectionsAutoFill')}
              </button>
            </div>
          </div>
        </div>
      )}

      {pendingStructuredPageData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
            onClick={() => setPendingStructuredPageData(null)}
          />
          <div className="relative bg-white rounded-lg shadow-2xl max-w-lg w-full mx-4 p-6">
            <div className="flex items-center justify-center w-12 h-12 mx-auto mb-4 bg-amber-100 rounded-full">
              <svg className="w-6 h-6 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-6h6v6m-9 4h12a2 2 0 002-2V7.828a2 2 0 00-.586-1.414l-3.828-3.828A2 2 0 0014.172 2H6a2 2 0 00-2 2v15a2 2 0 002 2z" />
              </svg>
            </div>
            <h3 className="text-xl font-bold text-gray-900 text-center mb-2">
              {t('textbook.form.structuredMissingPagesTitle')}
            </h3>
            <p className="text-sm text-gray-600 text-center mb-4">
              {t('textbook.form.structuredMissingPagesDescription')}
            </p>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 mb-6">
              {t('textbook.form.structuredMissingPagesNote')}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setPendingStructuredPageData(null)}
                className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-300 transition-colors"
              >
                {t('textbook.form.structuredMissingPagesReview')}
              </button>
              <button
                type="button"
                onClick={() => {
                  const pending = pendingStructuredPageData
                  setPendingStructuredPageData(null)
                  if (!pending?.submitData) return
                  queueSubmitConfirmation(pending.submitData, pending.warnings || [])
                }}
                className="flex-1 px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                {t('textbook.form.structuredMissingPagesAutoFill')}
              </button>
            </div>
          </div>
        </div>
      )}

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
