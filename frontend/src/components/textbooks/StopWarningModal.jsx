export function StopWarningModal({ isOpen, onClose, onConfirm, currentProgress }) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative bg-white rounded-lg shadow-2xl max-w-md w-full mx-4 p-6">
        {/* Icon */}
        <div className="flex items-center justify-center w-12 h-12 mx-auto mb-4 bg-red-100 rounded-full">
          <svg className="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>

        {/* Title */}
        <h3 className="text-xl font-bold text-gray-900 text-center mb-2">
          ⚠️ Dừng tạo giáo trình?
        </h3>

        {/* Message */}
        <div className="mb-6 space-y-2">
          <p className="text-gray-700 text-center">
            Bạn có chắc chắn muốn dừng quá trình này?
          </p>
          
          {currentProgress && (
            <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
              <p className="text-sm text-yellow-800 font-medium mb-1">
                📊 Tiến độ hiện tại:
              </p>
              <p className="text-sm text-yellow-700">
                {currentProgress}
              </p>
            </div>
          )}

          <p className="text-sm text-red-600 font-medium text-center">
            ⚠️ Toàn bộ tiến độ sẽ bị mất và không thể khôi phục!
          </p>
          <p className="text-xs text-gray-500 text-center">
            Credit đã sử dụng sẽ không được hoàn lại
          </p>
        </div>

        {/* Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-300 transition-colors"
          >
            ❌ Hủy
          </button>
          <button
            onClick={() => {
              onConfirm()
              onClose()
            }}
            className="flex-1 px-4 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 transition-colors"
          >
            ⛔ Dừng lại
          </button>
        </div>
      </div>
    </div>
  )
}