import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export function ContentPreview({ content, currentChapter, currentSubsection, totalChapters, totalSubsections }) {
  const contentRef = useRef(null)

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (contentRef.current && content) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [content])

  const wordCount = content ? content.split(/\s+/).filter(Boolean).length : 0

  if (!content) {
    return (
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-xl font-bold text-gray-800">📖 Nội Dung Giáo Trình</h2>
          <p className="text-sm text-gray-500 mt-1">
            Nội dung sẽ hiển thị khi đang viết...
          </p>
        </div>

        {/* Empty State */}
        <div className="flex-1 flex items-center justify-center px-6 py-12">
          <div className="text-center">
            <div className="text-6xl mb-4">📝</div>
            <p className="text-gray-500">Nội dung giáo trình sẽ xuất hiện ở đây</p>
            <p className="text-xs text-gray-400 mt-2">
              Bắt đầu tạo giáo trình để xem preview
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-gray-200 px-6 py-3 bg-gray-50">
          <div className="flex justify-between text-sm text-gray-600">
            <span>Chương: 0/{totalChapters || 0}</span>
            <span>Mục: 0/{totalSubsections || 0}</span>
            <span>0 từ</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 py-4">
        <h2 className="text-xl font-bold text-gray-800">📖 Nội Dung Giáo Trình</h2>
        <p className="text-sm text-gray-500 mt-1">
          Preview nội dung đang được tạo
        </p>
      </div>

      {/* Content Area */}
      <div 
        ref={contentRef}
        className="flex-1 overflow-y-auto px-6 py-4"
      >
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={{
              // Custom heading styles
              h1: (props) => (
                <h1 className="text-3xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b-2 border-blue-600" {...props} />
              ),
              h2: (props) => (
                <h2 className="text-2xl font-bold text-gray-800 mt-6 mb-3" {...props} />
              ),
              h3: (props) => (
                <h3 className="text-xl font-semibold text-gray-700 mt-4 mb-2" {...props} />
              ),
              
              // Code blocks
              code: ({inline, className, children, ...props}) => {
                const match = /language-(\w+)/.exec(className || '')
                return !inline ? (
                  <div className="my-4">
                    {match && (
                      <div className="bg-gray-700 text-gray-200 text-xs px-3 py-1 rounded-t-md font-mono">
                        {match[1]}
                      </div>
                    )}
                    <pre className={`${match ? 'rounded-t-none' : ''} bg-gray-900 text-gray-100 p-4 rounded-md overflow-x-auto`}>
                      <code className={className} {...props}>
                        {children}
                      </code>
                    </pre>
                  </div>
                ) : (
                  <code className="bg-gray-100 text-red-600 px-1.5 py-0.5 rounded text-sm font-mono" {...props}>
                    {children}
                  </code>
                )
              },
              
              // Blockquotes (for images)
              blockquote: ({node, children, ...props}) => {
                const text = node?.children?.[0]?.children?.[0]?.value || ''
                
                // Check if it's an image placeholder
                if (text.includes('[IMAGE:')) {
                  const match = text.match(/\[IMAGE:\s*([^|]+)\s*\|\s*([^\]]+)\]/)
                  if (match) {
                    return (
                      <div className="my-6 p-4 bg-blue-50 border-l-4 border-blue-500 rounded-r-lg">
                        <div className="flex items-start gap-3">
                          <div className="flex-shrink-0 w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center text-white">
                            🖼️
                          </div>
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
              
              // Tables
              table: (props) => (
                <div className="my-6 overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-300 border border-gray-300" {...props} />
                </div>
              ),
              thead: (props) => (
                <thead className="bg-gray-50" {...props} />
              ),
              th: (props) => (
                <th className="px-4 py-2 text-left text-sm font-semibold text-gray-900 border-b border-gray-300" {...props} />
              ),
              td: (props) => (
                <td className="px-4 py-2 text-sm text-gray-700 border-b border-gray-200" {...props} />
              ),
              
              // Lists
              ul: (props) => (
                <ul className="list-disc list-inside my-4 space-y-2 text-gray-700" {...props} />
              ),
              ol: (props) => (
                <ol className="list-decimal list-inside my-4 space-y-2 text-gray-700" {...props} />
              ),
              
              // Paragraphs
              p: (props) => (
                <p className="my-3 text-gray-700 leading-relaxed" {...props} />
              ),
              
              // Strong/Bold
              strong: (props) => (
                <strong className="font-bold text-gray-900" {...props} />
              ),
              
              // Links
              a: (props) => (
                <a className="text-blue-600 hover:text-blue-800 underline" {...props} />
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>

        {/* Loading Indicator (if generating) */}
        {currentChapter > 0 && (
          <div className="mt-6 flex items-center gap-2 text-blue-600">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span className="text-sm font-medium">Đang viết tiếp...</span>
          </div>
        )}
      </div>

      {/* Footer with Stats */}
      <div className="border-t border-gray-200 px-6 py-3 bg-gray-50">
        <div className="flex justify-between text-sm text-gray-600">
          <span>Chương: {(currentChapter || 0) + 1}/{totalChapters || 0}</span>
          <span>Mục: {(currentSubsection || 0) + 1}/{totalSubsections || 0}</span>
          <span>{wordCount.toLocaleString()} từ</span>
        </div>
      </div>
    </div>
  )
}