import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { textbooksAPI } from '../api/textbooks'
import { Navbar } from '../components/layout/Navbar'
import { Button } from '../components/common/Button'
import { TextbookForm } from '../components/textbooks/TextbookForm'
import { ProgressBar } from '../components/textbooks/ProgressBar'
import { WorkflowCard } from '../components/textbooks/WorkflowCard'
import { SubStageCard } from '../components/textbooks/SubStageCard'
import { CurriculumEditor } from '../components/textbooks/CurriculumEditor'
import { ContentSidebar } from '../components/textbooks/ContentSidebar'

export function CreateTextbookPage() {
  const navigate = useNavigate()
  const { textbookId: urlTextbookId } = useParams() // ⭐ Get textbookId from URL
  const { user } = useAuth()

  const [textbookId, setTextbookId] = useState(urlTextbookId || null)
  const [phase, setPhase] = useState('idle')
  const [progressData, setProgressData] = useState(null)
  const [configExpanded, setConfigExpanded] = useState(false)
  const [error, setError] = useState(null)
  const [submittedTopic, setSubmittedTopic] = useState('')
  const [sidebarExpanded, setSidebarExpanded] = useState(true) // ⭐ Sidebar toggle state
  const pollingRef = useRef(null)

  // ⭐ Load existing textbook if textbookId in URL
  useEffect(() => {
    if (urlTextbookId) {
      const loadTextbook = async () => {
        try {
          const response = await textbooksAPI.getProgress(urlTextbookId)
          const data = response.data.progress_data

          if (data) {
            setTextbookId(urlTextbookId)
            setProgressData(data)
            setPhase(data.phase || 'idle')
            setSubmittedTopic(data.topic || '')
          }
        } catch (err) {
          console.error('❌ Load textbook error:', err)
          setError({ message: 'Không thể tải thông tin giáo trình' })
        }
      }

      loadTextbook()
    }
  }, [urlTextbookId])

  // Poll progress every 2 seconds
  useEffect(() => {
    if (!textbookId || phase === 'idle' || phase === 'done') {
      return
    }

    const poll = async () => {
      try {
        const response = await textbooksAPI.getProgress(textbookId)
        const data = response.data.progress_data

        if (data) {
          setProgressData(data)
          setPhase(data.phase)

          if (data.phase === 'done') {
            clearInterval(pollingRef.current)
            setTimeout(() => {
              navigate('/dashboard', {
                state: { message: 'Tạo giáo trình thành công!' }
              })
            }, 3000)
          }
        }
      } catch (err) {
        console.error('❌ Poll error:', err)
      }
    }

    pollingRef.current = setInterval(poll, 2000)
    poll()

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    }
  }, [textbookId, phase, navigate])

  const handleSubmit = async (formData) => {
    setError(null)

    try {
      console.log('🔵 Creating textbook:', formData)

      const response = await textbooksAPI.create({
        ...formData,
        export_formats: ['PDF', 'Word'],
      })

      const textbook = response.data
      setTextbookId(textbook.id)
      setPhase('planning')
      setSubmittedTopic(formData.topic)
      setConfigExpanded(false)

      // ⭐ Update URL to include textbookId
      navigate(`/create/${textbook.id}`, { replace: true })

      console.log('✅ Textbook created:', textbook)

    } catch (err) {
      console.error('❌ Create error:', err)
      const errorDetail = err.response?.data?.detail

      if (errorDetail?.validation_failed) {
        setError({
          message: errorDetail.reason || 'Chủ đề không hợp lệ',
          suggestions: errorDetail.suggestion
            ? errorDetail.suggestion.split('|').map(s => s.trim())
            : [],
        })
      } else {
        setError({
          message: typeof errorDetail === 'string'
            ? errorDetail
            : (errorDetail?.message || 'Không thể tạo giáo trình'),
        })
      }
    }
  }

  const handleStop = async () => {
    if (!textbookId) return

    try {
      await textbooksAPI.stop(textbookId)
      setPhase('idle')
      setTextbookId(null)
      setProgressData(null)
      setSubmittedTopic('')

      // ⭐ Navigate back to /create (new textbook)
      navigate('/create', { replace: true })

      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    } catch (err) {
      console.error('❌ Stop error:', err)
    }
  }

  const handleCurriculumConfirm = async (curriculum) => {
    try {
      console.log('🔵 Confirming curriculum:', curriculum)

      await textbooksAPI.confirmCurriculum(textbookId, curriculum)
      setPhase('generating')

      console.log('✅ Curriculum confirmed')

    } catch (err) {
      console.error('❌ Confirm curriculum error:', err)
      setError({ message: 'Không thể xác nhận giáo trình' })
    }
  }

  const isIdle = phase === 'idle'
  const isActive = phase !== 'idle' && phase !== 'done'
  const showSidebar = phase === 'generating'

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />

      <div className="w-full">

        {/* Header */}
        <div className="bg-white border-b border-gray-200">
            <div className="content-container-lg py-6">
                <h1 className="text-3xl font-bold text-center text-primary mb-2">
                📚 Hệ Thống Tạo Giáo Trình Tự Động
                </h1>
                <p className="text-center text-gray-600 text-sm mb-6">
                Hệ thống AI — vui lòng kiểm tra lại kết quả trước khi sử dụng
                </p>
            </div>
            </div>

        {/* Sidebar + Main content */}
        <div className="flex min-h-screen">

          {/* ⭐ Sidebar Toggle Button (only when sidebar should show) */}
          {showSidebar && (
            <button
              onClick={() => setSidebarExpanded(!sidebarExpanded)}
              className="fixed left-4 top-32 z-50 bg-white border border-gray-300 rounded-lg p-2 shadow-lg hover:bg-gray-50 transition-all"
              title={sidebarExpanded ? 'Ẩn sidebar' : 'Hiện sidebar'}
            >
              {sidebarExpanded ? (
                <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                </svg>
              ) : (
                <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                </svg>
              )}
            </button>
          )}

          {/* ⭐ Left sidebar (collapsible with animation) */}
          {showSidebar && (
            <div 
              className={`
                flex-shrink-0 bg-gray-100 border-r border-gray-200 min-h-screen p-4
                transition-all duration-300 ease-in-out
                ${sidebarExpanded ? 'w-64 opacity-100' : 'w-0 opacity-0 overflow-hidden'}
              `}
            >
              {sidebarExpanded && <ContentSidebar progressData={progressData} />}
            </div>
          )}

          {/* Main content area */}
          <div className="flex-1">
            <div className={`${showSidebar && sidebarExpanded ? 'content-container-md' : 'content-container-sm'} py-4`}>

              {/* ⭐ FORM BOX - ALWAYS VISIBLE */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">

                {/* Idle: full interactive form */}
                {isIdle && (
                  <TextbookForm
                    onSubmit={handleSubmit}
                    loading={false}
                    error={error}
                    user={user}
                    configExpanded={configExpanded}
                    onToggleConfig={() => setConfigExpanded(!configExpanded)}
                  />
                )}

                {/* Running: disabled form with config visible */}
                {!isIdle && (
                  <div className="space-y-4">
                    {/* Topic display */}
                    <div className="flex items-center justify-between gap-4 pb-4 border-b border-gray-200">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-gray-500 mb-1">Chủ đề</p>
                        <p className="font-semibold text-gray-900 truncate">
                          {submittedTopic || progressData?.topic || '…'}
                        </p>
                      </div>

                      {/* Stop button (hide during review) */}
                      {phase !== 'done' && phase !== 'reviewing' && (
                        <Button
                          variant="danger"
                          onClick={handleStop}
                          className="flex-shrink-0"
                        >
                          ⛔ Dừng lại
                        </Button>
                      )}
                    </div>

                    {/* ⭐ Config area (collapsed but visible) */}
                    <div>
                      <button
                        onClick={() => setConfigExpanded(!configExpanded)}
                        className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
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
                              <span className="ml-2 font-medium">{progressData?.total_chapters || '—'}</span>
                            </div>
                            <div>
                              <span className="text-gray-600">Mức độ:</span>
                              <span className="ml-2 font-medium">{progressData?.content_level || '—'}</span>
                            </div>
                          </div>
                          <p className="text-xs text-gray-500 italic">
                            Cấu hình này không thể thay đổi khi đang chạy
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* ⭐ PROGRESS SECTION - BELOW FORM */}
              {isActive && progressData && (
                <div className="space-y-4">

                  <ProgressBar
                    value={progressData.progress_value || 0}
                    statusText={progressData.status_text || ''}
                  />

                  {progressData.planner_status && (
                    <WorkflowCard
                      stage="planner"
                      status={progressData.planner_status}
                      message="Lập dàn ý giáo trình"
                    />
                  )}

                  {/* Ingestion shown only after curriculum confirmation */}
                  {phase === 'generating' && progressData.ingestion_status && (
                    <WorkflowCard
                      stage="ingestion"
                      status={progressData.ingestion_status}
                      message="Thu thập dữ liệu"
                    />
                  )}

                  {phase === 'generating' && progressData.sub_stages && (
                    <SubStageCard
                      subStages={progressData.sub_stages}
                      chapter={progressData.current_chapter}
                      subsection={progressData.current_subsection}
                      totalChapters={progressData.total_chapters}
                      subsectionsInChapter={progressData.subsections_in_chapter}
                    />
                  )}

                  {progressData.publisher_status && (
                    <WorkflowCard
                      stage="publisher"
                      status={progressData.publisher_status}
                      message="Xuất bản tài liệu"
                    />
                  )}
                </div>
              )}

              {/* ── CURRICULUM EDITOR ── */}
              {phase === 'reviewing' && progressData?.curriculum_data && (
                <div className="mt-4">
                  <CurriculumEditor
                    curriculum={progressData.curriculum_data}
                    onConfirm={handleCurriculumConfirm}
                    onReset={() => setPhase('planning')}
                  />
                </div>
              )}

              {/* ── ERROR ── */}
              {progressData?.error_message && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mt-4">
                  <p className="text-red-600 font-medium">❌ Lỗi</p>
                  <p className="text-red-700 text-sm mt-1">{progressData.error_message}</p>
                </div>
              )}

              {/* ── SUCCESS ── */}
              {phase === 'done' && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4 mt-4">
                  <p className="text-green-800 font-semibold">🎉 Tạo giáo trình thành công!</p>
                  <p className="text-green-700 text-sm mt-1">Đang chuyển về dashboard...</p>
                </div>
              )}

              {/* ── TIPS (idle only) ── */}
              {isIdle && (
                <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-gray-900 mb-2">
                    💡 Mẹo để có kết quả tốt hơn
                  </h3>
                  <ul className="text-xs text-gray-600 space-y-1">
                    <li>• Hãy cụ thể với chủ đề (VD: "Python cho Data Science" thay vì "Lập trình")</li>
                    <li>• Nhiều chương hơn = nội dung toàn diện hơn</li>
                    <li>• Quá trình tạo thường mất 2-5 phút tùy cấu hình</li>
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}