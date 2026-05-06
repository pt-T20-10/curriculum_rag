export function CompletionModal({ isOpen, onClose, textbookData, onViewDashboard }) {
  if (!isOpen || !textbookData) return null

  const handleDownload = (fileType) => {
    const path = fileType === 'pdf' ? textbookData.pdf_path : textbookData.docx_path
    if (!path) return

    // Trigger download
    window.open(path, '_blank')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative bg-white rounded-lg shadow-2xl max-w-lg w-full mx-4 p-6">
        {/* Success Icon */}
        <div className="flex items-center justify-center w-16 h-16 mx-auto mb-4 bg-green-100 rounded-full">
          <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>

        {/* Title */}
        <h3 className="text-2xl font-bold text-gray-900 text-center mb-2">
          🎉 Tạo giáo trình thành công!
        </h3>

        {/* Textbook Info */}
        <div className="mb-6">
          <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-sm text-green-800 font-medium mb-1">
              📚 {textbookData.title || textbookData.topic}
            </p>
            <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-green-700">
              <div>
                <span className="font-medium">Tổng chương:</span> {textbookData.total_chapters || 0}
              </div>
              <div>
                <span className="font-medium">Tổng mục:</span> {textbookData.total_subsections || 0}
              </div>
            </div>
          </div>
        </div>

        {/* Download Options */}
        <div className="mb-6 space-y-3">
          <p className="text-sm font-medium text-gray-700 text-center mb-3">
            💾 Tải xuống giáo trình
          </p>
          
          <div className="grid grid-cols-2 gap-3">
            {/* PDF Download */}
            {textbookData.pdf_path && (
              <button
                onClick={() => handleDownload('pdf')}
                className="flex flex-col items-center gap-2 p-4 bg-red-50 border-2 border-red-200 rounded-lg hover:bg-red-100 transition-all group"
              >
                <svg className="w-8 h-8 text-red-600 group-hover:scale-110 transition-transform" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
                  <path d="M14 2v6h6M9 13h6M9 17h6M9 9h1" fill="white" />
                </svg>
                <span className="text-sm font-medium text-red-900">PDF</span>
                <span className="text-xs text-red-700">Định dạng chuẩn</span>
              </button>
            )}

            {/* DOCX Download */}
            {textbookData.docx_path && (
              <button
                onClick={() => handleDownload('docx')}
                className="flex flex-col items-center gap-2 p-4 bg-blue-50 border-2 border-blue-200 rounded-lg hover:bg-blue-100 transition-all group"
              >
                <svg className="w-8 h-8 text-blue-600 group-hover:scale-110 transition-transform" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" />
                  <path d="M14 2v6h6M10 18v-5h4v5M10 13h4" fill="white" />
                </svg>
                <span className="text-sm font-medium text-blue-900">Word</span>
                <span className="text-xs text-blue-700">Có thể chỉnh sửa</span>
              </button>
            )}
          </div>

          {!textbookData.pdf_path && !textbookData.docx_path && (
            <p className="text-sm text-gray-500 text-center">
              Đang xử lý file, vui lòng đợi...
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="space-y-2">
          <button
            onClick={onViewDashboard}
            className="w-full px-4 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            📊 Về Dashboard
          </button>
          <button
            onClick={onClose}
            className="w-full px-4 py-2 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors"
          >
            Đóng
          </button>
        </div>

        {/* Tips */}
        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-xs text-yellow-800">
            💡 <span className="font-medium">Lưu ý:</span> Vui lòng kiểm tra và hiệu chỉnh nội dung trước khi sử dụng chính thức.
          </p>
        </div>
      </div>
    </div>
  )
}