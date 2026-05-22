import { useNavigate } from 'react-router-dom'
import { StatusBadge, ContentTypeBadge } from '../common/Badge'
import { Button } from '../common/Button'
import { getPdfUrl } from '../../utils/helpers'

export function TextbookCard({ textbook }) {
  const navigate = useNavigate()

  const formatDate = (dateString) => {
    const date = new Date(dateString)
    return date.toLocaleDateString('vi-VN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  }

  const isGenerating = textbook.status === 'generating'
  const isCompleted = textbook.status === 'done' || textbook.status === 'completed'

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900 mb-2 line-clamp-2">
            {textbook.title}
          </h3>
          <div className="flex flex-wrap gap-2">
            <StatusBadge status={textbook.status} />
            <ContentTypeBadge type={textbook.content_type} />
          </div>
        </div>
      </div>

      {/* Info */}
      <div className="space-y-2 text-sm text-gray-600 mb-4">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          <span>{textbook.num_chapters} chương</span>
        </div>

        <div className="flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <span>Tạo lúc {formatDate(textbook.created_at)}</span>
        </div>

        {textbook.completed_at && (
          <div className="flex items-center gap-2 text-green-600">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>Hoàn thành {formatDate(textbook.completed_at)}</span>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {isGenerating ? (
          <Button
            onClick={() => navigate(`/create/${textbook.id}`)}
            className="flex-1"
            variant="primary"
          >
            <span className="flex items-center justify-center gap-2">
              <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Xem tiến độ →
            </span>
          </Button>
        ) : isCompleted ? (
          <Button
            onClick={() => navigate(`/textbooks/${textbook.id}`)}
            className="flex-1"
            variant="primary"
          >
            📄 Xem chi tiết
          </Button>
        ) : null}

        {textbook.pdf_path && isCompleted && (
          <Button
            variant="secondary"
            onClick={() => {
              const pdfUrl = getPdfUrl(textbook.pdf_path)
              if (pdfUrl) {
                window.open(pdfUrl, '_blank')
              }
            }}
            title="Tải PDF"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </Button>
        )}
      </div>

    </div>
  )
}