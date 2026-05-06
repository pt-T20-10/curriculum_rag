import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Navbar } from '../components/layout/Navbar'

export function TextbookDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [textbook, setTextbook] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const loadTextbook = async () => {
      try {
        setLoading(true)
        
        // ⭐ FIX: Use direct API call to /textbooks/{id} endpoint
        // This endpoint returns full textbook data including pdf_path and docx_path
        const response = await fetch(
          `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/v1/textbooks/${id}`,
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
        
        // ⭐ DEBUG: Log to see what we get
        console.log('=== TEXTBOOK DATA ===')
        console.log('Full data:', data)
        console.log('PDF path:', data.pdf_path)
        console.log('DOCX path:', data.docx_path)
        console.log('Status:', data.status)
        console.log('====================')
        
        setTextbook(data)
      } catch (err) {
        console.error('Load textbook error:', err)
        setError('Không thể tải thông tin giáo trình')
      } finally {
        setLoading(false)
      }
    }

    if (id) {
      loadTextbook()
    }
  }, [id])

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
            <p className="text-gray-600">Đang tải...</p>
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
            <p className="text-gray-600 mb-4">{error || 'Không tìm thấy giáo trình'}</p>
            <button
              onClick={() => navigate('/dashboard')}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              ← Về Dashboard
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Construct PDF URL - extract relative path from absolute path
  // Backend stores: "D:\Thesis\curriculum_rag\backend\outputs\file.pdf"
  // We need: "outputs/file.pdf"
  const extractRelativePath = (path) => {
    if (!path) return null
    // Extract everything after "outputs" (or "outputs\")
    const match = path.match(/outputs[/\\](.+)$/)
    if (match) {
      // URL encode the filename to handle Vietnamese characters
      const filename = match[1].replace(/\\/g, '/')
      const encodedFilename = encodeURIComponent(filename)
      return `outputs/${encodedFilename}`
    }
    // If already relative, just normalize slashes and encode
    const normalized = path.replace(/\\/g, '/')
    const parts = normalized.split('/')
    const filename = parts.pop()
    const dir = parts.join('/')
    return dir ? `${dir}/${encodeURIComponent(filename)}` : encodeURIComponent(filename)
  }

  const pdfUrl = textbook.pdf_path 
    ? `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/${extractRelativePath(textbook.pdf_path)}`
    : null

  const docxUrl = textbook.docx_path
    ? `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/${extractRelativePath(textbook.docx_path)}`
    : null

  // ⭐ DEBUG: Log constructed URL
  console.log('Constructed PDF URL:', pdfUrl)
  console.log('Constructed DOCX URL:', docxUrl)

  if (!pdfUrl) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md">
            <div className="text-6xl mb-4">📄</div>
            <p className="text-gray-600 mb-2">PDF chưa sẵn sàng</p>
            <p className="text-sm text-gray-500 mb-4">Giáo trình đang được xử lý...</p>
            
            {/* ⭐ DEBUG INFO */}
            <div className="mt-4 p-4 bg-gray-100 rounded-lg text-left text-xs">
              <p className="font-bold mb-2">Debug Info:</p>
              <p>Status: {textbook.status || textbook.phase || 'unknown'}</p>
              <p>PDF Path: {textbook.pdf_path || 'null'}</p>
              <p>DOCX Path: {textbook.docx_path || 'null'}</p>
              <p>Title: {textbook.title || textbook.topic || 'unknown'}</p>
            </div>
            
            <button
              onClick={() => navigate('/dashboard')}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              ← Về Dashboard
            </button>
          </div>
        </div>
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
              onClick={() => navigate('/dashboard')}
              className="text-gray-600 hover:text-gray-900"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
            </button>
            <div>
              <h1 className="text-xl font-bold text-gray-900">{textbook.title}</h1>
              <p className="text-sm text-gray-500">{textbook.num_chapters} chương</p>
            </div>
          </div>
          
          <div className="flex gap-2">
            {docxUrl && (
              <button
                onClick={() => {
                  const link = document.createElement('a')
                  link.href = docxUrl
                  link.download = ''
                  link.click()
                }}
                className="px-4 py-2 bg-blue-50 text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
                  <path d="M14 2v6h6M10 18v-5h4v5M10 13h4" fill="white" />
                </svg>
                Tải Word
              </button>
            )}
            {pdfUrl && (
              <button
                onClick={() => {
                  const link = document.createElement('a')
                  link.href = pdfUrl
                  link.download = ''
                  link.click()
                }}
                className="px-4 py-2 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
                  <path d="M14 2v6h6M9 13h6M9 17h6M9 9h1" fill="white" />
                </svg>
                Tải PDF
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
    </div>
  )
}