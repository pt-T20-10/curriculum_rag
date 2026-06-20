import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Button } from '../common/Button'

export function CurriculumEditor({ curriculum, onConfirm, onReset, confirming = false }) {
  const { t } = useTranslation()
  const [editedCurriculum, setEditedCurriculum] = useState(curriculum)
  const [deletedSubs, setDeletedSubs] = useState(new Set())
  const [deletedChapters, setDeletedChapters] = useState(new Set()) // ⭐ NEW
  const [newSubs, setNewSubs] = useState({}) // { chapterIdx: [titles...] }
  const [validationError, setValidationError] = useState('')

  // Handle chapter title change
  const handleChapterChange = (chapterIdx, newTitle) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].title = newTitle
    setEditedCurriculum(updated)
  }

  // Handle subsection title change
  const handleSubChange = (chapterIdx, subIdx, newTitle) => {
    const updated = { ...editedCurriculum }
    updated.chapters[chapterIdx].subsections[subIdx].title = newTitle
    setEditedCurriculum(updated)
  }

  const handleAddChapter = () => {
    const chapterNumber = editedCurriculum.chapters.length + 1
    const chapterTitle = t('textbook.curriculum.newChapterTitle', { number: chapterNumber })
    const subsectionTitle = t('textbook.curriculum.newChapterSubsection', { number: chapterNumber })
    setEditedCurriculum({
      ...editedCurriculum,
      chapters: [
        ...editedCurriculum.chapters,
        {
          title: chapterTitle,
          subsections: [{
            title: subsectionTitle,
            description: `Content about ${subsectionTitle}`,
            search_query: subsectionTitle,
            section_type: 'medium',
          }],
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
    updated[chapterIdx].push(`${t('textbook.contentSidebar.subsections')} ${chapterIdx + 1}.${currentCount + newCount + 1}`)
    setNewSubs(updated)
  }

  // Build final curriculum for submit
  const buildFinalCurriculum = () => {
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
            return {
              title,
              description: sub.description?.trim() || `Content about ${title}`,
              search_query: sub.search_query?.trim() || title,
              section_type: sub.section_type || 'medium',
            }
          })
          .filter(Boolean)

        if (activeSubs.some(sub => sub.invalid)) return { invalid: true }

        // Add new subsections
        const newSubsForChapter = newSubs[chIdx] || []
        const newSubObjects = newSubsForChapter.map(title => {
          const cleanTitle = title.trim()
          if (!cleanTitle) return { invalid: true }
          return {
            title: cleanTitle,
            description: `Content about ${cleanTitle}`,
            search_query: cleanTitle,
            section_type: 'medium',
          }
        })

        if (newSubObjects.some(sub => sub.invalid)) return { invalid: true }

        return {
          title: chapterTitle,
          subsections: [...activeSubs, ...newSubObjects],
        }
      })
      .filter(Boolean) // Remove nulls (deleted chapters and empty chapters)

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
      chapters: compactChapters,
    }
  }

  const handleConfirm = () => {
    const finalCurriculum = buildFinalCurriculum()
    if (finalCurriculum.invalid) {
      setValidationError(
        finalCurriculum.empty
          ? t('textbook.curriculum.emptyCurriculumError')
          : t('textbook.curriculum.blankTitleError')
      )
      return
    }
    setValidationError('')
    onConfirm(finalCurriculum)
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

        return (
          <div key={chIdx} className="bg-white rounded-lg border border-gray-200 p-4">
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

            {/* Subsections */}
            <div className="space-y-2">
              {chapter.subsections.map((sub, subIdx) => {
                if (deletedSubs.has(`${chIdx}-${subIdx}`)) return null
                
                const displayIdx = chapter.subsections
                  .slice(0, subIdx)
                  .filter((_, idx) => !deletedSubs.has(`${chIdx}-${idx}`))
                  .length + 1

                return (
                  <div key={subIdx} className="flex gap-2 items-center">
                    <div className="w-12 text-right text-sm text-blue-400">
                      {chIdx + 1}.{displayIdx}
                    </div>
                    <input
                      type="text"
                      value={sub.title}
                      onChange={(e) => handleSubChange(chIdx, subIdx, e.target.value)}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                    <button
                      onClick={() => handleDeleteSub(chIdx, subIdx)}
                      className="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg"
                      title={t('textbook.curriculum.deleteSubsectionTitle')}
                    >
                      🗑️
                    </button>
                  </div>
                )
              })}

              {/* New subsections */}
              {newSubsForChapter.map((title, newIdx) => {
                const displayIdx = activeSubs.length + newIdx + 1
                
                return (
                  <div key={`new-${newIdx}`} className="flex gap-2 items-center">
                    <div className="w-12 text-right text-sm text-blue-600 font-semibold">
                      {chIdx + 1}.{displayIdx} ✦
                    </div>
                    <input
                      type="text"
                      value={title}
                      onChange={(e) => {
                        const updated = { ...newSubs }
                        updated[chIdx][newIdx] = e.target.value
                        setNewSubs(updated)
                      }}
                      className="flex-1 px-3 py-2 border border-blue-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-blue-50"
                      placeholder={t('textbook.curriculum.newSubsectionPlaceholder')}
                    />
                    <button
                      onClick={() => handleDeleteNewSub(chIdx, newIdx)}
                      className="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg"
                      title={t('textbook.curriculum.deleteNewSubsectionTitle')}
                    >
                      🗑️
                    </button>
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
          disabled={confirming}
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
    </div>
  )
}
