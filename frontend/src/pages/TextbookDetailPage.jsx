import { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Navbar } from '../components/layout/Navbar'
import { WordFieldUpdateNoticeModal } from '../components/textbooks/WordFieldUpdateNoticeModal'
import { buildBackendUrl } from '../utils/apiConfig'
import { getDocxUrl, getPdfUrl } from '../utils/helpers'

export function TextbookDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useTranslation()
  const [textbook, setTextbook] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showWordNotice, setShowWordNotice] = useState(false)
  const isAdminView = location.pathname.startsWith('/admin/textbooks/')
  const detailEndpoint = isAdminView
    ? `/api/v1/admin/textbooks/${id}`
    : `/api/v1/textbooks/${id}`
  const backPath = isAdminView ? '/admin/textbooks' : '/dashboard'
  const backLabel = isAdminView
    ? t('textbook.detail.backAdminTextbooks')
    : t('textbook.detail.backDashboard')

  useEffect(() => {
    const loadTextbook = async () => {
      try {
        setLoading(true)
        
        // Direct API call returns full textbook data including pdf_path/docx_path.
        const response = await fetch(
          buildBackendUrl(detailEndpoint),
          {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('token')}`,
            },
          }
        )
        
        if (!response.ok) {
          throw new Error('Failed to load textbook')
        }
        
        const data = await response.json()
        
        setTextbook(data)
      } catch (err) {
        console.error('Load textbook error:', err)
        setError(t('textbook.loadError'))
      } finally {
        setLoading(false)
      }
    }

    if (id) {
      loadTextbook()
    }
  }, [detailEndpoint, id, t])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <svg className="animate-spin h-12 w-12 text-blue-600 mx-auto mb-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <p className="text-gray-600">{t('app.loading')}</p>
          </div>
        </div>
      </div>
    )
  }

  if (error || !textbook) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="text-6xl mb-4">❌</div>
            <p className="text-gray-600 mb-4">{error || t('textbook.detail.notFound')}</p>
            <button
              onClick={() => navigate(backPath)}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              ← {backLabel}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const pdfUrl = getPdfUrl(textbook.pdf_path)
  const docxUrl = getDocxUrl(textbook.docx_path)
  const languageLabel = textbook.language
    ? t(`textbook.language.${textbook.language}`, { defaultValue: textbook.language.toUpperCase() })
    : null

  const downloadFile = (url) => {
    const link = document.createElement('a')
    link.href = url
    link.download = ''
    link.click()
  }

  if (!pdfUrl) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md">
            <div className="text-6xl mb-4">📄</div>
            <p className="text-gray-600 mb-2">{t('textbook.detail.pdfUnavailable')}</p>
            <p className="text-sm text-gray-500 mb-4">
              {textbook.error_message || t('textbook.detail.exportFailed')}
            </p>

            {docxUrl && (
              <button
                type="button"
                onClick={() => setShowWordNotice(true)}
                className="inline-flex px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                {t('textbook.detail.downloadWord')}
              </button>
            )}
            
            <button
              onClick={() => navigate(backPath)}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              ← {backLabel}
            </button>
          </div>
        </div>

        <WordFieldUpdateNoticeModal
          isOpen={showWordNotice}
          onClose={() => setShowWordNotice(false)}
          onConfirm={() => downloadFile(docxUrl)}
        />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />
      
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(backPath)}
              className="text-gray-600 hover:text-gray-900"
              title={backLabel}
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
            </button>
            <div>
              <h1 className="text-xl font-bold text-gray-900">{textbook.title}</h1>
              <p className="text-sm text-gray-500">
                {t('textbook.detail.chapters', { count: textbook.num_chapters })}
                {languageLabel ? ` · ${t('textbook.detail.language', { language: languageLabel })}` : ''}
              </p>
              {isAdminView && (
                <p className="mt-1 text-xs text-amber-700">
                  {t('textbook.detail.adminViewing')}
                  {textbook.owner_email
                    ? ` · ${t('textbook.detail.owner', {
                      name: textbook.owner_name || textbook.owner_email,
                      email: textbook.owner_email,
                    })}`
                    : ''}
                </p>
              )}
            </div>
          </div>
          
          <div className="flex gap-2">
            {docxUrl && (
              <button
                onClick={() => setShowWordNotice(true)}
                className="px-4 py-2 bg-blue-50 text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
                  <path d="M14 2v6h6M10 18v-5h4v5M10 13h4" fill="white" />
                </svg>
                {t('textbook.detail.downloadWord')}
              </button>
            )}
            {pdfUrl && (
              <button
                onClick={() => downloadFile(pdfUrl)}
                className="px-4 py-2 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
                  <path d="M14 2v6h6M9 13h6M9 17h6M9 9h1" fill="white" />
                </svg>
                {t('textbook.detail.downloadPdf')}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* PDF Viewer */}
      <div className="flex-1 bg-gray-900">
        <iframe
          src={pdfUrl}
          className="w-full h-full"
          title={textbook.title}
          style={{ border: 'none', minHeight: 'calc(100vh - 140px)' }}
        />
      </div>

      <WordFieldUpdateNoticeModal
        isOpen={showWordNotice}
        onClose={() => setShowWordNotice(false)}
        onConfirm={() => downloadFile(docxUrl)}
      />
    </div>
  )
}
