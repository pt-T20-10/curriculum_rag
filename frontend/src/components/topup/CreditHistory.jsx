import { useTranslation } from 'react-i18next'

const TYPE_STYLE = {
  admin_adjustment: 'bg-blue-50 text-blue-700 border-blue-200',
  textbook_generation: 'bg-gray-50 text-gray-600 border-gray-200',
  topup: 'bg-green-50 text-green-700 border-green-200',
  other: 'bg-gray-50 text-gray-600 border-gray-200',
}

export function CreditAdjustmentNotice({ item }) {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'

  if (!item || item.type !== 'admin_adjustment') return null

  const isAdded = Number(item.delta) > 0

  return (
    <div className={`rounded-xl border p-4 ${isAdded ? 'border-green-200 bg-green-50' : 'border-amber-200 bg-amber-50'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className={`text-sm font-semibold ${isAdded ? 'text-green-800' : 'text-amber-800'}`}>
            {isAdded
              ? t('topup.adminCreditAdded', { count: Math.abs(item.delta) })
              : t('topup.adminCreditSubtracted', { count: Math.abs(item.delta) })}
          </p>
          <p className="mt-1 text-sm text-gray-700">{item.reason}</p>
        </div>
        <span className="text-xs text-gray-500">
          {new Date(item.created_at).toLocaleString(locale)}
        </span>
      </div>
    </div>
  )
}

export function CreditHistory({ history, loading }) {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" />
      </div>
    )
  }

  if (!history.length) {
    return (
      <div className="text-center py-10 text-gray-400">
        <svg className="w-10 h-10 mx-auto mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 14l2 2 4-4m5-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-sm">{t('topup.noCreditHistory')}</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left py-2 px-3 font-medium text-gray-500">{t('topup.date')}</th>
            <th className="text-right py-2 px-3 font-medium text-gray-500">{t('topup.creditChange')}</th>
            <th className="text-left py-2 px-3 font-medium text-gray-500">{t('topup.reason')}</th>
            <th className="text-right py-2 px-3 font-medium text-gray-500">{t('topup.balanceAfter')}</th>
          </tr>
        </thead>
        <tbody>
          {history.map((item) => {
            const delta = Number(item.delta || 0)
            return (
              <tr key={item.id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="py-3 px-3 text-gray-600 whitespace-nowrap">
                  {new Date(item.created_at).toLocaleDateString(locale)}
                </td>
                <td className={`py-3 px-3 text-right font-semibold ${delta >= 0 ? 'text-green-700' : 'text-red-600'}`}>
                  {delta > 0 ? `+${delta}` : delta}
                </td>
                <td className="py-3 px-3 text-gray-800">
                  <span className={`mr-2 inline-block rounded-full border px-2 py-0.5 text-xs ${TYPE_STYLE[item.type] || TYPE_STYLE.other}`}>
                    {t(`topup.creditTypes.${item.type}`, item.type)}
                  </span>
                  {item.reason}
                </td>
                <td className="py-3 px-3 text-right text-gray-700">
                  {Number(item.balance_after || 0).toLocaleString(locale)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
