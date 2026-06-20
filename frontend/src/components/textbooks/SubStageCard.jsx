import { useTranslation } from 'react-i18next'
import { getSubsectionProgress } from '../../utils/progressMetrics'

export function SubStageCard({ 
  subStages, 
  chapter, 
  subsection, 
  totalChapters,
  curriculumData  // ⭐ NEW: For calculating subsections
}) {
  const { t } = useTranslation()
  const {
    chapterNumber,
    subsectionNumber,
    currentChapterTotal,
  } = getSubsectionProgress({
    curriculumData,
    currentChapter: chapter,
    currentSubsection: subsection,
  })
  
  const icons = {
    researcher: '🔍',
    retriever: '🔎',
    writer: '✍️',
    reviewer: '👁️',
    illustrator: '🎨',
  }
  
  const labels = {
    researcher: t('textbook.workflow.researcher'),
    retriever: t('textbook.workflow.retriever'),
    writer: t('textbook.workflow.writer'),
    reviewer: t('textbook.workflow.reviewer'),
    illustrator: t('textbook.workflow.illustrator'),
  }
  
  const stateSymbols = {
    pending: '○',
    active: '⏳',
    done: '✓',
  }
  
  const anyActive = Object.values(subStages).some(s => s === 'active')
  const cardClass = anyActive ? 'border-l-4 border-l-blue-500 bg-blue-50' : 'border-l-4 border-l-gray-300 bg-gray-50'
  const badgeClass = anyActive ? 'bg-blue-100 text-blue-800 border border-blue-300' : 'bg-gray-100 text-gray-600'
  const badgeText = anyActive ? `⏳ ${t('textbook.workflow.active')}` : `⏸️ ${t('textbook.workflow.pending')}`

  return (
    <div className={`p-4 rounded-lg border ${cardClass} mb-3`}>
      <div className="flex justify-between items-center mb-3">
        <div>
          <span className="text-lg">⚙️</span>
          <span className="ml-2 font-semibold">
            {t('textbook.workflow.chapterSubsectionProgress', {
              chapter: chapterNumber,
              total: totalChapters,
              subsection: subsectionNumber,
              subsectionTotal: currentChapterTotal,
            })}
          </span>
        </div>
        <span className={`px-3 py-1 rounded-full text-xs font-semibold ${badgeClass}`}>
          {badgeText}
        </span>
      </div>
      
      <div className="grid grid-cols-4 gap-2">
        {Object.entries(subStages).map(([stage, state]) => {
          const stateClass = {
            done: 'bg-green-50 border-green-300 text-green-800',
            active: 'bg-blue-50 border-blue-500 text-blue-800 ring-2 ring-blue-200',
            pending: 'bg-gray-50 border-gray-200 text-gray-400',
          }[state]
          
          return (
            <div key={stage} className={`p-2 rounded-lg border text-center text-xs ${stateClass}`}>
              <div className="mb-1">{icons[stage]}</div>
              <div className="font-medium">{labels[stage]}</div>
              <div className="text-xs mt-1">
                <strong>{stateSymbols[state]}</strong>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
