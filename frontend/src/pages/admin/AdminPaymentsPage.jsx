import { useEffect, useState } from 'react'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'

const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  confirmed: 'bg-green-100 text-green-700 border-green-200',
  rejected: 'bg-red-100 text-red-700 border-red-200',
}
const STATUS_LABEL = { pending: 'Chờ xác nhận', confirmed: 'Đã xác nhận', rejected: 'Từ chối' }

function RejectModal({ onConfirm, onCancel }) {
  const [reason, setReason] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
        <h3 className="text-base font-semibold text-gray-800 mb-3">Từ chối giao dịch</h3>
        <textarea
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 h-24 resize-none mb-4"
          placeholder="Lý do từ chối (tùy chọn)..."
          value={reason}
          onChange={e => setReason(e.target.value)}
        />
        <div className="flex gap-3">
          <button
            onClick={() => onConfirm(reason)}
            className="flex-1 py-2 bg-red-500 text-white rounded-lg text-sm font-medium hover:bg-red-600 transition-colors"
          >
            Xác nhận từ chối
          </button>
          <button
            onClick={onCancel}
            className="flex-1 py-2 border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            Hủy
          </button>
        </div>
      </div>
    </div>
  )
}

export function AdminPaymentsPage() {
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

  const fetchTransactions = async () => {
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
  }

  useEffect(() => { fetchTransactions() }, [page, statusFilter])

  const handleConfirm = async (txnId) => {
    if (!window.confirm('Xác nhận giao dịch này và cộng credits cho người dùng?')) return
    setActionLoading(txnId)
    try {
      const r = await adminAPI.confirmTransaction(txnId)
      flash(`Đã xác nhận! Số dư mới: ${r.data.new_balance} credits`)
      fetchTransactions()
    } catch (e) {
      flash(e.response?.data?.detail || 'Lỗi khi xác nhận', true)
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
      flash('Đã từ chối giao dịch')
      fetchTransactions()
    } catch (e) {
      flash(e.response?.data?.detail || 'Lỗi khi từ chối', true)
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
            <h1 className="text-2xl font-bold text-gray-900">Xác nhận thanh toán</h1>
            <p className="text-sm text-gray-500 mt-1">Duyệt giao dịch nạp tiền của người dùng</p>
          </div>
        </div>

    <div className="space-y-5">
      {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{error}</div>}
      {success && <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">{success}</div>}

      {/* Filter */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-medium text-gray-600">Lọc:</span>
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
            {s === '' ? 'Tất cả' : STATUS_LABEL[s]}
          </button>
        ))}
        <span className="ml-auto text-sm text-gray-400">{total} giao dịch</span>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" />
          </div>
        ) : transactions.length === 0 ? (
          <div className="text-center py-10 text-gray-400 text-sm">Không có giao dịch nào</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  {['Ngày', 'Người dùng', 'Gói', 'Số tiền', 'Nội dung CK', 'Trạng thái', 'Thao tác'].map(h => (
                    <th key={h} className="text-left py-3 px-4 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {transactions.map((t) => (
                  <tr key={t.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-3 px-4 text-gray-600 whitespace-nowrap">
                      {new Date(t.created_at).toLocaleDateString('vi-VN')}
                    </td>
                    <td className="py-3 px-4">
                      <div className="font-medium text-gray-800">{t.user_name || '—'}</div>
                      <div className="text-xs text-gray-400">{t.user_email}</div>
                    </td>
                    <td className="py-3 px-4 text-gray-800">{t.plan_name}</td>
                    <td className="py-3 px-4 text-gray-800 font-medium whitespace-nowrap">
                      {t.amount_vnd.toLocaleString('vi-VN')}₫
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-600 whitespace-nowrap">
                      {t.transfer_content}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium border ${STATUS_STYLE[t.status] || ''}`}>
                        {STATUS_LABEL[t.status] || t.status}
                      </span>
                      {t.reject_reason && (
                        <p className="text-xs text-red-500 mt-1 max-w-[140px] truncate" title={t.reject_reason}>
                          {t.reject_reason}
                        </p>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      {t.status === 'pending' ? (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleConfirm(t.id)}
                            disabled={actionLoading === t.id}
                            className="px-3 py-1.5 text-xs bg-green-500 text-white rounded-lg hover:bg-green-600 disabled:opacity-60 transition-colors"
                          >
                            {actionLoading === t.id ? '...' : 'Xác nhận'}
                          </button>
                          <button
                            onClick={() => setRejectTarget(t.id)}
                            disabled={actionLoading === t.id}
                            className="px-3 py-1.5 text-xs border border-red-200 text-red-500 rounded-lg hover:bg-red-50 disabled:opacity-60 transition-colors"
                          >
                            Từ chối
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400">
                          {t.confirmed_at ? new Date(t.confirmed_at).toLocaleDateString('vi-VN') : '—'}
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
            <span className="text-xs text-gray-400">Trang {page} / {totalPages}</span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
              >
                Trước
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
              >
                Sau
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
