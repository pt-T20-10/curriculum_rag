import { useEffect, useMemo, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { textbooksAPI } from '../../api/textbooks'
import { getChapterPageBudgetIssues } from '../../utils/curriculumStructure'
import { Button } from '../common/Button'

function pageValueForSubmit(value, fallback) {
  if (value !== '' && value !== undefined && value !== null) {
    return parseInt(value, 10)
  }
  if (fallback !== '' && fallback !== undefined && fallback !== null) {
    const parsed = Math.round(Number(fallback))
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
  }
  return undefined
}

function numericPage(value, fallback) {
  const parsed = pageValueForSubmit(value, fallback)
  return Number.isFinite(parsed) ? parsed : null
}

export function CurriculumEditor({
  curriculum,
  textbookId,
  onConfirm,
  onReset,
  confirming = false,
  generationMode = 'system_credit_billing',
}) {
  const { t } = useTranslation()
  const [editedCurriculum, setEditedCurriculum] = useState(curriculum)
  const structureDepth = editedCurriculum?.structure_depth || curriculum?.structure_depth || 'level1'
  const [deletedSubs, setDeletedSubs] = useState(new Set())
  const [deletedChapters, setDeletedChapters] = useState(new Set()) // ⭐ NEW
  const [newSubs, setNewSubs] = useState({}) // { chapterIdx: [titles...] }
  const [validationError, setValidationError] = useState('')
  const [creditEstimate, setCreditEstimate] = useState(null)
  const [estimateError, setEstimateError] = useState('')
  const [estimatingCredits, setEstimatingCredits] = useState(false)
  const [pendingConfirmCurriculum, setPendingConfirmCurriculum] = useState(null)
  const usesUserProvidedKeys = generationMode === 'user_provided_api_keys'

  // Handle chapter title change
  const handleChapterChange = (chapterIdx, newTitle) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].title = newTitle
    setEditedCurriculum(updated)
  }

  const handleChapterPagesChange = (chapterIdx, value) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].target_pages = value
    setEditedCurriculum(updated)
  }

  // Handle subsection title change
  const handleSubChange = (chapterIdx, subIdx, newTitle) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].subsections[subIdx].title = newTitle
    setEditedCurriculum(updated)
  }

  const handleSubPagesChange = (chapterIdx, subIdx, value) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].subsections[subIdx].target_pages = value
    setEditedCurriculum(updated)
  }

  const handleChildChange = (chapterIdx, subIdx, childIdx, newTitle) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].subsections[subIdx].children[childIdx].title = newTitle
    setEditedCurriculum(updated)
  }

  const handleChildPagesChange = (chapterIdx, subIdx, childIdx, value) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].subsections[subIdx].children[childIdx].target_pages = value
    setEditedCurriculum(updated)
  }

  const handleAddChild = (chapterIdx, subIdx) => {
    const updated = { ...editedCurriculum }
    const subsection = updated.chapters[chapterIdx].subsections[subIdx]
    const nextNumber = (subsection.children || []).length + 1
    subsection.children = [
      ...(subsection.children || []),
      {
        title: t('textbook.structure.defaultChildSubsection', {
          chapter: chapterIdx + 1,
          section: subIdx + 1,
          number: nextNumber,
        }),
        target_pages: '',
      },
    ]
    setEditedCurriculum(updated)
  }

  const handleDeleteChild = (chapterIdx, subIdx, childIdx) => {
    const updated = { ...editedCurriculum }
    const subsection = updated.chapters[chapterIdx].subsections[subIdx]
    subsection.children = (subsection.children || []).filter((_, idx) => idx !== childIdx)
    setEditedCurriculum(updated)
  }

  const handleAddChapter = () => {
    const chapterNumber = editedCurriculum.chapters.length + 1
    const chapterTitle = t('textbook.curriculum.newChapterTitle', { number: chapterNumber })
    const subsectionTitle = t('textbook.curriculum.newChapterSubsection', { number: chapterNumber })
    const subsection = {
      title: subsectionTitle,
      description: `Content about ${subsectionTitle}`,
      search_query: subsectionTitle,
      section_type: 'medium',
      target_pages: '',
    }
    if (structureDepth === 'level2') {
      subsection.children = [{
        title: t('textbook.structure.defaultChildSubsection', {
          chapter: chapterNumber,
          section: 1,
          number: 1,
        }),
        target_pages: '',
      }]
    }
    setEditedCurriculum({
      ...editedCurriculum,
      chapters: [
        ...editedCurriculum.chapters,
        {
          title: chapterTitle,
          subsections: [subsection],
        },
      ],
    })
  }

  // ⭐ NEW - Delete entire chapter
  const handleDeleteChapter = (chapterIdx) => {
    setDeletedChapters(new Set([...deletedChapters, chapterIdx]))
  }

  // ⭐ NEW - Restore deleted chapter
  const handleRestoreChapter = (chapterIdx) => {
    const updated = new Set(deletedChapters)
    updated.delete(chapterIdx)
    setDeletedChapters(updated)
  }

  // Delete subsection
  const handleDeleteSub = (chapterIdx, subIdx) => {
    const key = `${chapterIdx}-${subIdx}`
    setDeletedSubs(new Set([...deletedSubs, key]))
  }

  // Delete new subsection
  const handleDeleteNewSub = (chapterIdx, newSubIdx) => {
    const updated = { ...newSubs }
    updated[chapterIdx].splice(newSubIdx, 1)
    setNewSubs(updated)
  }

  // Add new subsection
  const handleAddSub = (chapterIdx) => {
    const updated = { ...newSubs }
    if (!updated[chapterIdx]) {
      updated[chapterIdx] = []
    }
    const currentCount = editedCurriculum.chapters[chapterIdx].subsections.length
    const newCount = updated[chapterIdx].length
    const subsection = {
      title: `${t('textbook.contentSidebar.subsections')} ${chapterIdx + 1}.${currentCount + newCount + 1}`,
      target_pages: '',
    }
    if (structureDepth === 'level2') {
      subsection.children = [{
        title: t('textbook.structure.defaultChildSubsection', {
          chapter: chapterIdx + 1,
          section: currentCount + newCount + 1,
          number: 1,
        }),
        target_pages: '',
      }]
    }
    updated[chapterIdx].push(subsection)
    setNewSubs(updated)
  }

  const handleNewSubChange = (chapterIdx, newSubIdx, patch) => {
    const updated = { ...newSubs }
    const current = typeof updated[chapterIdx][newSubIdx] === 'string'
      ? { title: updated[chapterIdx][newSubIdx], target_pages: '' }
      : updated[chapterIdx][newSubIdx]
    updated[chapterIdx][newSubIdx] = { ...current, ...patch }
    setNewSubs(updated)
  }

  const handleAddNewChild = (chapterIdx, newSubIdx) => {
    const updated = { ...newSubs }
    const current = typeof updated[chapterIdx][newSubIdx] === 'string'
      ? { title: updated[chapterIdx][newSubIdx], target_pages: '', children: [] }
      : updated[chapterIdx][newSubIdx]
    const childCount = (current.children || []).length
    const sectionNumber = editedCurriculum.chapters[chapterIdx].subsections.length + newSubIdx + 1
    updated[chapterIdx][newSubIdx] = {
      ...current,
      children: [
        ...(current.children || []),
        {
          title: t('textbook.structure.defaultChildSubsection', {
            chapter: chapterIdx + 1,
            section: sectionNumber,
            number: childCount + 1,
          }),
          target_pages: '',
        },
      ],
    }
    setNewSubs(updated)
  }

  const handleNewChildChange = (chapterIdx, newSubIdx, childIdx, patch) => {
    const updated = { ...newSubs }
    const current = typeof updated[chapterIdx][newSubIdx] === 'string'
      ? { title: updated[chapterIdx][newSubIdx], target_pages: '', children: [] }
      : updated[chapterIdx][newSubIdx]
    updated[chapterIdx][newSubIdx] = {
      ...current,
      children: (current.children || []).map((child, idx) => (
        idx === childIdx ? { ...child, ...patch } : child
      )),
    }
    setNewSubs(updated)
  }

  const handleDeleteNewChild = (chapterIdx, newSubIdx, childIdx) => {
    const updated = { ...newSubs }
    const current = typeof updated[chapterIdx][newSubIdx] === 'string'
      ? { title: updated[chapterIdx][newSubIdx], target_pages: '', children: [] }
      : updated[chapterIdx][newSubIdx]
    updated[chapterIdx][newSubIdx] = {
      ...current,
      children: (current.children || []).filter((_, idx) => idx !== childIdx),
    }
    setNewSubs(updated)
  }

  // Build final curriculum for submit
  const finalCurriculum = useMemo(() => {
    const finalChapters = editedCurriculum.chapters
      .map((chapter, chIdx) => {
        // ⭐ Skip deleted chapters
        if (deletedChapters.has(chIdx)) return null

        const chapterTitle = chapter.title.trim()
        if (!chapterTitle) return { invalid: true }

        // Filter out deleted subsections
        const activeSubs = chapter.subsections
          .map((sub, subIdx) => {
            if (deletedSubs.has(`${chIdx}-${subIdx}`)) return null
            const title = sub.title.trim()
            if (!title) return { invalid: true }
            const section = {
              title,
              description: sub.description?.trim() || `Content about ${title}`,
              search_query: sub.search_query?.trim() || title,
              section_type: sub.section_type || 'medium',
              target_pages: pageValueForSubmit(sub.target_pages, sub.estimated_pages),
            }
            if (structureDepth === 'level2') {
              section.children = (sub.children || []).map(child => {
                const childTitle = String(child.title || '').trim()
                if (!childTitle) return { invalid: true }
                return {
                  title: childTitle,
                  description: child.description?.trim() || `Content about ${childTitle}`,
                  search_query: child.search_query?.trim() || childTitle,
                  section_type: child.section_type || sub.section_type || 'medium',
                  target_pages: pageValueForSubmit(child.target_pages, child.estimated_pages),
                }
              })
              if (!section.children.length) return { invalid: true, missingChild: true }
            }
            return section
          })
          .filter(Boolean)

        if (activeSubs.some(sub => sub.missingChild)) return { invalid: true, missingChild: true }
        if (activeSubs.some(sub => sub.invalid || (sub.children || []).some(child => child.invalid))) return { invalid: true }

        // Add new subsections
        const newSubsForChapter = newSubs[chIdx] || []
        const newSubObjects = newSubsForChapter.map(item => {
          const cleanTitle = String(typeof item === 'string' ? item : item.title || '').trim()
          if (!cleanTitle) return { invalid: true }
          const newSubObject = {
            title: cleanTitle,
            description: `Content about ${cleanTitle}`,
            search_query: cleanTitle,
            section_type: 'medium',
            target_pages: typeof item === 'string'
              ? undefined
              : pageValueForSubmit(item.target_pages),
          }
          if (structureDepth === 'level2') {
            const children = typeof item === 'string' ? [] : (item.children || [])
            newSubObject.children = children.map(child => {
              const childTitle = String(child.title || '').trim()
              if (!childTitle) return { invalid: true }
              return {
                title: childTitle,
                description: `Content about ${childTitle}`,
                search_query: childTitle,
                section_type: 'medium',
                target_pages: pageValueForSubmit(child.target_pages),
              }
            })
            if (!newSubObject.children.length) {
              return { invalid: true, missingChild: true }
            }
            if (newSubObject.children.some(child => child.invalid)) {
              return { invalid: true }
            }
          }
          return newSubObject
        })

        if (newSubObjects.some(sub => sub.missingChild)) return { invalid: true, missingChild: true }
        if (newSubObjects.some(sub => sub.invalid)) return { invalid: true }

        return {
          title: chapterTitle,
          target_pages: pageValueForSubmit(chapter.target_pages, chapter.estimated_pages),
          subsections: [...activeSubs, ...newSubObjects],
        }
      })
      .filter(Boolean) // Remove nulls (deleted chapters and empty chapters)

    if (finalChapters.some(ch => ch.missingChild)) {
      return { invalid: true, missingChild: true }
    }
    if (finalChapters.some(ch => ch.invalid)) {
      return { invalid: true }
    }

    const compactChapters = finalChapters
      .filter(ch => ch.subsections.length > 0) // Remove empty chapters

    if (compactChapters.length === 0) {
      return { invalid: true, empty: true }
    }

    return {
      topic: editedCurriculum.topic,
      structure_depth: structureDepth,
      target_pages: editedCurriculum.target_pages === '' || editedCurriculum.target_pages === undefined
        ? undefined
        : parseInt(editedCurriculum.target_pages, 10),
      chapters: compactChapters,
    }
  }, [deletedChapters, deletedSubs, editedCurriculum, newSubs, structureDepth])

  const chapterPageBudgetIssues = useMemo(() => {
    if (finalCurriculum.invalid) return []
    return getChapterPageBudgetIssues(finalCurriculum.chapters, t)
  }, [finalCurriculum, t])

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(async () => {
      if (!textbookId || finalCurriculum.invalid) {
        setCreditEstimate(null)
        setEstimateError('')
        setEstimatingCredits(false)
        return
      }

      setCreditEstimate(null)
      setEstimateError('')
      setEstimatingCredits(true)
      try {
        const response = await textbooksAPI.estimateCredits(textbookId, finalCurriculum)
        if (!cancelled) {
          setCreditEstimate(response.data)
          setEstimateError('')
        }
      } catch (err) {
        console.error('Estimate credits error:', err)
        if (!cancelled) {
          setCreditEstimate(null)
          setEstimateError(t('textbook.curriculum.estimateError'))
        }
      } finally {
        if (!cancelled) {
          setEstimatingCredits(false)
        }
      }
    }, !textbookId || finalCurriculum.invalid ? 0 : 400)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [finalCurriculum, textbookId, t])

  const handleConfirm = () => {
    if (finalCurriculum.invalid) {
      setValidationError(
        finalCurriculum.empty
          ? t('textbook.curriculum.emptyCurriculumError')
          : finalCurriculum.missingChild
            ? t('textbook.curriculum.level2MissingChildrenError')
          : t('textbook.curriculum.blankTitleError')
      )
      return
    }
    if (chapterPageBudgetIssues.length > 0) {
      setValidationError(chapterPageBudgetIssues[0])
      return
    }
    if (creditEstimate?.page_validation?.severity === 'error') {
      setValidationError(
        creditEstimate.page_validation.ai_note || t('textbook.curriculum.pageValidationError')
      )
      return
    }
    setValidationError('')
    setPendingConfirmCurriculum(finalCurriculum)
  }

  const handleConfirmModalClose = () => {
    if (!confirming) {
      setPendingConfirmCurriculum(null)
    }
  }

  const handleConfirmModalSubmit = () => {
    if (!pendingConfirmCurriculum || estimatingCredits) {
      return
    }
    onConfirm(
      pendingConfirmCurriculum,
      creditEstimate?.page_validation?.severity === 'warning',
    )
  }

  const handleReset = () => {
    if (onReset) onReset()
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-lg">
        <h3 className="font-semibold text-blue-900 mb-1">
          ✏️ {t('textbook.curriculum.title')}
        </h3>
        <p className="text-sm text-blue-700">
          <Trans i18nKey="textbook.curriculum.description" components={{ strong: <strong /> }} />
        </p>
      </div>

      {validationError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm font-medium text-red-700">⚠️ {validationError}</p>
        </div>
      )}

      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <label className="block text-sm font-semibold text-gray-800 mb-2">
          {t('textbook.form.targetPages')}
        </label>
        <input
          type="number"
          min="5"
          step="1"
          value={editedCurriculum.target_pages ?? ''}
          onChange={(e) => setEditedCurriculum({
            ...editedCurriculum,
            target_pages: e.target.value,
          })}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <p className="mt-1 text-xs text-gray-500">
          {t('textbook.form.targetPagesHint')}
        </p>
      </div>

      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-emerald-900">
              {usesUserProvidedKeys ? t('textbook.curriculum.userKeysNoCreditTitle') : t('textbook.curriculum.creditEstimateTitle')}
            </p>
            {creditEstimate ? (
              <p className="text-xs text-emerald-700 mt-1">
                {usesUserProvidedKeys
                  ? t('textbook.curriculum.userKeysNoCreditDescription')
                  : t('textbook.curriculum.creditEstimateDetails', {
                    chapters: creditEstimate.total_chapters,
                    subsections: creditEstimate.total_subsections,
                    images: creditEstimate.enable_images ? t('app.yes') : t('app.no'),
                    level: creditEstimate.content_level,
                  })}
              </p>
            ) : (
              <p className="text-xs text-emerald-700 mt-1">
                {estimatingCredits
                  ? t('textbook.curriculum.estimatingCredits')
                  : estimateError || t('textbook.curriculum.creditEstimatePending')}
              </p>
            )}
          </div>
          <div className="text-right">
            {usesUserProvidedKeys ? (
              <p className="text-sm font-bold text-emerald-700">
                0 credit
              </p>
            ) : creditEstimate?.is_admin_free ? (
              <p className="text-sm font-bold text-emerald-700">
                {t('textbook.curriculum.adminFree')}
              </p>
            ) : (
              <p className="text-2xl font-bold text-emerald-800">
                {creditEstimate ? creditEstimate.credits_required : '...'}
              </p>
            )}
            {!usesUserProvidedKeys && !creditEstimate?.is_admin_free && (
              <p className="text-xs text-emerald-700">credits</p>
            )}
          </div>
        </div>
      </div>

      {creditEstimate?.page_validation && (
        <div className={`rounded-lg border p-4 ${
          creditEstimate.page_validation.severity === 'error'
            ? 'border-red-200 bg-red-50'
            : creditEstimate.page_validation.severity === 'warning'
              ? 'border-amber-200 bg-amber-50'
              : 'border-blue-200 bg-blue-50'
        }`}>
          <p className="text-sm font-semibold text-gray-900">
            {t('textbook.curriculum.pageEstimateTitle')}
          </p>
          <p className="mt-1 text-xs text-gray-700">
            {t('textbook.curriculum.pageEstimateDetails', {
              estimated: creditEstimate.page_validation.estimated_total_pages || '...',
              target: creditEstimate.page_validation.target_pages || '...',
            })}
          </p>
          {creditEstimate.page_validation.ai_note && (
            <p className="mt-2 text-xs text-gray-700">
              {creditEstimate.page_validation.ai_note}
            </p>
          )}
          {[
            ...(creditEstimate.page_validation.errors || []),
            ...(creditEstimate.page_validation.warnings || []),
          ].map((item, index) => (
            <p key={index} className="mt-1 text-xs text-gray-700">
              {item}
            </p>
          ))}
        </div>
      )}

      {/* Chapters */}
      {editedCurriculum.chapters.map((chapter, chIdx) => {
        const isDeleted = deletedChapters.has(chIdx)
        
        // ⭐ Deleted chapter placeholder
        if (isDeleted) {
          return (
            <div 
              key={chIdx} 
              className="bg-red-50 border-2 border-red-300 rounded-lg p-4 opacity-70"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">🗑️</span>
                  <div>
                    <p className="font-semibold text-red-800 line-through">
                      {t('textbook.curriculum.chapter', { number: chIdx + 1 })}: {chapter.title}
                    </p>
                    <p className="text-xs text-red-600 mt-1">
                      {t('textbook.curriculum.deletedChapter')}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleRestoreChapter(chIdx)}
                  className="px-4 py-2 text-sm bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                >
                  ↩️ {t('textbook.curriculum.restore')}
                </button>
              </div>
            </div>
          )
        }

        const activeSubs = chapter.subsections.filter(
          (_, subIdx) => !deletedSubs.has(`${chIdx}-${subIdx}`)
        )
        const newSubsForChapter = newSubs[chIdx] || []
        const totalVisible = activeSubs.length + newSubsForChapter.length
        const chapterPages = numericPage(chapter.target_pages, chapter.estimated_pages)
        const allocatedPages = [
          ...activeSubs.map(sub => numericPage(sub.target_pages, sub.estimated_pages)),
          ...newSubsForChapter.map(item => (
            typeof item === 'string' ? null : numericPage(item.target_pages)
          )),
        ].reduce((sum, pages) => sum + (pages || 0), 0)
        const isOverBudget = chapterPages && allocatedPages > chapterPages

        return (
          <div key={chIdx} className={`bg-white rounded-lg border p-4 ${
            isOverBudget ? 'border-red-300' : 'border-gray-200'
          }`}>
            {/* ⭐ Chapter header with delete button */}
            <div className="mb-3 flex items-start gap-3">
              <div className="flex-1">
                <label className="block text-sm font-medium text-blue-700 mb-2">
                  📖 {t('textbook.curriculum.chapter', { number: chIdx + 1 })}
                </label>
                <input
                  type="text"
                  value={chapter.title}
                  onChange={(e) => handleChapterChange(chIdx, e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              <div className="w-28 shrink-0">
                <label className="block text-sm font-medium text-gray-600 mb-2">
                  {t('textbook.curriculum.pages')}
                </label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={chapter.target_pages ?? (Math.round(chapter.estimated_pages || 0) || '')}
                  onChange={(e) => handleChapterPagesChange(chIdx, e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              
              {/* ⭐ Delete chapter button */}
              <button
                onClick={() => handleDeleteChapter(chIdx)}
                className="mt-6 px-3 py-2 text-red-600 hover:bg-red-50 border border-red-300 rounded-lg flex items-center gap-2"
                title={t('textbook.curriculum.deleteChapterTitle')}
              >
                <span>🗑️</span>
                <span className="text-sm">{t('textbook.curriculum.deleteChapter')}</span>
              </button>
            </div>

            {/* Warning if empty */}
            {totalVisible === 0 && (
              <div className="bg-yellow-50 border border-yellow-200 rounded p-2 mb-3">
                <p className="text-xs text-yellow-700">
                  ⚠️ {t('textbook.curriculum.emptyChapter', { number: chIdx + 1 })}
                </p>
              </div>
            )}

            {chapterPages && (
              <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                isOverBudget
                  ? 'border-red-200 bg-red-50 text-red-700'
                  : 'border-blue-100 bg-blue-50 text-blue-700'
              }`}>
                {t('textbook.curriculum.pageAllocationStatus', {
                  allocated: allocatedPages,
                  target: chapterPages,
                })}
                {isOverBudget && (
                  <span className="ml-2 font-semibold">
                    {t('textbook.structure.errors.subsectionPagesExceedChapter', {
                      chapter: chIdx + 1,
                      allocated: allocatedPages,
                      target: chapterPages,
                    })}
                  </span>
                )}
              </div>
            )}

            {/* Subsections */}
            <div className="space-y-2">
              {chapter.subsections.map((sub, subIdx) => {
                if (deletedSubs.has(`${chIdx}-${subIdx}`)) return null
                
                const displayIdx = chapter.subsections
                  .slice(0, subIdx)
                  .filter((_, idx) => !deletedSubs.has(`${chIdx}-${idx}`))
                  .length + 1

                const subsectionPages = numericPage(sub.target_pages, sub.estimated_pages)
                const childAllocated = (sub.children || []).reduce((sum, child) => (
                  sum + (numericPage(child.target_pages, child.estimated_pages) || 0)
                ), 0)
                const childOverBudget = subsectionPages && childAllocated > subsectionPages

                return (
                  <div key={subIdx} className="space-y-2">
                    <div className="flex gap-2 items-center">
                      <div className="w-12 text-right text-sm text-blue-400">
                        {chIdx + 1}.{displayIdx}
                      </div>
                      <input
                        type="text"
                        value={sub.title}
                        onChange={(e) => handleSubChange(chIdx, subIdx, e.target.value)}
                        className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                      />
                      <input
                        type="number"
                        min="1"
                        max={chapterPages || undefined}
                        step="1"
                        value={sub.target_pages ?? (Math.round(sub.estimated_pages || 0) || '')}
                        onChange={(e) => handleSubPagesChange(chIdx, subIdx, e.target.value)}
                        className="w-24 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                        title={t('textbook.curriculum.pages')}
                      />
                      <button
                        onClick={() => handleDeleteSub(chIdx, subIdx)}
                        className="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg"
                        title={t('textbook.curriculum.deleteSubsectionTitle')}
                      >
                        🗑️
                      </button>
                    </div>

                    {structureDepth === 'level2' && (
                      <div className={`ml-12 space-y-2 rounded-md border p-2 ${
                        childOverBudget ? 'border-red-200 bg-red-50' : 'border-gray-100 bg-gray-50'
                      }`}>
                        {subsectionPages && (
                          <p className={`text-xs ${childOverBudget ? 'text-red-700' : 'text-gray-500'}`}>
                            {t('textbook.structure.childPageAllocationStatus', {
                              allocated: childAllocated,
                              target: subsectionPages,
                            })}
                          </p>
                        )}
                        {(sub.children || []).map((child, childIdx) => (
                          <div key={childIdx} className="flex items-center gap-2">
                            <div className="w-16 text-right text-xs font-medium text-blue-500">
                              {chIdx + 1}.{displayIdx}.{childIdx + 1}
                            </div>
                            <input
                              type="text"
                              value={child.title}
                              onChange={(e) => handleChildChange(chIdx, subIdx, childIdx, e.target.value)}
                              className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                            />
                            <input
                              type="number"
                              min="1"
                              max={subsectionPages || undefined}
                              step="1"
                              value={child.target_pages ?? (Math.round(child.estimated_pages || 0) || '')}
                              onChange={(e) => handleChildPagesChange(chIdx, subIdx, childIdx, e.target.value)}
                              className="w-20 rounded-md border border-gray-300 px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                              title={t('textbook.structure.childSubsectionPages')}
                            />
                            <button
                              onClick={() => handleDeleteChild(chIdx, subIdx, childIdx)}
                              className="rounded-md px-2 py-2 text-sm text-red-600 hover:bg-red-50"
                              title={t('textbook.structure.deleteChildSubsection')}
                            >
                              🗑️
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => handleAddChild(chIdx, subIdx)}
                          className="ml-16 rounded-md border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50"
                        >
                          + {t('textbook.structure.addChildSubsection')}
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}

              {/* New subsections */}
              {newSubsForChapter.map((item, newIdx) => {
                const displayIdx = activeSubs.length + newIdx + 1
                const title = typeof item === 'string' ? item : item.title
                const pages = typeof item === 'string' ? '' : item.target_pages
                const children = typeof item === 'string' ? [] : (item.children || [])
                const subsectionPages = numericPage(pages)
                const childAllocated = children.reduce((sum, child) => (
                  sum + (numericPage(child.target_pages) || 0)
                ), 0)
                const childOverBudget = subsectionPages && childAllocated > subsectionPages
                
                return (
                  <div key={`new-${newIdx}`} className="space-y-2">
                    <div className="flex gap-2 items-center">
                      <div className="w-12 text-right text-sm text-blue-600 font-semibold">
                        {chIdx + 1}.{displayIdx} ✦
                      </div>
                      <input
                        type="text"
                        value={title}
                        onChange={(e) => handleNewSubChange(chIdx, newIdx, { title: e.target.value })}
                        className="flex-1 px-3 py-2 border border-blue-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-blue-50"
                        placeholder={t('textbook.curriculum.newSubsectionPlaceholder')}
                      />
                      <input
                        type="number"
                        min="1"
                        max={chapterPages || undefined}
                        step="1"
                        value={pages ?? ''}
                        onChange={(e) => handleNewSubChange(chIdx, newIdx, { target_pages: e.target.value })}
                        className="w-24 px-3 py-2 border border-blue-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-blue-50"
                        title={t('textbook.curriculum.pages')}
                      />
                      <button
                        onClick={() => handleDeleteNewSub(chIdx, newIdx)}
                        className="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg"
                        title={t('textbook.curriculum.deleteNewSubsectionTitle')}
                      >
                        🗑️
                      </button>
                    </div>

                    {structureDepth === 'level2' && (
                      <div className={`ml-12 space-y-2 rounded-md border p-2 ${
                        childOverBudget ? 'border-red-200 bg-red-50' : 'border-blue-100 bg-blue-50'
                      }`}>
                        {subsectionPages && (
                          <p className={`text-xs ${childOverBudget ? 'text-red-700' : 'text-blue-700'}`}>
                            {t('textbook.structure.childPageAllocationStatus', {
                              allocated: childAllocated,
                              target: subsectionPages,
                            })}
                          </p>
                        )}
                        {children.map((child, childIdx) => (
                          <div key={childIdx} className="flex items-center gap-2">
                            <div className="w-16 text-right text-xs font-medium text-blue-600">
                              {chIdx + 1}.{displayIdx}.{childIdx + 1}
                            </div>
                            <input
                              type="text"
                              value={child.title}
                              onChange={(e) => handleNewChildChange(chIdx, newIdx, childIdx, { title: e.target.value })}
                              className="min-w-0 flex-1 rounded-md border border-blue-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                            />
                            <input
                              type="number"
                              min="1"
                              max={subsectionPages || undefined}
                              step="1"
                              value={child.target_pages ?? ''}
                              onChange={(e) => handleNewChildChange(chIdx, newIdx, childIdx, { target_pages: e.target.value })}
                              className="w-20 rounded-md border border-blue-300 bg-white px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                              title={t('textbook.structure.childSubsectionPages')}
                            />
                            <button
                              onClick={() => handleDeleteNewChild(chIdx, newIdx, childIdx)}
                              className="rounded-md px-2 py-2 text-sm text-red-600 hover:bg-red-50"
                              title={t('textbook.structure.deleteChildSubsection')}
                            >
                              🗑️
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => handleAddNewChild(chIdx, newIdx)}
                          className="ml-16 rounded-md border border-blue-200 bg-white px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50"
                        >
                          + {t('textbook.structure.addChildSubsection')}
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Add button */}
            <button
              onClick={() => handleAddSub(chIdx)}
              className="mt-3 px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 border border-blue-300 rounded-lg"
            >
              ➕ {t('textbook.curriculum.addSubsection')}
            </button>
          </div>
        )
      })}

      <button
        onClick={handleAddChapter}
        className="w-full px-4 py-3 text-sm font-medium text-blue-700 hover:bg-blue-50 border border-blue-300 rounded-lg"
      >
        ➕ {t('textbook.curriculum.addChapter')}
      </button>

      {/* Action buttons */}
      <div className="flex gap-3">
        <Button
          onClick={handleConfirm}
          className="flex-1"
          disabled={confirming || chapterPageBudgetIssues.length > 0}
        >
          ✅ {confirming ? t('textbook.curriculum.confirming') : t('textbook.curriculum.confirm')}
        </Button>
        <Button
          variant="secondary"
          onClick={handleReset}
        >
          🔄 {t('textbook.curriculum.reset')}
        </Button>
      </div>

      {pendingConfirmCurriculum && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <button
            type="button"
            aria-label={t('app.close')}
            className="absolute inset-0 bg-black bg-opacity-50"
            onClick={handleConfirmModalClose}
            disabled={confirming}
          />
          <div className="relative w-full max-w-md rounded-lg bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-gray-900">
              {t('textbook.curriculum.creditConfirmTitle')}
            </h3>
            <p className="mt-2 text-sm text-gray-600">
              {creditEstimate?.is_admin_free
                ? t('textbook.curriculum.creditConfirmAdminDescription')
                : t('textbook.curriculum.creditConfirmDescription')}
            </p>

            <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-xs font-semibold uppercase text-emerald-700">
                {t('textbook.curriculum.creditEstimateTitle')}
              </p>
              <div className="mt-2 flex items-end justify-between gap-4">
                <div className="text-xs text-emerald-700">
                  {creditEstimate ? (
                    <p>
                      {t('textbook.curriculum.creditEstimateDetails', {
                        chapters: creditEstimate.total_chapters,
                        subsections: creditEstimate.total_subsections,
                        images: creditEstimate.enable_images ? t('app.yes') : t('app.no'),
                        level: creditEstimate.content_level,
                      })}
                    </p>
                  ) : (
                    <p>
                      {estimatingCredits
                        ? t('textbook.curriculum.estimatingCredits')
                        : estimateError || t('textbook.curriculum.creditEstimatePending')}
                    </p>
                  )}
                </div>
                {creditEstimate?.is_admin_free ? (
                  <p className="text-sm font-bold text-emerald-800">
                    {t('textbook.curriculum.adminFree')}
                  </p>
                ) : (
                  <div className="text-right">
                    <p className="text-3xl font-bold text-emerald-900">
                      {creditEstimate ? creditEstimate.credits_required : '...'}
                    </p>
                    <p className="text-xs text-emerald-700">credits</p>
                  </div>
                )}
              </div>
            </div>

            {creditEstimate?.page_validation?.severity === 'warning' && (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
                <p className="text-xs font-semibold uppercase text-amber-700">
                  {t('textbook.curriculum.pageEstimateTitle')}
                </p>
                <p className="mt-2 text-xs text-amber-800">
                  {creditEstimate.page_validation.ai_note}
                </p>
              </div>
            )}

            {estimateError && (
              <p className="mt-3 text-xs text-yellow-700">
                {estimateError}
              </p>
            )}

            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={handleConfirmModalClose}
                disabled={confirming}
                className="flex-1 rounded-lg bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t('textbook.curriculum.creditConfirmCancel')}
              </button>
              <button
                type="button"
                onClick={handleConfirmModalSubmit}
                disabled={confirming || estimatingCredits || (!creditEstimate && !estimateError)}
                className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {confirming
                  ? t('textbook.curriculum.confirming')
                  : t('textbook.curriculum.creditConfirmProceed')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
