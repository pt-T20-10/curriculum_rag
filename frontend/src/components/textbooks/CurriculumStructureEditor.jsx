import { useTranslation } from 'react-i18next'
import { createDefaultStructure } from '../../utils/curriculumStructure'

function parseOptionalPage(value) {
  if (value === '' || value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function CurriculumStructureEditor({
  value,
  onChange,
  disabled = false,
  structureDepth = 'level1',
  allowChildControls = false,
  missingChildSections = [],
}) {
  const { t } = useTranslation()
  const structure = value || createDefaultStructure(t, structureDepth)
  const chapters = structure.chapters || []

  const updateChapters = (nextChapters) => {
    onChange({ ...structure, structure_depth: structureDepth, chapters: nextChapters })
  }

  const updateChapter = (chapterIdx, patch) => {
    updateChapters(
      chapters.map((chapter, idx) => (
        idx === chapterIdx ? { ...chapter, ...patch } : chapter
      ))
    )
  }

  const updateSubsection = (chapterIdx, subIdx, patch) => {
    const chapter = chapters[chapterIdx]
    const subsections = (chapter.subsections || []).map((subsection, idx) => (
      idx === subIdx ? { ...subsection, ...patch } : subsection
    ))
    updateChapter(chapterIdx, { subsections })
  }

  const updateChild = (chapterIdx, subIdx, childIdx, patch) => {
    const chapter = chapters[chapterIdx]
    const subsections = (chapter.subsections || []).map((subsection, idx) => {
      if (idx !== subIdx) return subsection
      const children = (subsection.children || []).map((child, cIdx) => (
        cIdx === childIdx ? { ...child, ...patch } : child
      ))
      return { ...subsection, children }
    })
    updateChapter(chapterIdx, { subsections })
  }

  const addChapter = () => {
    const nextNumber = chapters.length + 1
    updateChapters([
      ...chapters,
      {
        title: t('textbook.structure.defaultChapter', { number: nextNumber }),
        subsections: [
          {
            title: t('textbook.structure.defaultSubsection', { chapter: nextNumber, number: 1 }),
            children: structureDepth === 'level2'
              ? [{ title: t('textbook.structure.defaultChildSubsection', { chapter: nextNumber, section: 1, number: 1 }) }]
              : [],
          },
        ],
      },
    ])
  }

  const deleteChapter = (chapterIdx) => {
    updateChapters(chapters.filter((_, idx) => idx !== chapterIdx))
  }

  const addSubsection = (chapterIdx) => {
    const chapter = chapters[chapterIdx]
    const nextNumber = (chapter.subsections || []).length + 1
    updateChapter(chapterIdx, {
      subsections: [
        ...(chapter.subsections || []),
        {
          title: t('textbook.structure.defaultSubsection', {
            chapter: chapterIdx + 1,
            number: nextNumber,
          }),
          children: structureDepth === 'level2'
            ? [{ title: t('textbook.structure.defaultChildSubsection', { chapter: chapterIdx + 1, section: nextNumber, number: 1 }) }]
            : [],
        },
      ],
    })
  }

  const addChild = (chapterIdx, subIdx) => {
    const chapter = chapters[chapterIdx]
    const subsection = chapter.subsections[subIdx]
    const nextNumber = (subsection.children || []).length + 1
    updateSubsection(chapterIdx, subIdx, {
      children: [
        ...(subsection.children || []),
        {
          title: t('textbook.structure.defaultChildSubsection', {
            chapter: chapterIdx + 1,
            section: subIdx + 1,
            number: nextNumber,
          }),
        },
      ],
    })
  }

  const deleteChild = (chapterIdx, subIdx, childIdx) => {
    const chapter = chapters[chapterIdx]
    const subsection = chapter.subsections[subIdx]
    updateSubsection(chapterIdx, subIdx, {
      children: (subsection.children || []).filter((_, idx) => idx !== childIdx),
    })
  }

  const deleteSubsection = (chapterIdx, subIdx) => {
    const chapter = chapters[chapterIdx]
    updateChapter(chapterIdx, {
      subsections: (chapter.subsections || []).filter((_, idx) => idx !== subIdx),
    })
  }

  return (
    <div className="space-y-4">
      {chapters.map((chapter, chapterIdx) => {
        const chapterPages = parseOptionalPage(chapter.target_pages)
        const allocatedPages = (chapter.subsections || []).reduce((sum, subsection) => {
          const pages = parseOptionalPage(subsection.target_pages)
          return sum + (pages || 0)
        }, 0)
        const isOverBudget = chapterPages && allocatedPages > chapterPages

        return (
        <div key={chapterIdx} className={`rounded-lg border bg-white p-4 ${
          isOverBudget ? 'border-red-300' : 'border-gray-200'
        }`}>
          <div className="mb-3 flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <label className="mb-2 block text-sm font-semibold text-blue-700">
                {t('textbook.structure.chapter', { number: chapterIdx + 1 })}
              </label>
              <input
                type="text"
                value={chapter.title}
                onChange={(event) => updateChapter(chapterIdx, { title: event.target.value })}
                disabled={disabled}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
              />
            </div>
            <div className="w-28 shrink-0">
              <label className="mb-2 block text-sm font-semibold text-gray-600">
                {t('textbook.structure.pages')}
              </label>
              <input
                type="number"
                min="1"
                step="1"
                value={chapter.target_pages ?? ''}
                onChange={(event) => updateChapter(chapterIdx, { target_pages: event.target.value })}
                disabled={disabled}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
              />
            </div>
            <button
              type="button"
              onClick={() => deleteChapter(chapterIdx)}
              disabled={disabled}
              className="mt-7 shrink-0 rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('textbook.structure.deleteChapter')}
            </button>
          </div>

          {chapterPages && (
            <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
              isOverBudget
                ? 'border-red-200 bg-red-50 text-red-700'
                : 'border-blue-100 bg-blue-50 text-blue-700'
            }`}>
              {t('textbook.structure.pageAllocationStatus', {
                allocated: allocatedPages,
                target: chapterPages,
              })}
              {isOverBudget && (
                <span className="ml-2 font-semibold">
                  {t('textbook.structure.errors.subsectionPagesExceedChapter', {
                    chapter: chapterIdx + 1,
                    allocated: allocatedPages,
                    target: chapterPages,
                  })}
                </span>
              )}
            </div>
          )}

          <div className="space-y-2">
            {(chapter.subsections || []).map((subsection, subIdx) => {
              const childRowsVisible = structureDepth === 'level2' || allowChildControls || (subsection.children || []).length > 0
              const isMissingChild = missingChildSections.some(item => (
                item.chapter === chapterIdx + 1 && item.section === subIdx + 1
              ))
              const subsectionPages = parseOptionalPage(subsection.target_pages)
              const childAllocated = (subsection.children || []).reduce((sum, child) => {
                const pages = parseOptionalPage(child.target_pages)
                return sum + (pages || 0)
              }, 0)
              const childOverBudget = subsectionPages && childAllocated > subsectionPages
              return (
                <div key={subIdx} className="space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="w-12 shrink-0 text-right text-sm font-medium text-blue-500">
                      {chapterIdx + 1}.{subIdx + 1}
                    </div>
                    <input
                      type="text"
                      value={subsection.title}
                      onChange={(event) => updateSubsection(chapterIdx, subIdx, { title: event.target.value })}
                      disabled={disabled}
                      className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
                    />
                    <input
                      type="number"
                      min="1"
                      max={chapterPages || undefined}
                      step="1"
                      value={subsection.target_pages ?? ''}
                      onChange={(event) => updateSubsection(chapterIdx, subIdx, { target_pages: event.target.value })}
                      disabled={disabled}
                      className="w-24 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
                      title={t('textbook.structure.subsectionPages')}
                    />
                    <button
                      type="button"
                      onClick={() => deleteSubsection(chapterIdx, subIdx)}
                      disabled={disabled}
                      className="shrink-0 rounded-lg px-2 py-2 text-sm text-red-500 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                      title={t('textbook.structure.deleteSubsection')}
                    >
                      {t('app.delete')}
                    </button>
                  </div>
                  {childRowsVisible && (
                    <div className={`ml-12 space-y-2 rounded-md border p-2 ${
                      childOverBudget || isMissingChild ? 'border-red-200 bg-red-50' : 'border-gray-100 bg-gray-50'
                    }`}>
                      {isMissingChild && (
                        <p className="text-xs font-medium text-red-700">
                          {t('textbook.structure.errors.emptyChildSection', {
                            chapter: chapterIdx + 1,
                            section: subIdx + 1,
                          })}
                        </p>
                      )}
                      {subsectionPages && (
                        <p className={`text-xs ${childOverBudget ? 'text-red-700' : 'text-gray-500'}`}>
                          {t('textbook.structure.childPageAllocationStatus', {
                            allocated: childAllocated,
                            target: subsectionPages,
                          })}
                        </p>
                      )}
                      {(subsection.children || []).map((child, childIdx) => (
                        <div key={childIdx} className="flex items-center gap-2">
                          <div className="w-16 shrink-0 text-right text-xs font-medium text-blue-500">
                            {chapterIdx + 1}.{subIdx + 1}.{childIdx + 1}
                          </div>
                          <input
                            type="text"
                            value={child.title}
                            onChange={(event) => updateChild(chapterIdx, subIdx, childIdx, { title: event.target.value })}
                            disabled={disabled}
                            className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
                          />
                          <input
                            type="number"
                            min="1"
                            max={subsectionPages || undefined}
                            step="1"
                            value={child.target_pages ?? ''}
                            onChange={(event) => updateChild(chapterIdx, subIdx, childIdx, { target_pages: event.target.value })}
                            disabled={disabled}
                            className="w-20 shrink-0 rounded-md border border-gray-300 px-2 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
                            title={t('textbook.structure.childSubsectionPages')}
                          />
                          <button
                            type="button"
                            onClick={() => deleteChild(chapterIdx, subIdx, childIdx)}
                            disabled={disabled}
                            className="shrink-0 rounded-md px-2 py-2 text-sm text-red-500 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                            title={t('textbook.structure.deleteChildSubsection')}
                          >
                            {t('app.delete')}
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => addChild(chapterIdx, subIdx)}
                        disabled={disabled}
                        className="ml-16 rounded-md border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        + {t('textbook.structure.addChildSubsection')}
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <button
            type="button"
            onClick={() => addSubsection(chapterIdx)}
            disabled={disabled}
            className="mt-3 rounded-lg border border-blue-300 px-4 py-2 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            + {t('textbook.structure.addSubsection')}
          </button>
        </div>
        )
      })}

      <button
        type="button"
        onClick={addChapter}
        disabled={disabled}
        className="w-full rounded-lg border border-blue-300 px-4 py-3 text-sm font-semibold text-blue-700 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        + {t('textbook.structure.addChapter')}
      </button>
    </div>
  )
}
