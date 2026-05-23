import { useState, useEffect, useCallback } from 'react'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'

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

const STATUS_LABEL = {
  completed: 'Hoàn thành',
  failed: 'Thất bại',
  generating: 'Đang tạo',
  pending: 'Chờ',
}

const CONTENT_TYPE_LABEL = {
  technical: 'Kỹ thuật',
  academic: 'Học thuật',
  general: 'Tổng hợp',
  professional: 'Chuyên nghiệp',
  simplified: 'Đơn giản hóa',
}

export function AdminTextbooksPage() {
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
      setError(err.response?.data?.detail || 'Không thể tải dữ liệu')
    } finally {
      setLoading(false)
    }
  }, [page, search, statusFilter, dateFrom, dateTo])

  useEffect(() => { load() }, [load])

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
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Quản lý giáo trình</h1>
            <p className="text-sm text-gray-500 mt-0.5">Tổng: {total} giáo trình</p>
          </div>
        </div>

        {/* Filters */}
        <form onSubmit={handleSearch} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 mb-6">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-gray-500 mb-1">Tìm kiếm</label>
              <input
                type="text"
                placeholder="Tiêu đề hoặc chủ đề..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Trạng thái</label>
              <select
                value={statusFilter}
                onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              >
                <option value="">Tất cả</option>
                <option value="completed">Hoàn thành</option>
                <option value="generating">Đang tạo</option>
                <option value="pending">Chờ</option>
                <option value="failed">Thất bại</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Từ ngày</label>
              <input
                type="date"
                value={dateFrom}
                onChange={e => { setDateFrom(e.target.value); setPage(1) }}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Đến ngày</label>
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
                Tìm kiếm
              </button>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={handleClearFilters}
                  className="px-3 py-2 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50"
                >
                  Xóa bộ lọc
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
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Tiêu đề</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Chủ đề</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Loại nội dung</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Người tạo</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Trạng thái</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Cấu hình</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Credits</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Ngày tạo</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
                  </td>
                </tr>
              ) : textbooks.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-gray-400">
                    Không có giáo trình
                  </td>
                </tr>
              ) : (
                textbooks.map(t => (
                  <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-800 max-w-[180px] truncate" title={t.title}>
                        {t.title}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 max-w-[140px] truncate" title={t.topic}>
                      {t.topic}
                    </td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-medium">
                        {CONTENT_TYPE_LABEL[t.content_type] || t.content_type || '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-gray-800">{t.owner_name || '—'}</div>
                      <div className="text-gray-400 text-xs">{t.owner_email}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge color={STATUS_COLOR[t.status] || 'gray'}>
                        {STATUS_LABEL[t.status] || t.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">
                      {t.num_chapters} chương · {t.content_level}
                    </td>
                    <td className="px-4 py-3 text-gray-700">{t.credits_used}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(t.created_at).toLocaleDateString('vi-VN')}
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
              Trang {page} / {totalPages} ({total} giáo trình)
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
              >
                ← Trước
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
              >
                Sau →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
