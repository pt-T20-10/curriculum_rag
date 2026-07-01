import { useTranslation } from 'react-i18next'
import { RunningIndicator } from '../common/RunningIndicator'
import { translateProgressText } from '../../utils/progressText'

export function ProgressBar({ statusText }) {
  const { t } = useTranslation()
  const displayStatus = translateProgressText(statusText, t)

  return (
    <div className="mb-6">
      <RunningIndicator
        label={displayStatus}
        description={t('textbook.workflow.runningHint')}
        size="lg"
        allowHtml
      />
    </div>
  )
}
