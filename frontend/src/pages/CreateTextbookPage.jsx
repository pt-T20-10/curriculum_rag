import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
import { CONTENT_LEVEL } from '../constants/textbookOptions'

export function CreateTextbookPage() {
  const navigate = useNavigate()
  const { textbookId: urlTextbookId } = useParams()
  const { user, loadUser } = useAuth()
  const { i18n, t } = useTranslation()

  const [textbookId, setTextbookId] = useState(urlTextbookId || null)
  const [phase, setPhase] = useState('idle')
  const [progressData, setProgressData] = useState(null)
  const [configExpanded, setConfigExpanded] = useState(true)
  const [error, setError] = useState(null)
  const [textbookTitle, setTextbookTitle] = useState('')
  const [submittedConfig, setSubmittedConfig] = useState(null) // ⭐ NEW - actual config
  const [sidebarExpanded, setSidebarExpanded] = useState(true)
  const [rightSidebarExpanded, setRightSidebarExpanded] = useState(true)
  const [confirmedCurriculum, setConfirmedCurriculum] = useState(null)
  const [showStopModal, setShowStopModal] = useState(false)
  const [showCompletionModal, setShowCompletionModal] = useState(false)
  const [completedTextbookData, setCompletedTextbookData] = useState(null)
  const [confirmingCurriculum, setConfirmingCurriculum] = useState(false)
  const [creatingTextbook, setCreatingTextbook] = useState(false)
  const [formulaConfirmation, setFormulaConfirmation] = useState(null)
  const pollingRef = useRef(null)

  const clearDraftState = () => {
    setPhase('idle')
    setTextbookId(null)
    setProgressData(null)
    setTextbookTitle('')
    setSubmittedConfig(null)
    setConfirmedCurriculum(null)
    setCompletedTextbookData(null)
    setShowCompletionModal(false)
    setError(null)
    setConfirmingCurriculum(false)
    setCreatingTextbook(false)
    setFormulaConfirmation(null)
    setConfigExpanded(true)

    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

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
            // Don't reset to 'idle' if Celery hasn't written phase yet (race on new submit)
            if (data.phase) {
              setPhase(data.phase)
            }
            // Don't overwrite a valid title with empty string
            if (data.title || data.topic) {
              setTextbookTitle(data.title || data.topic)
            }

            // Always restore config from API (fields now always present after backend fix)
            setSubmittedConfig({
              topic: data.topic || '',
              num_chapters: data.num_chapters || 3,
              content_level: data.content_level || CONTENT_LEVEL.MEDIUM,
              max_subsections_per_chapter: data.max_subsections_per_chapter || 5,
              enable_images: data.enable_images !== undefined ? data.enable_images : true,
              language: data.language || 'vi',
              planning_mode: data.planning_mode || 'auto',
              textbook_mode: data.textbook_mode || 'standard',
              formula_policy: data.formula_policy || 'auto',
              formula_need: data.formula_need || 'none',
              source_preferences: data.source_preferences || {
                source_mode: 'system_default',
                selected_source_ids: [],
                custom_urls: [],
                custom_domains: [],
              },
            })

            const curriculum = data.curriculum_data
            if (curriculum) {
              setConfirmedCurriculum(curriculum)
            }
          }
        } catch (err) {
          console.error('Load textbook error:', err)
          setError({ message: t('textbook.loadError') })
        }
      }

      loadTextbook()
    }
  }, [urlTextbookId, t])

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
          
          // Update to AI-generated title once planner produces it
          if (data.title) {
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
    if (creatingTextbook) return
    setError(null)
    setCreatingTextbook(true)
    const uiLanguage = (i18n.resolvedLanguage || i18n.language || 'vi').split('-')[0]

    try {
      const response = await textbooksAPI.create({
        ...formData,
        ui_language: uiLanguage,
        export_formats: ['PDF', 'Word'],
      })

      const textbook = response.data
      setTextbookId(textbook.id)
      setPhase('planning')
      setTextbookTitle(formData.topic)
      setSubmittedConfig({
        ...formData,
        language: textbook.language || uiLanguage,
        planning_mode: formData.planning_mode || 'auto',
        textbook_mode: formData.textbook_mode || 'standard',
        formula_policy: textbook.formula_policy || formData.formula_policy || 'auto',
        formula_need: textbook.formula_need || 'none',
        source_preferences: formData.source_preferences || {
          source_mode: 'system_default',
          selected_source_ids: [],
          custom_urls: [],
          custom_domains: [],
        },
      }) // ⭐ Save actual submitted config
      setConfigExpanded(false)

      navigate(`/create/${textbook.id}`, { replace: true })
    } catch (err) {
      setCreatingTextbook(false)
      console.error('Create error:', err)
      const errorDetail = err.response?.data?.detail

      if (errorDetail?.validation_failed) {
        setError({
          message: errorDetail.reason || t('textbook.topicInvalid'),
          suggestions: errorDetail.suggestion
            ? errorDetail.suggestion.split('|').map(s => s.trim())
            : [],
        })
      } else if (errorDetail?.formula_confirmation_required) {
        setFormulaConfirmation({
          formData,
          reason: errorDetail.reason || t('textbook.formulaConfirmDescription'),
        })
        setError(null)
      } else if (errorDetail?.formula_conflict) {
        setError({
          message: errorDetail.reason || t('textbook.formulaConflict'),
        })
      } else {
        setError({
          message: typeof errorDetail === 'string'
            ? errorDetail
            : (errorDetail?.message || t('textbook.genericCreateError')),
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
      clearDraftState()
      navigate('/create', { replace: true })
    } catch (err) {
      console.error('Stop error:', err)
    }
  }

  const handleCurriculumConfirm = async (curriculum) => {
    if (!textbookId || confirmingCurriculum) return

    try {
      setConfirmingCurriculum(true)
      setConfirmedCurriculum(curriculum)
      await textbooksAPI.confirmCurriculum(textbookId, curriculum)
      await loadUser?.()
      setPhase('generating')
    } catch (err) {
      console.error('Confirm curriculum error:', err)
      const detail = err.response?.data?.detail
      setError({ message: typeof detail === 'string' ? detail : t('textbook.confirmError') })
    } finally {
      setConfirmingCurriculum(false)
    }
  }

  const handlePlanningReset = async () => {
    if (!textbookId) {
      clearDraftState()
      navigate('/create', { replace: true })
      return
    }

    try {
      await textbooksAPI.stop(textbookId)
      clearDraftState()
      navigate('/create', { replace: true })
    } catch (err) {
      console.error('Reset planning draft error:', err)
      setError({ message: t('textbook.resetDraftError') })
    }
  }

  const handleViewDashboard = () => {
    navigate('/dashboard', {
      state: { message: t('dashboard.successCreated') }
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
    <div className="h-screen overflow-hidden bg-gray-50 flex flex-col">
      <Navbar />

      <div className="flex-1 overflow-hidden min-h-0">
        <ThreeColumnLayout
          leftSidebar={
            showLeftSidebar ? (
              <ContentSidebar progressData={enhancedProgressData} />
            ) : (
              <div className="p-6 text-center text-gray-400">
                <p className="text-sm">{t('textbook.sidebarWaiting')}</p>
              </div>
            )
          }

          centerPanel={
            <div className="p-6">
              {/* Title */}
              <div className="mb-6 text-center">
                <h1 className="text-2xl font-bold text-gray-800">
                  📚 {t('textbook.createTitle')}
                  {displayTopic && ` - ${displayTopic}`}
                </h1>
                <p className="text-sm text-gray-500 mt-1">
                  {t('textbook.createSubtitle')}
                </p>
              </div>

              {/* Form Box */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
                {!isIdle && (
                  <div className="flex items-center justify-between gap-4 mb-4">
                    <div className="flex-1" />
                    {phase !== 'done' && (
                      <Button
                        variant="danger"
                        onClick={handleStopClick}
                      >
                        ⛔ {t('textbook.stop')}
                      </Button>
                    )}
                  </div>
                )}

                <ConfigForm
                  onSubmit={handleSubmit}
                  loading={creatingTextbook}
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
                    statusText={progressData.status_text || ''}
                  />

                  {progressData.planner_status && (
                    <WorkflowCard
                      stage="planner"
                      status={progressData.planner_status}
                      message={t('textbook.workflow.planner')}
                    />
                  )}

                  {phase === 'generating' && progressData.ingestion_status && (
                    <WorkflowCard
                      stage="ingestion"
                      status={progressData.ingestion_status}
                      message={t('textbook.workflow.ingestion')}
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
                      message={t('textbook.workflow.publisher')}
                    />
                  )}
                </div>
              )}

              {/* Curriculum Editor */}
              {phase === 'reviewing' && progressData?.curriculum_data && (
                <div className="mt-4">
                  <CurriculumEditor
                    curriculum={progressData.curriculum_data}
                    textbookId={textbookId}
                    onConfirm={handleCurriculumConfirm}
                    onReset={handlePlanningReset}
                    confirming={confirmingCurriculum}
                  />
                </div>
              )}

              {/* Error */}
              {progressData?.error_message && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mt-4">
                  <p className="text-red-600 font-medium">❌ {t('app.error')}</p>
                  <p className="text-red-700 text-sm mt-1">{progressData.error_message}</p>
                </div>
              )}

              {/* Tips (idle only) */}
              {isIdle && (
                <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-gray-900 mb-2">
                    💡 {t('textbook.tipsTitle')}
                  </h3>
                  <ul className="text-xs text-gray-600 space-y-1">
                    <li>• {t('textbook.tipsSpecific')}</li>
                    <li>• {t('textbook.tipsChapters')}</li>
                    
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
              curriculumData={enhancedProgressData?.curriculum_data}
              isGenerating={phase === 'generating'}
            />
          }

          leftCollapsed={!sidebarExpanded}
          rightCollapsed={!rightSidebarExpanded}
          onToggleLeft={() => setSidebarExpanded(!sidebarExpanded)}
          onToggleRight={() => setRightSidebarExpanded(!rightSidebarExpanded)}
        />
      </div>

      {/* Modals */}
      {formulaConfirmation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
            onClick={() => setFormulaConfirmation(null)}
          />
          <div className="relative mx-4 w-full max-w-lg rounded-lg bg-white p-6 shadow-2xl">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-xl font-bold text-blue-700">
              ∑
            </div>
            <h3 className="mb-2 text-center text-xl font-bold text-gray-900">
              {t('textbook.formulaConfirmTitle')}
            </h3>
            <p className="mb-4 text-center text-sm text-gray-600">
              {formulaConfirmation.reason}
            </p>
            <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {t('textbook.formulaConfirmNote')}
            </p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => {
                  const nextData = {
                    ...formulaConfirmation.formData,
                    formula_policy: 'exclude',
                    formula_confirmed: true,
                  }
                  setFormulaConfirmation(null)
                  handleSubmit(nextData)
                }}
                className="flex-1 rounded-lg bg-gray-200 px-4 py-2 font-medium text-gray-700 transition-colors hover:bg-gray-300"
              >
                {t('textbook.formulaConfirmNo')}
              </button>
              <button
                type="button"
                onClick={() => {
                  const nextData = {
                    ...formulaConfirmation.formData,
                    formula_policy: 'include',
                    formula_confirmed: true,
                  }
                  setFormulaConfirmation(null)
                  handleSubmit(nextData)
                }}
                className="flex-1 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white transition-colors hover:bg-blue-700"
              >
                {t('textbook.formulaConfirmYes')}
              </button>
            </div>
          </div>
        </div>
      )}

      <StopWarningModal
        isOpen={showStopModal}
        onClose={() => setShowStopModal(false)}
        onConfirm={handleStopConfirm}
        currentProgress={progressData?.status_text}
        isPlanningDraft={phase === 'planning' || phase === 'reviewing'}
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
