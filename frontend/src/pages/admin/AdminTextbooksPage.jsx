import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'

function Badge({ children, color = 'gray' }) {
  const colors = {
    green: 'bg-green-100 text-green-700',
    red: 'bg-red-100 text-red-700',
    blue: 'bg-blue-100 text-blue-700',
    gray: 'bg-gray-100 text-gray-600',
    yellow: 'bg-yellow-100 text-yellow-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[color]}`}>
      {children}
    </span>
  )
}

const STATUS_COLOR = {
  completed: 'green',
  failed: 'red',
  generating: 'blue',
  pending: 'yellow',
}

export function AdminTextbooksPage() {
  const { i18n, t } = useTranslation()
  const navigate = useNavigate()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const [textbooks, setTextbooks] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const PAGE_SIZE = 20

  const load = useCallback(async () => {
    await Promise.resolve()
    setLoading(true)
    setError(null)
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (search) params.search = search
      if (statusFilter) params.status = statusFilter
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const res = await adminAPI.listTextbooks(params)
      setTextbooks(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      setError(err.response?.data?.detail || t('admin.textbooks.loadError'))
    } finally {
      setLoading(false)
    }
  }, [page, search, statusFilter, dateFrom, dateTo, t])

  useEffect(() => {
    const timer = setTimeout(() => { load() }, 0)
    return () => clearTimeout(timer)
  }, [load])

  const handleSearch = (e) => {
    e.preventDefault()
    setPage(1)
    load()
  }

  const handleClearFilters = () => {
    setSearch('')
    setStatusFilter('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
  }

  const hasActiveFilters = search || statusFilter || dateFrom || dateTo
  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />
      <div className="max-w-7xl mx-auto w-full px-6 py-8">
        <AdminNavigation className="mb-6" />

        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">{t('admin.textbooks.title')}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{t('admin.textbooks.total', { count: total })}</p>
          </div>
        </div>

        {/* Filters */}
        <form onSubmit={handleSearch} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 mb-6">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-gray-500 mb-1">{t('admin.textbooks.searchLabel')}</label>
              <input
                type="text"
                placeholder={t('admin.textbooks.searchPlaceholder')}
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('admin.textbooks.status')}</label>
              <select
                value={statusFilter}
                onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              >
                <option value="">{t('app.all')}</option>
                <option value="completed">{t('textbook.status.completed')}</option>
                <option value="generating">{t('textbook.status.generating')}</option>
                <option value="pending">{t('textbook.status.pending')}</option>
                <option value="failed">{t('textbook.status.failed')}</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('app.fromDate')}</label>
              <input
                type="date"
                value={dateFrom}
                onChange={e => { setDateFrom(e.target.value); setPage(1) }}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('app.toDate')}</label>
              <input
                type="date"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={e => { setDateTo(e.target.value); setPage(1) }}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/90"
              >
                {t('app.search')}
              </button>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={handleClearFilters}
                  className="px-3 py-2 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50"
                >
                  {t('textbook.filter.clear')}
                </button>
              )}
            </div>
          </div>
        </form>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4 text-red-700 text-sm">
            {error}
          </div>
        )}

        <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.textbooks.titleColumn')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.textbooks.topic')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.textbooks.contentType')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.textbooks.creator')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('app.status')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('admin.textbooks.config')}</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Credits</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">{t('app.createdAt')}</th>
                <th className="text-right px-4 py-3 text-gray-600 font-medium">{t('admin.textbooks.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="text-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
                  </td>
                </tr>
              ) : textbooks.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-gray-400">
                    {t('admin.textbooks.noTextbooks')}
                  </td>
                </tr>
              ) : (
                textbooks.map(textbook => (
                  <tr key={textbook.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-800 max-w-[180px] truncate" title={textbook.title}>
                        {textbook.title}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 max-w-[140px] truncate" title={textbook.topic}>
                      {textbook.topic}
                    </td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-medium">
                        {textbook.content_type ? t(`textbook.contentType.${textbook.content_type}`, textbook.content_type) : '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-gray-800">{textbook.owner_name || '—'}</div>
                      <div className="text-gray-400 text-xs">{textbook.owner_email}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge color={STATUS_COLOR[textbook.status] || 'gray'}>
                        {t(`textbook.status.${textbook.status}`, textbook.status)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">
                      {t('admin.textbooks.chaptersAndLevel', { chapters: textbook.num_chapters, level: textbook.content_level })}
                    </td>
                    <td className="px-4 py-3 text-gray-700">{textbook.credits_used}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(textbook.created_at).toLocaleDateString(locale)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => navigate(`/admin/textbooks/${textbook.id}`)}
                        className="px-3 py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-lg text-xs font-medium hover:bg-blue-100"
                      >
                        {t('admin.textbooks.view')}
                      </button>
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
              {t('admin.textbooks.pageInfo', { page, totalPages, total })}
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
