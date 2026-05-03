import { useState } from 'react'
import { Button } from '../common/Button'
import { Slider } from '../common/Slider'

const CONTENT_LEVEL_OPTIONS = [
  { value: 'Ngắn',       desc: '~350-550 từ/mục — Súc tích' },
  { value: 'Trung Bình', desc: '~600-950 từ/mục — Cân bằng' },
  { value: 'Dài',        desc: '~1000-1500 từ/mục — Chi tiết' },
  { value: 'Rất Dài',    desc: '~1400-2200 từ/mục — Học thuật' },
]

const LEVEL_COST = { 'Ngắn': 2, 'Trung Bình': 3, 'Dài': 5, 'Rất Dài': 8 }

export function TextbookForm({ onSubmit, loading, error, user, configExpanded, onToggleConfig }) {
  const [topic, setTopic] = useState('')
  const [errors, setErrors] = useState({})

  const [numChapters, setNumChapters] = useState(3)
  const [contentLevel, setContentLevel] = useState('Trung Bình')
  const [maxSubsections, setMaxSubsections] = useState(3)
  const [imagesEnabled, setImagesEnabled] = useState(false)
  const [imageWarningPending, setImageWarningPending] = useState(false)

  const calculateCost = () => {
    return (
      10 +
      numChapters * 2 +
      (LEVEL_COST[contentLevel] ?? 3) +
      maxSubsections +
      (imagesEnabled ? 5 : 0)
    )
  }

  const estimatedCost = calculateCost()
  const canAfford = user?.credits >= estimatedCost

  const handleToggleImages = () => {
    if (!imagesEnabled) {
      setImageWarningPending(true)
    } else {
      setImagesEnabled(false)
    }
  }

  const validate = () => {
    const newErrors = {}
    if (!topic.trim()) {
      newErrors.topic = 'Chủ đề không được để trống'
    } else if (topic.trim().length < 3) {
      newErrors.topic = 'Chủ đề phải có ít nhất 3 ký tự'
    }
    if (!canAfford) {
      newErrors.credits = `Không đủ credits. Cần ${estimatedCost}, có ${user?.credits}`
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!validate()) return
    onSubmit({
      topic: topic.trim(),
      num_chapters: numChapters,
      content_level: contentLevel,
      max_subsections_per_chapter: maxSubsections,
      enable_images: imagesEnabled,
    })
  }

  const handleSuggestionClick = (suggestion) => {
    setTopic(suggestion)
    setErrors({})
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Gear + Input + Submit — same row */}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={onToggleConfig}
          disabled={loading}
          className="flex-shrink-0 px-4 py-3 bg-white border-2 border-gray-300 rounded-lg hover:bg-gray-50 text-gray-700 text-lg transition-colors disabled:opacity-50"
          title="Mở/đóng cấu hình"
        >
          ⚙️
        </button>

        <div className="flex-1 min-w-0">
          <input
            type="text"
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value)
              if (errors.topic) setErrors({ ...errors, topic: '' })
            }}
            placeholder="Nhập chủ đề giáo trình..."
            className={`
              w-full px-4 py-3 text-lg border-2 rounded-lg
              focus:outline-none focus:ring-2 focus:ring-primary
              ${errors.topic ? 'border-red-500' : 'border-gray-300'}
            `}
            disabled={loading}
            autoFocus
          />
        </div>

        <Button
          type="submit"
          className="flex-shrink-0 px-6 py-3 text-lg"
          loading={loading}
          disabled={!canAfford || loading}
        >
          🚀
        </Button>
      </div>

      {/* Local topic error */}
      {errors.topic && (
        <p className="text-sm text-red-500 -mt-4">{errors.topic}</p>
      )}

      {/* Backend validation error + suggestions */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <span className="text-lg">⚠️</span>
            <div className="flex-1">
              <p className="text-sm text-red-600 font-medium">
                {error.message || 'Không thể tạo giáo trình'}
              </p>
              {error.suggestions && error.suggestions.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs text-red-700 mb-2">💡 Gợi ý:</p>
                  <div className="flex flex-wrap gap-2">
                    {error.suggestions.map((s, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => handleSuggestionClick(s)}
                        className="px-3 py-1 bg-white border border-red-300 rounded-full text-xs text-red-700 hover:bg-red-50 transition-colors"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Config panel (collapsible) */}
      {configExpanded && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

            {/* Left — Nội dung */}
            <div className="space-y-6">
              <h3 className="font-semibold text-gray-900">📖 Nội dung</h3>

              <Slider
                label="Số chương"
                value={numChapters}
                onChange={setNumChapters}
                min={1}
                max={10}
                disabled={loading}
              />

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  Độ dài nội dung
                </label>
                <div className="space-y-2">
                  {CONTENT_LEVEL_OPTIONS.map(({ value, desc }) => (
                    <label
                      key={value}
                      className={`
                        flex items-start p-3 rounded-lg border-2 cursor-pointer transition-colors
                        ${contentLevel === value
                          ? 'border-primary bg-primary/5'
                          : 'border-gray-200 hover:border-gray-300 bg-white'
                        }
                        ${loading ? 'opacity-50 cursor-not-allowed' : ''}
                      `}
                    >
                      <input
                        type="radio"
                        name="contentLevel"
                        value={value}
                        checked={contentLevel === value}
                        onChange={(e) => setContentLevel(e.target.value)}
                        disabled={loading}
                        className="mt-0.5 mr-3 text-primary focus:ring-primary"
                      />
                      <div>
                        <div className="font-medium text-gray-900 text-sm">{value}</div>
                        <div className="text-xs text-gray-500 mt-0.5">{desc}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <Slider
                label="Số mục tối đa / chương"
                value={maxSubsections}
                onChange={setMaxSubsections}
                min={2}
                max={10}
                disabled={loading}
              />
            </div>

            {/* Right — Hình ảnh & Xuất */}
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">🖼️ Hình ảnh & Xuất</h3>

              <div className="p-3 bg-white rounded-lg border border-gray-200 mb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">
                      Chèn hình ảnh minh họa
                    </label>
                    <p className="text-xs text-gray-500 mt-1">
                      {imagesEnabled
                        ? '✓ Tải về, resize và chèn tự động.'
                        : '✗ Bỏ qua — giáo trình chỉ có text.'
                      }
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleToggleImages}
                    disabled={loading}
                    className={`
                      relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full
                      transition-colors focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2
                      ${imagesEnabled ? 'bg-primary' : 'bg-gray-200'}
                      ${loading ? 'opacity-50 cursor-not-allowed' : ''}
                    `}
                  >
                    <span className={`
                      inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                      ${imagesEnabled ? 'translate-x-6' : 'translate-x-1'}
                    `} />
                  </button>
                </div>
              </div>

              {/* Image warning confirmation */}
              {imageWarningPending && (
                <div className="mb-3 bg-yellow-50 border border-yellow-300 rounded-lg p-3">
                  <p className="text-sm font-semibold text-yellow-800 mb-1">
                    ⚠️ Lưu ý về hình ảnh minh họa:
                  </p>
                  <ul className="text-xs text-yellow-700 space-y-0.5 mb-2">
                    <li>• Hình ảnh được tìm kiếm từ web hoặc tạo bởi AI</li>
                    <li>• Có thể không hoàn toàn chính xác với nội dung giáo trình</li>
                    <li>• Nên kiểm tra lại từng hình sau khi xuất bản</li>
                  </ul>
                  <p className="text-xs text-yellow-800 mb-3">
                    Bạn có muốn tiếp tục chèn hình ảnh không?
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => { setImagesEnabled(true); setImageWarningPending(false) }}
                      className="flex-1 py-1.5 text-xs font-medium bg-primary text-white rounded-md hover:bg-primary/90 transition-colors"
                    >
                      ✅ Xác nhận
                    </button>
                    <button
                      type="button"
                      onClick={() => setImageWarningPending(false)}
                      className="flex-1 py-1.5 text-xs font-medium bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
                    >
                      ❌ Hủy
                    </button>
                  </div>
                </div>
              )}

              {/* Export formats — always both */}
              <div className="p-3 bg-white rounded-lg border border-gray-200">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Định dạng xuất
                </label>
                <div className="flex gap-2">
                  <span className="px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-medium">PDF ✓</span>
                  <span className="px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-medium">Word ✓</span>
                </div>
                <p className="text-xs text-gray-400 mt-2">Cả hai định dạng luôn được xuất cùng lúc.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cost Estimation */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm font-medium text-gray-700">Chi phí ước tính:</span>
          <span className="text-lg font-bold text-primary">{estimatedCost} credits</span>
        </div>
        <div className="flex justify-between items-center text-xs text-gray-600">
          <span>Số dư của bạn:</span>
          <span className={canAfford ? 'text-green-600 font-semibold' : 'text-red-600 font-semibold'}>
            {user?.credits || 0} credits
          </span>
        </div>
      </div>

      {errors.credits && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm text-red-600">{errors.credits}</p>
        </div>
      )}
    </form>
  )
}
