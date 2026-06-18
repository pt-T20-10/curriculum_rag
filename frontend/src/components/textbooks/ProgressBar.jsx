import { useTranslation } from 'react-i18next'
import { translateProgressText } from '../../utils/progressText'

export function ProgressBar({ value, statusText }) {
  const { t } = useTranslation()
  const displayStatus = translateProgressText(statusText, t)

  return (
    <div className="mb-6">
      <div className="w-full bg-gray-200 rounded-full h-2.5">
        <div 
          className="bg-gradient-to-r from-blue-400 to-primary h-2.5 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(value * 100, 100)}%` }}
        />
      </div>
      {displayStatus && (
        <p className="text-sm text-gray-600 mt-2" 
           dangerouslySetInnerHTML={{ __html: displayStatus }} 
        />
      )}
    </div>
  )
}
