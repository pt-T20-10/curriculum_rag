import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ThreeColumnLayout from '../components/ThreeColumnLayout'
import { useAuth } from '../context/AuthContext'
import { textbooksAPI } from '../api/textbooks'
import { Navbar } from '../components/layout/Navbar'
import { Button } from '../components/common/Button'
import { ConfigForm } from '../components/textbooks/ConfigForm'
import { ProgressBar } from '../components/textbooks/ProgressBar'
import { WorkflowCard } from '../components/textbooks/WorkflowCard'
import { SubStageCard } from '../components/textbooks/SubStageCard'
import { CurriculumEditor } from '../components/textbooks/CurriculumEditor'
import { ContentSidebar } from '../components/textbooks/ContentSidebar'
import { ContentPreview } from '../components/textbooks/ContentPreview'
import { StopWarningModal } from '../components/textbooks/StopWarningModal'
import { CompletionModal } from '../components/textbooks/CompletionModal'

export function CreateTextbookPage() {
  const navigate = useNavigate()
  const { textbookId: urlTextbookId } = useParams()
  const { user } = useAuth()

  const [textbookId, setTextbookId] = useState(urlTextbookId || null)
  const [phase, setPhase] = useState('idle')
  const [progressData, setProgressData] = useState(null)
  const [configExpanded, setConfigExpanded] = useState(false)
  const [error, setError] = useState(null)
  const [textbookTitle, setTextbookTitle] = useState('')
  const [submittedConfig, setSubmittedConfig] = useState(null) // ⭐ NEW - actual config
  const [sidebarExpanded, setSidebarExpanded] = useState(true)
  const [rightSidebarExpanded, setRightSidebarExpanded] = useState(true)
  const [confirmedCurriculum, setConfirmedCurriculum] = useState(null)
  const [showStopModal, setShowStopModal] = useState(false)
  const [showCompletionModal, setShowCompletionModal] = useState(false)
  const [completedTextbookData, setCompletedTextbookData] = useState(null)
  const pollingRef = useRef(null)

  // Load existing textbook
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
            setTextbookTitle(data.title || data.topic || '')
            
            
            if (data.num_chapters || data.content_level) {
              setSubmittedConfig({
                topic: data.topic || '',
                num_chapters: data.num_chapters || 3,
                content_level: data.content_level || 'Trung Bình',
                max_subsections_per_chapter: data.max_subsections_per_chapter || 5,
                enable_images: data.enable_images !== undefined ? data.enable_images : true
              })
            }
            
            const curriculum = data.curriculum_data
            if (curriculum) {
              setConfirmedCurriculum(curriculum)
            }
          }
        } catch (err) {
          console.error('Load textbook error:', err)
          setError({ message: 'Không thể tải thông tin giáo trình' })
        }
      }

      loadTextbook()
    }
  }, [urlTextbookId])

  // Polling for progress
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
          
          // Update title if available
          if (data.title && !textbookTitle) {
            setTextbookTitle(data.title)
          }

          if (data.phase === 'done') {
            clearInterval(pollingRef.current)
            setCompletedTextbookData(data)
            setShowCompletionModal(true)
          }
        }
      } catch (err) {
        console.error('Poll error:', err)
      }
    }

    pollingRef.current = setInterval(poll, 2000)
    poll()

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    }
  }, [textbookId, phase, navigate, textbookTitle])

  const handleSubmit = async (formData) => {
    setError(null)

    try {
      const response = await textbooksAPI.create({
        ...formData,
        export_formats: ['PDF', 'Word'],
      })

      const textbook = response.data
      setTextbookId(textbook.id)
      setPhase('planning')
      setTextbookTitle(formData.topic)
      setSubmittedConfig(formData) // ⭐ Save actual submitted config
      setConfigExpanded(false)

      navigate(`/create/${textbook.id}`, { replace: true })
    } catch (err) {
      console.error('Create error:', err)
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

  const handleStopClick = () => {
    setShowStopModal(true)
  }

  const handleStopConfirm = async () => {
    if (!textbookId) return

    try {
      await textbooksAPI.stop(textbookId)
      setPhase('idle')
      setTextbookId(null)
      setProgressData(null)
      setTextbookTitle('')
      setSubmittedConfig(null) // ⭐ Clear config
      setConfirmedCurriculum(null)

      navigate('/create', { replace: true })

      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    } catch (err) {
      console.error('Stop error:', err)
    }
  }

  const handleCurriculumConfirm = async (curriculum) => {
    try {
      setConfirmedCurriculum(curriculum)
      await textbooksAPI.confirmCurriculum(textbookId, curriculum)
      setPhase('generating')
    } catch (err) {
      console.error('Confirm curriculum error:', err)
      setError({ message: 'Không thể xác nhận giáo trình' })
    }
  }

  const handleViewDashboard = () => {
    navigate('/dashboard', {
      state: { message: 'Tạo giáo trình thành công!' }
    })
  }

  const isIdle = phase === 'idle'
  const isActive = phase !== 'idle' && phase !== 'done'
  const showLeftSidebar = phase === 'generating'

  // Enhanced progress data with confirmed curriculum
  const enhancedProgressData = useMemo(() => {
    if (!progressData) return null
    
    return {
      ...progressData,
      curriculum_data: confirmedCurriculum || progressData.curriculum_data
    }
  }, [progressData, confirmedCurriculum])

  // Extract content for preview
  const previewContent = useMemo(() => {
    if (!progressData) return null
    
    // Backend uses 'current_content_preview' not 'current_content'!
    const content = progressData.current_content_preview ||  // ⭐ CORRECT field name
                   progressData.current_content || 
                   progressData.final_content || 
                   progressData.content ||
                   progressData.generated_content ||
                   progressData.text ||
                   null
    
    if (phase === 'generating' && !content) {
      console.log('ContentPreview - No content found. Available fields:', Object.keys(progressData))
    }
    
    return content
  }, [progressData, phase])

  // Display topic with fallbacks
  const displayTopic = useMemo(() => {
    return textbookTitle || 
           progressData?.title || 
           progressData?.topic || 
           progressData?.core_topic ||
           ''
  }, [textbookTitle, progressData])

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />

      <div className="flex-1">
        <ThreeColumnLayout
          leftSidebar={
            showLeftSidebar ? (
              <ContentSidebar progressData={enhancedProgressData} />
            ) : (
              <div className="p-6 text-center text-gray-400">
                <p className="text-sm">Sidebar sẽ hiển thị khi đang tạo nội dung</p>
              </div>
            )
          }

          centerPanel={
            <div className="p-6">
              {/* Title */}
              <div className="mb-6 text-center">
                <h1 className="text-2xl font-bold text-gray-800">
                  📚 Tạo Giáo Trình AI
                  {displayTopic && ` - ${displayTopic}`}
                </h1>
                <p className="text-sm text-gray-500 mt-1">
                  Hệ thống AI — vui lòng kiểm tra lại kết quả trước khi sử dụng
                </p>
              </div>

              {/* Form Box */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
                {!isIdle && (
                  <div className="flex items-center justify-between gap-4 mb-4">
                    <div className="flex-1" />
                    {phase !== 'done' && phase !== 'reviewing' && (
                      <Button
                        variant="danger"
                        onClick={handleStopClick}
                      >
                        ⛔ Dừng lại
                      </Button>
                    )}
                  </div>
                )}

                <ConfigForm
                  onSubmit={handleSubmit}
                  loading={false}
                  error={error}
                  user={user}
                  configExpanded={configExpanded}
                  onToggleConfig={() => setConfigExpanded(!configExpanded)}
                  isActive={isActive}
                  currentTopic={displayTopic}
                  submittedConfig={submittedConfig}
                />
              </div>

              {/* Progress Section */}
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
                      curriculumData={enhancedProgressData?.curriculum_data}
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

              {/* Curriculum Editor */}
              {phase === 'reviewing' && progressData?.curriculum_data && (
                <div className="mt-4">
                  <CurriculumEditor
                    curriculum={progressData.curriculum_data}
                    onConfirm={handleCurriculumConfirm}
                    onReset={() => setPhase('planning')}
                  />
                </div>
              )}

              {/* Error */}
              {progressData?.error_message && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mt-4">
                  <p className="text-red-600 font-medium">❌ Lỗi</p>
                  <p className="text-red-700 text-sm mt-1">{progressData.error_message}</p>
                </div>
              )}

              {/* Tips (idle only) */}
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
          }

          rightSidebar={
            <ContentPreview 
              content={previewContent}
              currentChapter={progressData?.current_chapter}
              currentSubsection={progressData?.current_subsection}
              totalChapters={progressData?.total_chapters}
              totalSubsections={progressData?.total_subsections}
            />
          }

          leftCollapsed={!sidebarExpanded}
          rightCollapsed={!rightSidebarExpanded}
          onToggleLeft={() => setSidebarExpanded(!sidebarExpanded)}
          onToggleRight={() => setRightSidebarExpanded(!rightSidebarExpanded)}
        />
      </div>

      {/* Modals */}
      <StopWarningModal
        isOpen={showStopModal}
        onClose={() => setShowStopModal(false)}
        onConfirm={handleStopConfirm}
        currentProgress={progressData?.status_text}
      />

      <CompletionModal
        isOpen={showCompletionModal}
        onClose={() => setShowCompletionModal(false)}
        textbookData={completedTextbookData}
        onViewDashboard={handleViewDashboard}
      />
    </div>
  )
}