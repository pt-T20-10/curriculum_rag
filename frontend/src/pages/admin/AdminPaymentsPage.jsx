import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'

const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  confirmed: 'bg-green-100 text-green-700 border-green-200',
  rejected: 'bg-red-100 text-red-700 border-red-200',
}
function RejectModal({ onConfirm, onCancel }) {
  const { t } = useTranslation()
  const [reason, setReason] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
        <h3 className="text-base font-semibold text-gray-800 mb-3">{t('admin.payments.rejectTitle')}</h3>
        <textarea
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 h-24 resize-none mb-4"
          placeholder={t('admin.payments.rejectPlaceholder')}
          value={reason}
          onChange={e => setReason(e.target.value)}
        />
        <div className="flex gap-3">
          <button
            onClick={() => onConfirm(reason)}
            className="flex-1 py-2 bg-red-500 text-white rounded-lg text-sm font-medium hover:bg-red-600 transition-colors"
          >
            {t('admin.payments.rejectConfirm')}
          </button>
          <button
            onClick={onCancel}
            className="flex-1 py-2 border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            {t('app.cancel')}
          </button>
        </div>
      </div>
    </div>
  )
}

export function AdminPaymentsPage() {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const [transactions, setTransactions] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 20
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(null) // txn id being processed
  const [rejectTarget, setRejectTarget] = useState(null) // txn id for reject modal
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const flash = (msg, isError = false) => {
    if (isError) setError(msg)
    else setSuccess(msg)
    setTimeout(() => { setError(''); setSuccess('') }, 3000)
  }

  const fetchTransactions = useCallback(async () => {
    await Promise.resolve()
    setLoading(true)
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (statusFilter) params.status = statusFilter
      const r = await adminAPI.listTransactions(params)
      setTransactions(r.data.items)
      setTotal(r.data.total)
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter])

  useEffect(() => {
    const timer = setTimeout(() => { fetchTransactions() }, 0)
    return () => clearTimeout(timer)
  }, [fetchTransactions])

  const handleConfirm = async (txnId) => {
    if (!window.confirm(t('admin.payments.confirmPrompt'))) return
    setActionLoading(txnId)
    try {
      const r = await adminAPI.confirmTransaction(txnId)
      flash(t('admin.payments.confirmed', { balance: r.data.new_balance }))
      fetchTransactions()
    } catch (e) {
      flash(e.response?.data?.detail || t('admin.payments.confirmError'), true)
    } finally {
      setActionLoading(null)
    }
  }

  const handleReject = async (reason) => {
    const txnId = rejectTarget
    setRejectTarget(null)
    setActionLoading(txnId)
    try {
      await adminAPI.rejectTransaction(txnId, reason)
      flash(t('admin.payments.rejected'))
      fetchTransactions()
    } catch (e) {
      flash(e.response?.data?.detail || t('admin.payments.rejectError'), true)
    } finally {
      setActionLoading(null)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-6xl mx-auto px-4 py-8">
        <AdminNavigation className="mb-6" />

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{t('admin.payments.title')}</h1>
            <p className="text-sm text-gray-500 mt-1">{t('admin.payments.subtitle')}</p>
          </div>
        </div>

    <div className="space-y-5">
      {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{error}</div>}
      {success && <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">{success}</div>}

      {/* Filter */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-medium text-gray-600">{t('admin.payments.filter')}</span>
        {['', 'pending', 'confirmed', 'rejected'].map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1) }}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              statusFilter === s
                ? 'bg-primary text-white'
                : 'border border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            {s === '' ? t('app.all') : t(`topup.statuses.${s}`, s)}
          </button>
        ))}
        <span className="ml-auto text-sm text-gray-400">{t('admin.payments.total', { count: total })}</span>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" />
          </div>
        ) : transactions.length === 0 ? (
          <div className="text-center py-10 text-gray-400 text-sm">{t('admin.payments.empty')}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  {[t('admin.payments.date'), t('admin.payments.user'), t('admin.payments.plan'), t('admin.payments.amount'), t('admin.payments.transferContent'), t('app.status'), t('app.actions')].map(h => (
                    <th key={h} className="text-left py-3 px-4 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {transactions.map((transaction) => (
                  <tr key={transaction.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-3 px-4 text-gray-600 whitespace-nowrap">
                      {new Date(transaction.created_at).toLocaleDateString(locale)}
                    </td>
                    <td className="py-3 px-4">
                      <div className="font-medium text-gray-800">{transaction.user_name || '—'}</div>
                      <div className="text-xs text-gray-400">{transaction.user_email}</div>
                    </td>
                    <td className="py-3 px-4 text-gray-800">{transaction.plan_name}</td>
                    <td className="py-3 px-4 text-gray-800 font-medium whitespace-nowrap">
                      {transaction.amount_vnd.toLocaleString(locale)}₫
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-600 whitespace-nowrap">
                      {transaction.transfer_content}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium border ${STATUS_STYLE[transaction.status] || ''}`}>
                        {t(`topup.statuses.${transaction.status}`, transaction.status)}
                      </span>
                      {transaction.reject_reason && (
                        <p className="text-xs text-red-500 mt-1 max-w-[140px] truncate" title={transaction.reject_reason}>
                          {transaction.reject_reason}
                        </p>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      {transaction.status === 'pending' ? (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleConfirm(transaction.id)}
                            disabled={actionLoading === transaction.id}
                            className="px-3 py-1.5 text-xs bg-green-500 text-white rounded-lg hover:bg-green-600 disabled:opacity-60 transition-colors"
                          >
                            {actionLoading === transaction.id ? '...' : t('admin.payments.confirm')}
                          </button>
                          <button
                            onClick={() => setRejectTarget(transaction.id)}
                            disabled={actionLoading === transaction.id}
                            className="px-3 py-1.5 text-xs border border-red-200 text-red-500 rounded-lg hover:bg-red-50 disabled:opacity-60 transition-colors"
                          >
                            {t('admin.payments.reject')}
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400">
                          {transaction.confirmed_at ? new Date(transaction.confirmed_at).toLocaleDateString(locale) : '—'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
            <span className="text-xs text-gray-400">{t('app.page', { page, totalPages })}</span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
              >
                {t('app.previous')}
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
              >
                {t('app.next')}
              </button>
            </div>
          </div>
        )}
      </div>

      {rejectTarget && (
        <RejectModal onConfirm={handleReject} onCancel={() => setRejectTarget(null)} />
      )}
    </div>
      </div>
    </div>
  )
}
