import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StatsSection } from './StatsSection'
import { ChapterList } from './ChapterList'
import { SourceAuditSection } from './SourceAuditSection'
import { RunningIndicator } from '../common/RunningIndicator'
import { getSubsectionProgress } from '../../utils/progressMetrics'

/**
 * Transform flat chapter_titles array into hierarchical structure
 * This handles the case where backend only sends chapter_titles (flat list)
 */
function transformChapterData(progressData) {
  const { chapter_titles = [], curriculum_data } = progressData || {}

  // If we have full curriculum_data, use it
  if (curriculum_data?.chapters) {
    return curriculum_data.chapters.map((ch, idx) => ({
      number: ch.number || idx + 1,
      title: ch.title,
      subsections: ch.subsections || []
    }))
  }

  // Otherwise, construct from flat chapter_titles
  if (Array.isArray(chapter_titles) && chapter_titles.length > 0) {
    return chapter_titles.map((title, idx) => ({
      number: idx + 1,
      title: title,
      subsections: [] // No subsections in simple mode
    }))
  }

  return []
}

export function ContentSidebar({ progressData }) {
  const { t } = useTranslation()
  const [sourceAuditHeight, setSourceAuditHeight] = useState(260)
  const resizeStartRef = useRef(null)
  // Transform chapter data (must be before early return - hooks rule)
  const chapters = useMemo(
    () => transformChapterData(progressData),
    [progressData]
  )

  useEffect(() => {
    const handleMouseMove = (event) => {
      if (!resizeStartRef.current) return

      const { startY, startHeight } = resizeStartRef.current
      const nextHeight = startHeight + event.clientY - startY
      setSourceAuditHeight(Math.min(420, Math.max(160, nextHeight)))
    }

    const handleMouseUp = () => {
      resizeStartRef.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [])

  const {
    current_chapter = 0,
    current_subsection = 0,
  } = progressData || {}
  const { displaySubsectionLocalNumber } = getSubsectionProgress({
    curriculumData: progressData?.curriculum_data,
    currentChapter: current_chapter,
    currentSubsection: current_subsection,
    totalSubsections: progressData?.total_subsections,
  })

  // Don't render if no data or not in generating phase
  if (!progressData || progressData.phase !== 'generating') {
    return (
      <div className="h-full flex items-center justify-center p-6 text-center text-gray-400">
        <div>
          <div className="text-4xl mb-3">📊</div>
          <p className="text-sm">
            {t('textbook.sidebarWaiting')}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Stats Section */}
      <div className="flex-shrink-0 border-b border-gray-200">
        <StatsSection progressData={progressData} />
      </div>

      <div
        className="min-h-0 flex-shrink-0 overflow-hidden"
        style={{ height: `${sourceAuditHeight}px` }}
      >
        <SourceAuditSection
          sourceAudit={progressData.source_audit}
          sourceMaterials={progressData.source_materials}
          className="h-full"
        />
      </div>

      <div
        onMouseDown={(event) => {
          resizeStartRef.current = {
            startY: event.clientY,
            startHeight: sourceAuditHeight,
          }
          document.body.style.cursor = 'row-resize'
          document.body.style.userSelect = 'none'
        }}
        className="h-1.5 flex-shrink-0 cursor-row-resize bg-gray-100 hover:bg-blue-400"
        title={t('layout.resize')}
      />

      {/* Chapter List - Scrollable */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ChapterList
          chapters={chapters}
          currentChapter={current_chapter}
          currentSubsection={current_subsection}
        />
      </div>

      {/* Footer - Current Status */}
      <div className="flex-shrink-0 border-t border-gray-200 px-4 py-3 bg-blue-50">
        <RunningIndicator
          className="border-0 bg-transparent p-0"
          size="sm"
          label={
            current_chapter > 0 && current_subsection > 0
              ? t('textbook.contentSidebar.writing', {
                  chapter: current_chapter,
                  subsection: displaySubsectionLocalNumber || current_subsection,
                })
              : t('textbook.contentSidebar.initializing')
          }
        />
      </div>
    </div>
  )
}
