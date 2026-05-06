import { useState, useMemo } from 'react'
import { ChapterItem } from './ChapterItem'

export function ChapterList({ chapters, currentChapter, currentSubsection }) {
  // Track manually expanded chapters (user clicked to expand)
  const [manuallyExpanded, setManuallyExpanded] = useState([])

  // Combine auto-expand (current chapter) + manual expands
  const expandedChapters = useMemo(() => {
    const expanded = new Set(manuallyExpanded)
    
    // Auto-expand current chapter
    if (currentChapter) {
      expanded.add(currentChapter)
    }
    
    return Array.from(expanded)
  }, [currentChapter, manuallyExpanded])

  const toggleChapter = (chapterNum) => {
    setManuallyExpanded(prev =>
      prev.includes(chapterNum)
        ? prev.filter(num => num !== chapterNum)
        : [...prev, chapterNum]
    )
  }

  const getChapterStatus = (chapterNum) => {
    if (chapterNum < currentChapter) return 'done'
    if (chapterNum === currentChapter) return 'running'
    return 'pending'
  }

  if (!chapters || chapters.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-gray-400 text-sm">
        <div className="text-4xl mb-2">📚</div>
        <p>Chưa có danh sách chương</p>
      </div>
    )
  }

  return (
    <div className="px-4 py-3 space-y-3">
      {/* Title */}
      <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2">
        <span>📚</span>
        <span>Danh Sách Chương</span>
      </h3>

      {/* Chapter List */}
      <div className="space-y-2">
        {chapters.map((chapter) => (
          <ChapterItem
            key={chapter.number}
            chapter={chapter}
            isCurrent={chapter.number === currentChapter}
            status={getChapterStatus(chapter.number)}
            currentSubsection={{
              chapter: currentChapter,
              subsection: currentSubsection
            }}
            isExpanded={expandedChapters.includes(chapter.number)}  
            onToggle={() => toggleChapter(chapter.number)}
          />
        ))}
      </div>
    </div>
  )
}