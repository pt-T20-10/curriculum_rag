export function ContentSidebar({ progressData }) {
  if (!progressData || progressData.phase !== 'generating') {
    return null
  }

  const { 
    chapter_titles = [],
    current_chapter = 0,
    current_subsection = 0,
    current_content_preview = '',
    total_chapters = 0,
    total_subsections = 0,
  } = progressData

  const chapterList = Array.isArray(chapter_titles) ? chapter_titles : []
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="pb-3 border-b border-gray-300">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <span>📊</span>
          <span>Thống kê</span>
        </h3>
      </div>

      {/* Stats */}
      <div className="space-y-3">
        <div>
          <div className="text-xs text-gray-600 mb-1">Số chương</div>
          <div className="text-2xl font-bold text-primary">{total_chapters}</div>
        </div>
        <div>
          <div className="text-xs text-gray-600 mb-1">Tổng số mục</div>
          <div className="text-2xl font-bold text-primary">{total_subsections}</div>
        </div>
      </div>

      <div className="border-t border-gray-300 pt-3"></div>

      {/* Chapter navigation */}
      {chapterList.length > 0 && (
        <div>
            <h4 className="text-xs font-semibold text-gray-700 mb-2">Tiến độ chương</h4>
            <div className="space-y-1">
            {chapterList.map((title, idx) => (
              <div
                key={idx}
                className={`
                  px-2 py-1.5 rounded text-xs transition-colors
                  ${idx === current_chapter
                    ? 'bg-blue-50 border-l-2 border-blue-500 font-semibold text-blue-900'
                    : idx < current_chapter
                    ? 'bg-green-50 text-green-700'
                    : 'bg-gray-50 text-gray-500'
                  }
                `}
              >
                <div className="flex items-center gap-2">
                  {idx < current_chapter && <span className="text-green-600 text-xs">✓</span>}
                  {idx === current_chapter && <span className="text-blue-600 text-xs">⏳</span>}
                  {idx > current_chapter && <span className="text-gray-400 text-xs">○</span>}
                  <span className="line-clamp-1 text-xs">
                    {idx + 1}. {title}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Content preview */}
      {current_content_preview && (
        <div>
          <h4 className="text-xs font-semibold text-gray-700 mb-2">
            Nội dung gần nhất:
          </h4>
          <div className="bg-white rounded border border-gray-200 p-2 text-xs text-gray-700 leading-relaxed max-h-48 overflow-y-auto">
            <div className="whitespace-pre-wrap font-mono text-xs">
              {current_content_preview.split('\n').slice(-10).join('\n')}
            </div>
          </div>
          <div className="mt-1 text-xs text-gray-500 text-center">
            Cập nhật theo thời gian thực...
          </div>
        </div>
      )}

      {/* Current indicator */}
      <div className="p-2 bg-blue-50 rounded text-xs text-blue-700 text-center">
        Đang viết mục {current_subsection + 1}...
      </div>
    </div>
  )
}