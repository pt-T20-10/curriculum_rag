import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------
function StatCard({ label, value, sub, color = 'text-gray-900', icon }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        {icon && <span className="text-xl">{icon}</span>}
      </div>
      <p className={`text-3xl font-bold ${color}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SVG bar chart — works for any numeric series
// ---------------------------------------------------------------------------
function BarChart({ data, xKey, yKey, color = '#3b82f6', height = 180, formatY = v => v, formatX = v => v }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <p className="text-sm text-gray-400">Không có dữ liệu</p>
      </div>
    )
  }

  const W = 560
  const H = height
  const padL = 40
  const padR = 12
  const padT = 24
  const padB = 36
  const chartW = W - padL - padR
  const chartH = H - padT - padB

  const maxVal = Math.max(...data.map(d => d[yKey]), 1)
  const barW = Math.max(4, (chartW / data.length) - 3)
  const gap = (chartW / data.length) - barW

  // Y-axis ticks (4 lines)
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
    y: padT + chartH - f * chartH,
    label: formatY(Math.round(f * maxVal)),
  }))

  // Show at most ~6 x-labels evenly spaced
  const xLabelEvery = Math.ceil(data.length / 6)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      {/* Grid lines */}
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={padL} x2={W - padR} y1={t.y} y2={t.y} stroke="#f0f0f0" strokeWidth="1" />
          <text x={padL - 4} y={t.y + 4} textAnchor="end" fontSize="10" fill="#9ca3af">
            {t.label}
          </text>
        </g>
      ))}

      {/* Bars */}
      {data.map((d, i) => {
        const barH = Math.max(2, (d[yKey] / maxVal) * chartH)
        const x = padL + i * (barW + gap) + gap / 2
        const y = padT + chartH - barH

        return (
          <g key={i}>
            <rect x={x} y={y} width={barW} height={barH} fill={color} rx="2" opacity="0.85">
              <title>{`${d[xKey]}: ${formatY(d[yKey])}`}</title>
            </rect>
            {/* Value label on top (only if bar is tall enough) */}
            {barH > 18 && (
              <text x={x + barW / 2} y={y - 4} textAnchor="middle" fontSize="9" fill={color} fontWeight="600">
                {formatY(d[yKey])}
              </text>
            )}
            {/* X label */}
            {i % xLabelEvery === 0 && (
              <text
                x={x + barW / 2}
                y={padT + chartH + 14}
                textAnchor="middle"
                fontSize="9"
                fill="#9ca3af"
              >
                {formatX(d[xKey])}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Period selector
// ---------------------------------------------------------------------------
function PeriodSelector({ value, onChange }) {
  const options = [
    { label: '7 ngày', value: 7 },
    { label: '30 ngày', value: 30 },
    { label: '90 ngày', value: 90 },
  ]
  return (
    <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
      {options.map(o => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 transition-colors ${
            value === o.value
              ? 'bg-primary text-white font-medium'
              : 'bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
const fmtVND = v => {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`
  return String(v)
}

const fmtDate = iso => {
  // "2026-04-28" → "28/4"
  const [, m, d] = iso.split('-')
  return `${parseInt(d)}/${parseInt(m)}`
}

export function AdminDashboardPage() {
  const [stats, setStats] = useState(null)
  const [trends, setTrends] = useState([])
  const [paymentTrends, setPaymentTrends] = useState([])
  const [topics, setTopics] = useState([])
  const [period, setPeriod] = useState(30)
  const [loading, setLoading] = useState(true)
  const [chartsLoading, setChartsLoading] = useState(false)
  const [error, setError] = useState(null)

  // Load overview once
  useEffect(() => {
    adminAPI.getOverview()
      .then(r => setStats(r.data))
      .catch(e => setError(e.response?.data?.detail || 'Không thể tải dữ liệu'))
      .finally(() => setLoading(false))
  }, [])

  // Load charts whenever period changes
  const loadCharts = useCallback(async () => {
    setChartsLoading(true)
    try {
      const [trendsRes, payRes, topicsRes] = await Promise.all([
        adminAPI.getGenerationTrends(period),
        adminAPI.getPaymentTrends(period),
        adminAPI.getTopTopics(5),
      ])
      setTrends(trendsRes.data)
      setPaymentTrends(payRes.data)
      setTopics(topicsRes.data)
    } catch {
      // non-fatal, charts just stay empty
    } finally {
      setChartsLoading(false)
    }
  }, [period])

  useEffect(() => { loadCharts() }, [loadCharts])

  const maxTopicCount = Math.max(...topics.map(t => t.count), 1)

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />

      <div className="max-w-6xl mx-auto w-full px-6 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Admin Dashboard</h1>
            <p className="text-xs text-gray-400 mt-0.5">Tổng quan hệ thống</p>
          </div>
          <div className="flex gap-2">
            <Link to="/admin/users" className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/90 transition-colors">
              Người dùng
            </Link>
            <Link to="/admin/textbooks" className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50 transition-colors">
              Giáo trình
            </Link>
            <Link to="/admin/landing" className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50 transition-colors">
              Landing Page
            </Link>
            <Link to="/admin/plans" className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50 transition-colors">
              Gói & Ngân hàng
            </Link>
            <Link to="/admin/payments" className="px-4 py-2 border border-amber-300 text-amber-700 bg-amber-50 rounded-lg text-sm hover:bg-amber-100 transition-colors font-medium">
              Xác nhận TT
            </Link>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700 text-sm">{error}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" />
          </div>
        ) : (
          <>
            {/* ── Stats grid ── */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              <StatCard
                label="Tổng người dùng"
                value={stats?.total_users}
                sub={`${stats?.active_users} đang hoạt động`}
                icon="👥"
              />
              <StatCard
                label="Tổng giáo trình"
                value={stats?.total_textbooks}
                sub={`${stats?.completed_textbooks} hoàn thành · ${stats?.failed_textbooks} thất bại`}
                icon="📚"
              />
              <StatCard
                label="Giáo trình tháng này"
                value={stats?.textbooks_this_month}
                color="text-blue-600"
                icon="📅"
              />
              <StatCard
                label="Thanh toán chờ xử lý"
                value={stats?.pending_payments}
                color={stats?.pending_payments > 0 ? 'text-yellow-600' : 'text-gray-900'}
                icon="⏳"
              />
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
              <StatCard
                label="Tổng doanh thu"
                value={`${(stats?.total_revenue || 0).toLocaleString('vi-VN')} ₫`}
                color="text-green-600"
                icon="💰"
              />
              <StatCard
                label="Doanh thu tháng này"
                value={`${(stats?.revenue_this_month || 0).toLocaleString('vi-VN')} ₫`}
                color="text-green-600"
                icon="📈"
              />
              <StatCard
                label="Tổng credits đã bán"
                value={(stats?.total_credits_sold || 0).toLocaleString('vi-VN')}
                icon="🪙"
              />
            </div>

            {/* ── Period filter ── */}
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold text-gray-700">Biểu đồ theo thời gian</h2>
              <PeriodSelector value={period} onChange={setPeriod} />
            </div>

            {chartsLoading ? (
              <div className="flex items-center justify-center h-48">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">

                {/* Textbook trend */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                  <p className="text-sm font-semibold text-gray-700 mb-3">
                    Giáo trình tạo theo ngày
                  </p>
                  <BarChart
                    data={trends}
                    xKey="date"
                    yKey="count"
                    color="#3b82f6"
                    height={180}
                    formatX={fmtDate}
                  />
                </div>

                {/* Payment revenue trend */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                  <p className="text-sm font-semibold text-gray-700 mb-3">
                    Doanh thu thanh toán (₫)
                  </p>
                  <BarChart
                    data={paymentTrends}
                    xKey="date"
                    yKey="revenue"
                    color="#10b981"
                    height={180}
                    formatY={fmtVND}
                    formatX={fmtDate}
                  />
                </div>
              </div>
            )}

            {/* Top topics */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <p className="text-sm font-semibold text-gray-700 mb-4">Top 5 chủ đề</p>
              {topics.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-6">Không có dữ liệu</p>
              ) : (
                <div className="space-y-3">
                  {topics.map((t, i) => (
                    <div key={t.topic} className="flex items-center gap-3">
                      <span className="text-xs font-bold text-gray-400 w-4">{i + 1}</span>
                      <div className="flex-1">
                        <div className="flex justify-between text-sm mb-1">
                          <span className="text-gray-700 truncate max-w-xs">{t.topic}</span>
                          <span className="text-gray-500 ml-3 flex-shrink-0">{t.count} giáo trình</span>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full">
                          <div
                            className="h-2 bg-primary rounded-full transition-all"
                            style={{ width: `${(t.count / maxTopicCount) * 100}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
