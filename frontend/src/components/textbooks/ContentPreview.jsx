import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { getSubsectionProgress } from '../../utils/progressMetrics'

const NEAR_BOTTOM_THRESHOLD = 120 // px — within this distance = "at bottom"

export function ContentPreview({
  content,
  currentChapter,
  currentSubsection,
  totalChapters,
  totalSubsections,
  curriculumData,
  isGenerating,
}) {
  const { i18n, t } = useTranslation()
  const contentRef = useRef(null)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const isAtBottomRef = useRef(true) // tracks whether user is near bottom

  // Check scroll position and update button visibility
  const handleScroll = useCallback(() => {
    const el = contentRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    isAtBottomRef.current = distFromBottom <= NEAR_BOTTOM_THRESHOLD
    setShowScrollBtn(distFromBottom > NEAR_BOTTOM_THRESHOLD)
  }, [])

  // Auto-scroll only if user is already near the bottom
  useEffect(() => {
    if (isAtBottomRef.current && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [content])

  const scrollToBottom = () => {
    if (contentRef.current) {
      contentRef.current.scrollTo({ top: contentRef.current.scrollHeight, behavior: 'smooth' })
    }
  }

  const wordCount = content ? content.split(/\s+/).filter(Boolean).length : 0
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const {
    chapterNumber,
    currentGlobalSubsection,
  } = getSubsectionProgress({
    curriculumData,
    currentChapter,
    currentSubsection,
    totalSubsections,
  })

  if (!content) {
    return (
      <div className="h-full flex flex-col">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-xl font-bold text-gray-800">📖 {t('textbook.contentPreview.title')}</h2>
          <p className="text-sm text-gray-500 mt-1">{t('textbook.contentPreview.pendingSubtitle')}</p>
        </div>
        <div className="flex-1 flex items-center justify-center px-6 py-12">
          <div className="text-center">
            <div className="text-6xl mb-4">📝</div>
            <p className="text-gray-500">{t('textbook.contentPreview.emptyText')}</p>
            <p className="text-xs text-gray-400 mt-2">{t('textbook.contentPreview.emptyHint')}</p>
          </div>
        </div>
        <div className="border-t border-gray-200 px-6 py-3 bg-gray-50">
          <div className="flex justify-between text-sm text-gray-600">
            <span>{t('textbook.contentPreview.chapterCounter', { current: 0, total: totalChapters || 0 })}</span>
            <span>{t('textbook.contentPreview.subsectionCounter', { current: 0, total: totalSubsections || 0 })}</span>
            <span>{t('textbook.contentPreview.wordCount', { count: 0 })}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 py-4 flex-shrink-0">
        <h2 className="text-xl font-bold text-gray-800">📖 {t('textbook.contentPreview.title')}</h2>
        <p className="text-sm text-gray-500 mt-1">{t('textbook.contentPreview.activeSubtitle')}</p>
      </div>

      {/* Content Area — relative so the scroll button can be positioned inside */}
      <div className="flex-1 min-h-0 relative">
        <div
          ref={contentRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto px-6 py-4"
        >
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                h1: (props) => (
                  <h1 className="text-3xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b-2 border-blue-600" {...props} />
                ),
                h2: (props) => (
                  <h2 className="text-2xl font-bold text-gray-800 mt-6 mb-3" {...props} />
                ),
                h3: (props) => (
                  <h3 className="text-xl font-semibold text-gray-700 mt-4 mb-2" {...props} />
                ),
                code: ({ inline, className, children, ...props }) => {
                  const match = /language-(\w+)/.exec(className || '')
                  return !inline ? (
                    <div className="my-4">
                      {match && (
                        <div className="bg-gray-700 text-gray-200 text-xs px-3 py-1 rounded-t-md font-mono">
                          {match[1]}
                        </div>
                      )}
                      <pre className={`${match ? 'rounded-t-none' : ''} bg-gray-900 text-gray-100 p-4 rounded-md overflow-x-auto`}>
                        <code className={className} {...props}>{children}</code>
                      </pre>
                    </div>
                  ) : (
                    <code className="bg-gray-100 text-red-600 px-1.5 py-0.5 rounded text-sm font-mono" {...props}>
                      {children}
                    </code>
                  )
                },
                blockquote: ({ node, children, ...props }) => {
                  const text = node?.children?.[0]?.children?.[0]?.value || ''
                  if (text.includes('[IMAGE:')) {
                    const match = text.match(/\[IMAGE:\s*([^|]+)\s*\|\s*([^\]]+)\]/)
                    if (match) {
                      return (
                        <div className="my-6 p-4 bg-blue-50 border-l-4 border-blue-500 rounded-r-lg">
                          <div className="flex items-start gap-3">
                            <div className="flex-shrink-0 w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center text-white">🖼️</div>
                            <div className="flex-1">
                              <p className="font-semibold text-blue-900 text-sm">{match[1].trim()}</p>
                              <p className="text-blue-700 text-xs mt-1">{match[2].trim()}</p>
                            </div>
                          </div>
                        </div>
                      )
                    }
                  }
                  return (
                    <blockquote className="border-l-4 border-gray-300 pl-4 py-2 italic text-gray-700 my-4" {...props}>
                      {children}
                    </blockquote>
                  )
                },
                table: (props) => (
                  <div className="my-6 overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-300 border border-gray-300" {...props} />
                  </div>
                ),
                thead: (props) => <thead className="bg-gray-50" {...props} />,
                th: (props) => (
                  <th className="px-4 py-2 text-left text-sm font-semibold text-gray-900 border-b border-gray-300" {...props} />
                ),
                td: (props) => (
                  <td className="px-4 py-2 text-sm text-gray-700 border-b border-gray-200" {...props} />
                ),
                ul: (props) => <ul className="list-disc list-inside my-4 space-y-2 text-gray-700" {...props} />,
                ol: (props) => <ol className="list-decimal list-inside my-4 space-y-2 text-gray-700" {...props} />,
                p: (props) => <p className="my-3 text-gray-700 leading-relaxed" {...props} />,
                strong: (props) => <strong className="font-bold text-gray-900" {...props} />,
                a: (props) => <a className="text-blue-600 hover:text-blue-800 underline" {...props} />,
              }}
            >
              {content}
            </ReactMarkdown>
          </div>

          {/* Writing indicator — shown at the very end of the content */}
          {isGenerating && (
            <div className="mt-6 flex items-center gap-2 text-blue-600 pb-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              <span className="text-sm font-medium">{t('textbook.contentPreview.writingMore')}</span>
            </div>
          )}
        </div>

        {/* Scroll-to-bottom FAB — appears when user scrolls up */}
        {showScrollBtn && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-4 right-4 z-10 flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium px-3 py-1.5 rounded-full shadow-lg transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
            {t('textbook.contentPreview.scrollDown')}
          </button>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-gray-200 px-6 py-3 bg-gray-50 flex-shrink-0">
        <div className="flex justify-between text-sm text-gray-600">
          <span>{t('textbook.contentPreview.chapterCounter', { current: chapterNumber, total: totalChapters || 0 })}</span>
          <span>{t('textbook.contentPreview.subsectionCounter', { current: currentGlobalSubsection, total: totalSubsections || 0 })}</span>
          <span>{t('textbook.contentPreview.wordCount', { count: wordCount.toLocaleString(locale) })}</span>
        </div>
      </div>
    </div>
  )
}
