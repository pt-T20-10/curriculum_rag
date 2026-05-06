export function ChapterItem({ 
  chapter, 
  isCurrent, 
  status,
  currentSubsection,
  onToggle,
  isExpanded 
}) {
  const statusIcons = {
    done: '✅',
    running: '🔄',
    pending: '⏳',
    error: '❌'
  }

  const statusStyles = {
    done: 'bg-green-50 text-green-700',
    running: 'bg-blue-50 text-blue-700 border-l-2 border-blue-500',
    pending: 'bg-gray-50 text-gray-500',
    error: 'bg-red-50 text-red-700'
  }

  const hasSubsections = chapter.subsections && chapter.subsections.length > 0

  const getSubsectionStatus = (subsectionNum) => {
    if (chapter.number < currentSubsection?.chapter) return 'done'
    if (chapter.number > currentSubsection?.chapter) return 'pending'
    
    // Current chapter
    if (subsectionNum < currentSubsection?.subsection) return 'done'
    if (subsectionNum === currentSubsection?.subsection) return 'running'
    return 'pending'
  }

  return (
    <div>
      {/* Chapter Header */}
      <div
        className={`
          px-3 py-2 rounded-lg text-sm transition-all cursor-pointer
          ${statusStyles[status]}
          ${isCurrent ? 'font-semibold' : ''}
        `}
        onClick={() => hasSubsections && onToggle()}
      >
        <div className="flex items-center gap-2">
          {/* Expand Arrow */}
          {hasSubsections && (
            <span className="text-xs transition-transform duration-200" style={{
              transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)'
            }}>
              ▶
            </span>
          )}
          
          {/* Status Icon */}
          <span className={status === 'running' ? 'animate-pulse' : ''}>
            {statusIcons[status]}
          </span>
          
          {/* Chapter Title */}
          <span className="flex-1 line-clamp-1">
            {chapter.number}. {chapter.title}
          </span>
        </div>
      </div>

      {/* Subsections (when expanded) */}
      {hasSubsections && isExpanded && (
        <div className="ml-6 mt-1 space-y-1">
          {chapter.subsections.map((subsection, idx) => {
            const subStatus = getSubsectionStatus(subsection.number || idx + 1)
            const isCurrentSub = chapter.number === currentSubsection?.chapter && 
                                 (subsection.number || idx + 1) === currentSubsection?.subsection

            return (
              <div
                key={idx}
                className={`
                  px-2 py-1.5 rounded text-xs transition-all
                  ${statusStyles[subStatus]}
                  ${isCurrentSub ? 'font-medium' : ''}
                `}
              >
                <div className="flex items-center gap-2">
                  <span className={subStatus === 'running' ? 'animate-pulse' : ''}>
                    {statusIcons[subStatus]}
                  </span>
                  <span className="line-clamp-1">
                    {chapter.number}.{subsection.number || idx + 1} {subsection.title}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}