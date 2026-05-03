import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { textbooksAPI } from '../api/textbooks'
import { Navbar } from '../components/layout/Navbar'
import { TextbookFilter } from '../components/textbooks/TextbookFilter'
import { TextbookCard } from '../components/textbooks/TextbookCard'
import { Pagination } from '../components/common/Pagination'
import { EmptyState } from '../components/common/EmptyState'
import { Spinner } from '../components/common/Spinner'
import { Button } from '../components/common/Button'

export function DashboardPage() {
  const navigate = useNavigate()

  const [textbooks, setTextbooks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [filters, setFilters] = useState({
    content_type: '',
    status: '',
  })

  const [pagination, setPagination] = useState({
    page: 1,
    size: 9,
    total: 0,
    pages: 0,
  })

  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      setError(null)

      try {
        const params = {
          page: pagination.page,
          size: pagination.size,
          ...(filters.content_type && { content_type: filters.content_type }),
          ...(filters.status && { status: filters.status }),
        }

        const response = await textbooksAPI.list(params)
        const data = response.data

        if (!cancelled) {
          setTextbooks(data.items)
          setPagination(prev => ({
            ...prev,
            total: data.total,
            pages: data.pages,
          }))
        }
      } catch (err) {
        console.error('Failed to fetch textbooks:', err)
        if (!cancelled) {
          setError('Không thể tải danh sách giáo trình. Vui lòng thử lại.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [filters, pagination.page, pagination.size, refreshKey])

  const handleFilterChange = (key, value) => {
    if (key === 'clear') {
      setFilters({ content_type: '', status: '' })
    } else {
      setFilters(prev => ({ ...prev, [key]: value }))
    }
    setPagination(prev => ({ ...prev, page: 1 }))
  }

  const handlePageChange = (page) => {
    setPagination(prev => ({ ...prev, page }))
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="content-container py-8">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              Giáo trình của tôi
            </h1>
            <p className="text-gray-600 mt-1">
              Quản lý và tải xuống các giáo trình được tạo bởi AI
            </p>
          </div>
          <Button onClick={() => navigate('/create')}>
            + Tạo giáo trình
          </Button>
        </div>

        {/* Filters */}
        <TextbookFilter
          filters={filters}
          onFilterChange={handleFilterChange}
        />

        {/* Loading State */}
        {loading && (
          <div className="py-12">
            <Spinner size="lg" />
            <p className="text-center text-gray-600 mt-4">
              Đang tải giáo trình...
            </p>
          </div>
        )}

        {/* Error State */}
        {error && !loading && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-600">{error}</p>
            <Button
              onClick={() => setRefreshKey(k => k + 1)}
              variant="secondary"
              className="mt-2"
            >
              Thử lại
            </Button>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && textbooks.length === 0 && (
          <EmptyState
            icon={
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            }
            title={filters.content_type || filters.status ? 'Không tìm thấy giáo trình' : 'Chưa có giáo trình nào'}
            description={
              filters.content_type || filters.status
                ? 'Thử thay đổi bộ lọc để xem thêm kết quả.'
                : 'Bắt đầu bằng cách tạo giáo trình AI đầu tiên của bạn.'
            }
            actionLabel={filters.content_type || filters.status ? 'Xóa bộ lọc' : 'Tạo giáo trình'}
            onAction={() => {
              if (filters.content_type || filters.status) {
                handleFilterChange('clear')
              } else {
                navigate('/create')
              }
            }}
          />
        )}

        {/* Textbook Grid */}
        {!loading && !error && textbooks.length > 0 && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {textbooks.map(textbook => (
                <TextbookCard key={textbook.id} textbook={textbook} />
              ))}
            </div>

            <Pagination
              currentPage={pagination.page}
              totalPages={pagination.pages}
              onPageChange={handlePageChange}
            />
          </>
        )}
      </main>
    </div>
  )
}
