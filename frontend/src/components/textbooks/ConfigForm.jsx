import { useState } from 'react'

export function ConfigForm({
  onSubmit,
  loading,
  error,
  user,
  configExpanded,
  onToggleConfig,
  isActive = false,
  currentTopic = '',
  submittedConfig = null // ⭐ NEW - actual submitted config
}) {
  const [formData, setFormData] = useState({
    topic: '',
    num_chapters: 3,
    content_level: 'Trung Bình',
    max_subsections_per_chapter: 5,
    enable_images: true
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!formData.topic.trim()) {
      return
    }
    onSubmit(formData)
  }

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }))
  }

  if (isActive) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4 pb-4 border-b border-gray-200">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-gray-500 mb-1">Chủ đề</p>
            <p className="font-semibold text-gray-900 truncate">
              {currentTopic || '…'}
            </p>
          </div>
        </div>

        <button
          onClick={onToggleConfig}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
        >
          <svg
            className={`w-4 h-4 transition-transform ${configExpanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="font-medium">⚙️ Cấu hình</span>
          <span className="text-xs text-gray-500">(đang chạy với cấu hình này)</span>
        </button>

        {configExpanded && (
          <div className="mt-3 p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-3 opacity-60">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-600">Số chương:</span>
                <span className="ml-2 font-medium">{submittedConfig?.num_chapters || formData.num_chapters}</span>
              </div>
              <div>
                <span className="text-gray-600">Mức độ:</span>
                <span className="ml-2 font-medium">{submittedConfig?.content_level || formData.content_level}</span>
              </div>
              <div>
                <span className="text-gray-600">Mục/chương:</span>
                <span className="ml-2 font-medium">{submittedConfig?.max_subsections_per_chapter || formData.max_subsections_per_chapter}</span>
              </div>
              <div>
                <span className="text-gray-600">Hình ảnh:</span>
                <span className="ml-2 font-medium">{(submittedConfig?.enable_images !== undefined ? submittedConfig.enable_images : formData.enable_images) ? 'Có' : 'Không'}</span>
              </div>
            </div>
            <p className="text-xs text-gray-500 italic">
              Cấu hình này không thể thay đổi khi đang chạy
            </p>
          </div>
        )}
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Topic Input */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Chủ đề giáo trình <span className="text-red-500">*</span>
        </label>
        <textarea
          name="topic"
          value={formData.topic}
          onChange={handleChange}
          placeholder="VD: Lập trình Python cho Data Science, Lịch sử Việt Nam hiện đại, ..."
          className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none transition-all"
          rows={3}
          disabled={loading}
          required
        />
        <p className="mt-1 text-xs text-gray-500">
          Hãy cụ thể để có kết quả tốt nhất (VD: "Python cho Data Science" thay vì "Lập trình")
        </p>
      </div>

      {/* Advanced Config Toggle */}
      <button
        type="button"
        onClick={onToggleConfig}
        className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
      >
        <svg
          className={`w-4 h-4 transition-transform ${configExpanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-medium">⚙️ Tùy chỉnh nâng cao</span>
      </button>

      {/* Advanced Config */}
      {configExpanded && (
        <div className="space-y-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
          {/* Number of Chapters */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Số chương
            </label>
            <input
              type="number"
              name="num_chapters"
              value={formData.num_chapters}
              onChange={handleChange}
              min={2}
              max={12}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={loading}
            />
            <p className="mt-1 text-xs text-gray-500">
              Từ 2-12 chương. Nhiều chương hơn = nội dung toàn diện hơn
            </p>
          </div>

          {/* Content Level */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Độ dài nội dung
            </label>
            <select
              name="content_level"
              value={formData.content_level}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={loading}
            >
              <option value="Ngắn">Ngắn (súc tích)</option>
              <option value="Trung Bình">Trung Bình (cân bằng)</option>
              <option value="Dài">Dài (chi tiết)</option>
              <option value="Rất Dài">Rất Dài (toàn diện)</option>
            </select>
            <p className="mt-1 text-xs text-gray-500">
              {formData.content_level === 'Ngắn' && '~300-500 từ/mục (nhanh, ngắn gọn)'}
              {formData.content_level === 'Trung Bình' && '~500-800 từ/mục (cân bằng chi tiết)'}
              {formData.content_level === 'Dài' && '~800-1200 từ/mục (chi tiết, sâu sắc)'}
              {formData.content_level === 'Rất Dài' && '~1200-1500 từ/mục (toàn diện nhất)'}
            </p>
          </div>

          {/* Subsections per Chapter */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Số mục tối đa mỗi chương
            </label>
            <input
              type="number"
              name="max_subsections_per_chapter"
              value={formData.max_subsections_per_chapter}
              onChange={handleChange}
              min={2}
              max={8}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={loading}
            />
            <p className="mt-1 text-xs text-gray-500">
              Từ 2-8 mục. Nhiều mục hơn = cấu trúc chi tiết hơn
            </p>
          </div>

          {/* Enable Images */}
          <div>
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="enable_images"
                name="enable_images"
                checked={formData.enable_images}
                onChange={handleChange}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                disabled={loading}
              />
              <label htmlFor="enable_images" className="text-sm font-medium text-gray-700">
                Tạo hình ảnh minh họa
              </label>
            </div>
            
            {/* Warning when images enabled */}
            {formData.enable_images && (
              <div className="mt-2 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
                <div className="flex gap-2">
                  <svg className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-yellow-800">
                      ⚠️ Lưu ý về tính năng tạo hình ảnh
                    </p>
                    <p className="text-xs text-yellow-700 mt-1">
                      Hình ảnh được tạo bởi AI có thể không chính xác 100%. 
                      Vui lòng kiểm tra và chỉnh sửa nếu cần thiết.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-600 font-medium text-sm">❌ {error.message}</p>
          {error.suggestions && error.suggestions.length > 0 && (
            <div className="mt-2">
              <p className="text-red-700 text-sm font-medium">💡 Gợi ý:</p>
              <ul className="mt-1 text-red-700 text-sm space-y-1">
                {error.suggestions.map((suggestion, idx) => (
                  <li key={idx}>• {suggestion}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Credits Display */}
      {user && (
        <div className="flex items-center justify-between p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <span className="text-sm text-blue-900">
            💳 Credits khả dụng: <span className="font-bold">{user.credits}</span>
          </span>
          <span className="text-xs text-blue-700">Tạo giáo trình: -1 credit</span>
        </div>
      )}

      {/* Submit Button */}
      <button
        type="submit"
        disabled={loading || !formData.topic.trim() || (user && user.credits < 1)}
        className="w-full py-3 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 focus:ring-4 focus:ring-blue-200 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Đang xử lý...
          </span>
        ) : (
          '🚀 Tạo giáo trình'
        )}
      </button>
    </form>
  )
}