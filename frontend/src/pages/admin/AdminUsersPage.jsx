import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { FiCreditCard, FiTrash2 } from 'react-icons/fi'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'

function Badge({ children, color = 'gray' }) {
  const colors = {
    green: 'bg-green-100 text-green-700',
    red: 'bg-red-100 text-red-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    gray: 'bg-gray-100 text-gray-600',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[color]}`}>
      {children}
    </span>
  )
}

function LockModal({ user, onClose, onConfirm }) {
  const { t } = useTranslation()
  const [reason, setReason] = useState('')
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-2">{t('admin.users.lockTitle')}</h3>
        <p className="text-sm text-gray-600 mb-4">
          {t('admin.users.lockConfirm', { email: user.email })}
        </p>
        <textarea
          className="w-full border border-gray-300 rounded-lg p-3 text-sm resize-none h-20 focus:outline-none focus:ring-2 focus:ring-primary/40"
          placeholder={t('admin.users.lockReason')}
          value={reason}
          onChange={e => setReason(e.target.value)}
        />
        <div className="flex gap-3 mt-4 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">
            {t('app.cancel')}
          </button>
          <button
            onClick={() => onConfirm(reason)}
            className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700"
          >
            {t('admin.users.lockAccount')}
          </button>
        </div>
      </div>
    </div>
  )
}

function DeleteModal({ user, loading, onClose, onConfirm }) {
  const { t } = useTranslation()
  const [confirmation, setConfirmation] = useState('')
  const confirmed = confirmation.trim() === user.email

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700">
            <FiTrash2 className="h-4 w-4" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{t('admin.users.deleteTitle')}</h3>
            <p className="mt-1 text-sm leading-6 text-gray-600">
              {t('admin.users.deleteConfirm', { email: user.email })}
            </p>
          </div>
        </div>

        <label className="mt-5 block text-sm font-medium text-gray-800">
          {t('admin.users.deleteTypeEmail')}
          <input
            type="email"
            value={confirmation}
            onChange={event => setConfirmation(event.target.value)}
            autoComplete="off"
            className="mt-1.5 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            placeholder={user.email}
          />
        </label>

        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {t('app.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!confirmed || loading}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? '...' : t('admin.users.deleteAccount')}
          </button>
        </div>
      </div>
    </div>
  )
}

function CreditAdjustModal({ user, loading, onClose, onConfirm }) {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const [delta, setDelta] = useState('')
  const [reason, setReason] = useState('')
  const parsedDelta = Number.parseInt(delta, 10)
  const safeDelta = Number.isFinite(parsedDelta) ? parsedDelta : 0
  const currentBalance = Number(user.credits || 0)
  const nextBalance = currentBalance + safeDelta
  const reasonLength = reason.trim().length
  const invalidDelta = !Number.isFinite(parsedDelta) || safeDelta === 0 || Math.abs(safeDelta) > 100000
  const invalidReason = reasonLength < 5 || reasonLength > 200
  const invalidBalance = nextBalance < 0
  const canSubmit = !invalidDelta && !invalidReason && !invalidBalance && !loading

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
            <FiCreditCard className="h-4 w-4" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{t('admin.users.adjustCreditsTitle')}</h3>
            <p className="mt-1 text-sm text-gray-600">
              {user.full_name || '—'} · {user.email}
            </p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 rounded-lg bg-gray-50 p-3 text-sm">
          <div>
            <p className="text-xs text-gray-500">{t('admin.users.currentCredits')}</p>
            <p className="font-semibold text-gray-900">{currentBalance.toLocaleString(locale)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">{t('admin.users.newCredits')}</p>
            <p className={`font-semibold ${invalidBalance ? 'text-red-600' : 'text-gray-900'}`}>
              {nextBalance.toLocaleString(locale)}
            </p>
          </div>
        </div>

        <label className="mt-4 block text-sm font-medium text-gray-800">
          {t('admin.users.creditDelta')}
          <input
            type="number"
            value={delta}
            onChange={event => setDelta(event.target.value)}
            className="mt-1.5 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            placeholder={t('admin.users.creditDeltaPlaceholder')}
          />
        </label>
        <p className="mt-1 text-xs text-gray-500">{t('admin.users.creditDeltaHint')}</p>

        <label className="mt-4 block text-sm font-medium text-gray-800">
          {t('admin.users.adjustReason')}
          <textarea
            value={reason}
            onChange={event => setReason(event.target.value)}
            className="mt-1.5 h-24 w-full resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            placeholder={t('admin.users.adjustReasonPlaceholder')}
          />
        </label>
        <div className="mt-1 flex justify-between text-xs">
          <span className={(invalidDelta || invalidBalance || invalidReason) ? 'text-red-600' : 'text-gray-500'}>
            {invalidBalance
              ? t('admin.users.negativeBalanceError')
              : invalidDelta
                ? t('admin.users.deltaError')
                : invalidReason
                  ? t('admin.users.reasonError')
                  : t('admin.users.adjustPreview', { delta: safeDelta, balance: nextBalance })}
          </span>
          <span className="text-gray-400">{reasonLength}/200</span>
        </div>

        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {t('app.cancel')}
          </button>
          <button
            type="button"
            onClick={() => onConfirm({ delta: safeDelta, reason: reason.trim() })}
            disabled={!canSubmit}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? '...' : t('admin.users.saveCreditAdjustment')}
          </button>
        </div>
      </div>
    </div>
  )
}

export function AdminUsersPage() {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const [users, setUsers] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [lockedFilter, setLockedFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lockTarget, setLockTarget] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [creditTarget, setCreditTarget] = useState(null)
  const [actionLoading, setActionLoading] = useState(null)
  const [success, setSuccess] = useState(null)

  const PAGE_SIZE = 20

  const load = useCallback(async () => {
    await Promise.resolve()
    setLoading(true)
    setError(null)
    try {
      const params = { page, page_size: PAGE_SIZE, role: 'user' }
      if (search) params.search = search
      if (lockedFilter !== '') params.is_locked = lockedFilter === 'true'
      const res = await adminAPI.listUsers(params)
      setUsers(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      setError(err.response?.data?.detail || t('admin.users.loadError'))
    } finally {
      setLoading(false)
    }
  }, [page, search, lockedFilter, t])

  useEffect(() => {
    const timer = setTimeout(() => { load() }, 0)
    return () => clearTimeout(timer)
  }, [load])

  const handleSearch = (e) => {
    e.preventDefault()
    setPage(1)
    load()
  }

  const handleLock = async (reason) => {
    if (!lockTarget) return
    setActionLoading(lockTarget.id)
    setSuccess(null)
    try {
      await adminAPI.lockUser(lockTarget.id, reason)
      setLockTarget(null)
      load()
    } catch (err) {
      setError(err.response?.data?.detail || t('admin.users.lockFailed'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleUnlock = async (userId) => {
    setActionLoading(userId)
    setSuccess(null)
    try {
      await adminAPI.unlockUser(userId)
      load()
    } catch (err) {
      setError(err.response?.data?.detail || t('admin.users.unlockFailed'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setActionLoading(deleteTarget.id)
    setError(null)
    setSuccess(null)
    try {
      await adminAPI.deleteUser(deleteTarget.id)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || t('admin.users.deleteFailed'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleAdjustCredits = async ({ delta, reason }) => {
    if (!creditTarget) return
    setActionLoading(creditTarget.id)
    setError(null)
    setSuccess(null)
    try {
      const res = await adminAPI.adjustUserCredits(creditTarget.id, { delta, reason })
      setCreditTarget(null)
      setSuccess(t('admin.users.adjustSuccess', { balance: res.data.new_balance }))
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || t('admin.users.adjustFailed'))
    } finally {
      setActionLoading(null)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />

      {lockTarget && (
        <LockModal
          user={lockTarget}
          onClose={() => setLockTarget(null)}
          onConfirm={handleLock}
        />
      )}
      {deleteTarget && (
        <DeleteModal
          user={deleteTarget}
          loading={actionLoading === deleteTarget.id}
          onClose={() => setDeleteTarget(null)}
          onConfirm={handleDelete}
        />
      )}
      {creditTarget && (
        <CreditAdjustModal
          user={creditTarget}
          loading={actionLoading === creditTarget.id}
          onClose={() => setCreditTarget(null)}
          onConfirm={handleAdjustCredits}
        />
      )}

      <div className="max-w-7xl mx-auto w-full px-6 py-8">
        <AdminNavigation className="mb-6" />

        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">{t('admin.users.title')}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{t('admin.users.total', { count: total })}</p>
          </div>
        </div>

        {/* Filters */}
        <form onSubmit={handleSearch} className="flex flex-wrap gap-3 mb-6">
          <input
            type="text"
            placeholder={t('admin.users.searchPlaceholder')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-72 focus:outline-none focus:ring-2 focus:ring-primary/40"
          />
          <select
            value={lockedFilter}
            onChange={e => { setLockedFilter(e.target.value); setPage(1) }}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
          >
            <option value="">{t('admin.users.allStatuses')}</option>
            <option value="false">{t('admin.users.normal')}</option>
            <option value="true">{t('admin.users.locked')}</option>
          </select>
          <button
            type="submit"
            className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/90"
          >
            {t('app.search')}
          </button>
        </form>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4 text-red-700 text-sm">
            {error}
          </div>
        )}
        {success && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4 text-green-700 text-sm">
            {success}
          </div>
        )}

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.users.user')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('app.status')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Credits</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('nav.adminTextbooks')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.users.registeredVia')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('app.createdAt')}</th>
                <th className="text-right px-4 py-3 text-gray-600 font-medium">{t('app.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">{t('admin.users.noUsers')}</td>
                </tr>
              ) : (
                users.map(u => (
                  <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-800">{u.full_name || '—'}</div>
                      <div className="text-gray-400 text-xs">{u.email}</div>
                    </td>
                    <td className="px-4 py-3">
                      {u.is_locked ? (
                        <div>
                          <Badge color="red">{t('admin.users.locked')}</Badge>
                          {u.locked_at && (
                            <div className="text-xs text-gray-400 mt-0.5">
                              {new Date(u.locked_at).toLocaleDateString(locale)}
                            </div>
                          )}
                        </div>
                      ) : u.is_active ? (
                        <Badge color="green">{t('app.active')}</Badge>
                      ) : (
                        <Badge color="yellow">{t('app.inactive')}</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-700">{u.credits.toLocaleString(locale)}</td>
                    <td className="px-4 py-3 text-gray-700">{u.textbook_count}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs capitalize">{u.auth_provider}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(u.created_at).toLocaleDateString(locale)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setCreditTarget(u)}
                          disabled={actionLoading === u.id}
                          className="inline-flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                          title={t('admin.users.adjustCredits')}
                        >
                          <FiCreditCard className="h-3.5 w-3.5" aria-hidden="true" />
                          {t('admin.users.adjustCredits')}
                        </button>
                        {u.is_locked ? (
                          <button
                            onClick={() => handleUnlock(u.id)}
                            disabled={actionLoading === u.id}
                            className="px-3 py-1 text-xs bg-green-50 text-green-700 border border-green-200 rounded hover:bg-green-100 disabled:opacity-50"
                          >
                            {actionLoading === u.id ? '...' : t('admin.users.unlock')}
                          </button>
                        ) : (
                          <button
                            onClick={() => setLockTarget(u)}
                            disabled={actionLoading === u.id}
                            className="px-3 py-1 text-xs bg-red-50 text-red-700 border border-red-200 rounded hover:bg-red-100 disabled:opacity-50"
                          >
                            {actionLoading === u.id ? '...' : t('admin.users.lock')}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => setDeleteTarget(u)}
                          disabled={actionLoading === u.id}
                          className="inline-flex items-center gap-1 rounded border border-red-200 bg-white px-2.5 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
                          title={t('admin.users.delete')}
                        >
                          <FiTrash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          {t('admin.users.delete')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <p className="text-sm text-gray-500">
              {t('admin.users.pageInfo', { page, totalPages, total })}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
              >
                ← {t('app.previous')}
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
              >
                {t('app.next')} →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
