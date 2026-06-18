import { useTranslation } from 'react-i18next'

const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  confirmed: 'bg-green-100 text-green-700 border-green-200',
  rejected: 'bg-red-100 text-red-700 border-red-200',
}

export function TransactionHistory({ transactions, loading }) {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" />
      </div>
    )
  }

  if (!transactions.length) {
    return (
      <div className="text-center py-10 text-gray-400">
        <svg className="w-10 h-10 mx-auto mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        <p className="text-sm">{t('topup.noTransactions')}</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left py-2 px-3 font-medium text-gray-500">{t('topup.date')}</th>
            <th className="text-left py-2 px-3 font-medium text-gray-500">{t('topup.plan')}</th>
            <th className="text-right py-2 px-3 font-medium text-gray-500">{t('topup.transferAmount')}</th>
            <th className="text-right py-2 px-3 font-medium text-gray-500">Credits</th>
            <th className="text-center py-2 px-3 font-medium text-gray-500">{t('topup.status')}</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((transaction) => (
            <tr key={transaction.id} className="border-b border-gray-50 hover:bg-gray-50">
              <td className="py-3 px-3 text-gray-600 whitespace-nowrap">
                {new Date(transaction.created_at).toLocaleDateString(locale)}
              </td>
              <td className="py-3 px-3 text-gray-800 font-medium">{transaction.plan_name}</td>
              <td className="py-3 px-3 text-right text-gray-800">
                {transaction.amount_vnd.toLocaleString(locale)}₫
              </td>
              <td className="py-3 px-3 text-right text-primary font-semibold">+{transaction.credits}</td>
              <td className="py-3 px-3 text-center">
                <span
                  className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium border ${STATUS_STYLE[transaction.status] || 'bg-gray-100 text-gray-600'}`}
                >
                  {t(`topup.statuses.${transaction.status}`, transaction.status)}
                </span>
                {transaction.reject_reason && (
                  <p className="text-xs text-red-500 mt-1">{transaction.reject_reason}</p>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
