import { useState } from 'react'
import { Button } from '../common/Button'

export function CurriculumEditor({ curriculum, onConfirm, onReset }) {
  const [editedCurriculum, setEditedCurriculum] = useState(curriculum)
  const [deletedSubs, setDeletedSubs] = useState(new Set())
  const [deletedChapters, setDeletedChapters] = useState(new Set()) // ⭐ NEW
  const [newSubs, setNewSubs] = useState({}) // { chapterIdx: [titles...] }

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
    updated[chapterIdx].push(`Mục ${chapterIdx + 1}.${currentCount + newCount + 1} (mới)`)
    setNewSubs(updated)
  }

  // Build final curriculum for submit
  const buildFinalCurriculum = () => {
    const finalChapters = editedCurriculum.chapters
      .map((chapter, chIdx) => {
        // ⭐ Skip deleted chapters
        if (deletedChapters.has(chIdx)) return null

        // Filter out deleted subsections
        const activeSubs = chapter.subsections
          .map((sub, subIdx) => {
            if (deletedSubs.has(`${chIdx}-${subIdx}`)) return null
            return {
              title: sub.title,
              description: sub.description || `Content about ${sub.title}`,
              search_query: sub.search_query || sub.title,
              section_type: sub.section_type || 'medium',
            }
          })
          .filter(Boolean)

        // Add new subsections
        const newSubsForChapter = newSubs[chIdx] || []
        const newSubObjects = newSubsForChapter.map(title => ({
          title,
          description: `Content about ${title}`,
          search_query: title,
          section_type: 'medium',
        }))

        return {
          title: chapter.title,
          subsections: [...activeSubs, ...newSubObjects],
        }
      })
      .filter(Boolean) // Remove nulls (deleted chapters and empty chapters)
      .filter(ch => ch.subsections.length > 0) // Remove empty chapters

    return {
      topic: editedCurriculum.topic,
      chapters: finalChapters,
    }
  }

  const handleConfirm = () => {
    const finalCurriculum = buildFinalCurriculum()
    onConfirm(finalCurriculum)
  }

  const handleReset = () => {
    setEditedCurriculum(curriculum)
    setDeletedSubs(new Set())
    setDeletedChapters(new Set()) // ⭐ NEW
    setNewSubs({})
    if (onReset) onReset()
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-lg">
        <h3 className="font-semibold text-blue-900 mb-1">
          ✏️ Xem xét & Chỉnh sửa Cấu trúc Giáo Trình
        </h3>
        <p className="text-sm text-blue-700">
          Chỉnh sửa tiêu đề, xóa hoặc thêm mục trước khi tạo nội dung. 
          Nhấn <strong>Xác nhận</strong> khi sẵn sàng.
        </p>
      </div>

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
                      Chương {chIdx + 1}: {chapter.title}
                    </p>
                    <p className="text-xs text-red-600 mt-1">
                      Chương này đã bị xóa và sẽ không được tạo nội dung
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleRestoreChapter(chIdx)}
                  className="px-4 py-2 text-sm bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                >
                  ↩️ Khôi phục
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
                  📖 Chương {chIdx + 1}
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
                title="Xóa toàn bộ chương này"
              >
                <span>🗑️</span>
                <span className="text-sm">Xóa chương</span>
              </button>
            </div>

            {/* Warning if empty */}
            {totalVisible === 0 && (
              <div className="bg-yellow-50 border border-yellow-200 rounded p-2 mb-3">
                <p className="text-xs text-yellow-700">
                  ⚠️ Chương {chIdx + 1} không còn mục nào — sẽ bị bỏ qua khi tạo nội dung.
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
                      title="Xóa mục này"
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
                      placeholder="Nhập tiêu đề mục mới..."
                    />
                    <button
                      onClick={() => handleDeleteNewSub(chIdx, newIdx)}
                      className="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg"
                      title="Xóa mục mới"
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
              ➕ Thêm mục
            </button>
          </div>
        )
      })}

      {/* Action buttons */}
      <div className="flex gap-3">
        <Button
          onClick={handleConfirm}
          className="flex-1"
        >
          ✅ Xác nhận & Bắt đầu tạo nội dung
        </Button>
        <Button
          variant="secondary"
          onClick={handleReset}
        >
          🔄 Đặt lại
        </Button>
      </div>
    </div>
  )
}