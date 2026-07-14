import { useTranslation } from 'react-i18next'

export function WordFieldUpdateNoticeModal({ isOpen, onClose, onConfirm }) {
  const { t } = useTranslation()

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative bg-white rounded-lg shadow-2xl max-w-md w-full mx-4 p-6">
        <div className="flex items-center justify-center w-12 h-12 mx-auto mb-4 bg-blue-100 rounded-full">
          <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M12 3a9 9 0 100 18 9 9 0 000-18z" />
          </svg>
        </div>

        <h3 className="text-xl font-bold text-gray-900 text-center mb-3">
          {t('textbook.wordNotice.title')}
        </h3>

        <div className="space-y-3 text-sm text-gray-700">
          <p>{t('textbook.wordNotice.description')}</p>
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-blue-900">
            <p className="font-medium">{t('textbook.wordNotice.stepsTitle')}</p>
            <p className="mt-1">{t('textbook.wordNotice.steps')}</p>
          </div>
          <p className="text-xs text-gray-500">{t('textbook.wordNotice.note')}</p>
        </div>

        <div className="mt-6 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors"
          >
            {t('app.cancel')}
          </button>
          <button
            onClick={() => {
              onConfirm()
              onClose()
            }}
            className="flex-1 px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            {t('textbook.wordNotice.confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}
