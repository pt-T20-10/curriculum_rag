import { useTranslation } from 'react-i18next'
import { createDefaultStructure } from '../../utils/curriculumStructure'

export function CurriculumStructureEditor({ value, onChange, disabled = false }) {
  const { t } = useTranslation()
  const structure = value || createDefaultStructure(t)
  const chapters = structure.chapters || []

  const updateChapters = (nextChapters) => {
    onChange({ ...structure, chapters: nextChapters })
  }

  const updateChapter = (chapterIdx, patch) => {
    updateChapters(
      chapters.map((chapter, idx) => (
        idx === chapterIdx ? { ...chapter, ...patch } : chapter
      ))
    )
  }

  const updateSubsection = (chapterIdx, subIdx, title) => {
    const chapter = chapters[chapterIdx]
    const subsections = (chapter.subsections || []).map((subsection, idx) => (
      idx === subIdx ? { ...subsection, title } : subsection
    ))
    updateChapter(chapterIdx, { subsections })
  }

  const addChapter = () => {
    const nextNumber = chapters.length + 1
    updateChapters([
      ...chapters,
      {
        title: t('textbook.structure.defaultChapter', { number: nextNumber }),
        subsections: [
          { title: t('textbook.structure.defaultSubsection', { chapter: nextNumber, number: 1 }) },
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
        },
      ],
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
      {chapters.map((chapter, chapterIdx) => (
        <div key={chapterIdx} className="rounded-lg border border-gray-200 bg-white p-4">
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
            <button
              type="button"
              onClick={() => deleteChapter(chapterIdx)}
              disabled={disabled}
              className="mt-7 shrink-0 rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('textbook.structure.deleteChapter')}
            </button>
          </div>

          <div className="space-y-2">
            {(chapter.subsections || []).map((subsection, subIdx) => (
              <div key={subIdx} className="flex items-center gap-2">
                <div className="w-12 shrink-0 text-right text-sm font-medium text-blue-500">
                  {chapterIdx + 1}.{subIdx + 1}
                </div>
                <input
                  type="text"
                  value={subsection.title}
                  onChange={(event) => updateSubsection(chapterIdx, subIdx, event.target.value)}
                  disabled={disabled}
                  className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
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
            ))}
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
      ))}

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
