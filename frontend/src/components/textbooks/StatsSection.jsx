import { useTranslation } from 'react-i18next'
import { getSubsectionProgress } from '../../utils/progressMetrics'

export function StatsSection({ progressData }) {
  const { t } = useTranslation()
  const {
    current_chapter = 0,
    total_chapters = 0,
    current_subsection = 0,
    total_subsections = 0,
    curriculum_data = null,
  } = progressData || {}
  
  // Calculate totals from curriculum if not provided
  const actualTotalChapters = total_chapters || curriculum_data?.chapters?.length || 0
  const actualTotalSubsections = total_subsections || 
    curriculum_data?.chapters?.reduce((sum, ch) => sum + (ch.subsections?.length || 0), 0) || 0
  const { completedSubsections } = getSubsectionProgress({
    curriculumData: curriculum_data,
    currentChapter: current_chapter,
    currentSubsection: current_subsection,
    totalSubsections: actualTotalSubsections,
  })

  return (
    <div className="px-4 py-3 space-y-4">
      {/* Title */}
      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">{t('textbook.contentSidebar.chapters')}</div>
          <div className="text-lg font-bold text-gray-800">
            {current_chapter} / {actualTotalChapters}
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">{t('textbook.contentSidebar.subsections')}</div>
          <div className="text-lg font-bold text-gray-800">
            {completedSubsections} / {actualTotalSubsections}
          </div>
        </div>
      </div>
    </div>
  )
}
