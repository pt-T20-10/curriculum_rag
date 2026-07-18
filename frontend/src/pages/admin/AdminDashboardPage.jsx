import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { adminAPI } from '../../api/admin'
import { configAPI } from '../../api/config'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'
import { DeploymentProfileNotice } from '../../components/admin/DeploymentProfileNotice'

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
// SVG bar chart
// ---------------------------------------------------------------------------
function BarChart({ data, xKey, yKey, color = '#3b82f6', height = 180, formatY = v => v, formatX = v => v }) {
  const { t } = useTranslation()

  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <p className="text-sm text-gray-400">{t('admin.dashboard.noData')}</p>
      </div>
    )
  }

  const W = 560
  const H = height
  const padL = 40, padR = 12, padT = 24, padB = 36
  const chartW = W - padL - padR
  const chartH = H - padT - padB
  const maxVal = Math.max(...data.map(d => d[yKey]), 1)
  const barW = Math.max(4, (chartW / data.length) - 3)
  const gap = (chartW / data.length) - barW
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
    y: padT + chartH - f * chartH,
    label: formatY(Math.round(f * maxVal)),
  }))
  const xLabelEvery = Math.ceil(data.length / 6)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={padL} x2={W - padR} y1={t.y} y2={t.y} stroke="#f0f0f0" strokeWidth="1" />
          <text x={padL - 4} y={t.y + 4} textAnchor="end" fontSize="10" fill="#9ca3af">{t.label}</text>
        </g>
      ))}
      {data.map((d, i) => {
        const barH = Math.max(2, (d[yKey] / maxVal) * chartH)
        const x = padL + i * (barW + gap) + gap / 2
        const y = padT + chartH - barH
        return (
          <g key={i}>
            <rect x={x} y={y} width={barW} height={barH} fill={color} rx="2" opacity="0.85">
              <title>{`${d[xKey]}: ${formatY(d[yKey])}`}</title>
            </rect>
            {barH > 18 && (
              <text x={x + barW / 2} y={y - 4} textAnchor="middle" fontSize="9" fill={color} fontWeight="600">
                {formatY(d[yKey])}
              </text>
            )}
            {i % xLabelEvery === 0 && (
              <text x={x + barW / 2} y={padT + chartH + 14} textAnchor="middle" fontSize="9" fill="#9ca3af">
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
// Horizontal rank list — top users / top content types
// ---------------------------------------------------------------------------
function HorizontalRankList({ items, labelKey, valueKey, valueLabel, barColor = 'bg-primary', formatValue = v => v }) {
  const { t } = useTranslation()

  if (!items || items.length === 0) {
    return <p className="text-sm text-gray-400 text-center py-6">{t('admin.dashboard.noData')}</p>
  }
  const maxVal = Math.max(...items.map(r => r[valueKey]), 1)
  return (
    <div className="space-y-3">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="text-xs font-bold text-gray-400 w-4">{i + 1}</span>
          <div className="flex-1">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-700 truncate max-w-[160px]" title={item[labelKey]}>
                {item[labelKey] || '—'}
              </span>
              <span className="text-gray-500 ml-3 flex-shrink-0">
                {formatValue(item[valueKey])} {valueLabel}
              </span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full">
              <div
                className={`h-2 ${barColor} rounded-full transition-all`}
                style={{ width: `${(item[valueKey] / maxVal) * 100}%` }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Date range selector — quick presets + custom date inputs
// ---------------------------------------------------------------------------
function DateRangeSelector({ dateFrom, dateTo, onChangeDateFrom, onChangeDateTo, onApplyPreset }) {
  const { t } = useTranslation()
  const presets = [
    { label: t('admin.dashboard.days7'), days: 7 },
    { label: t('admin.dashboard.days30'), days: 30 },
    { label: t('admin.dashboard.days90'), days: 90 },
  ]
  const toIso = d => d.toISOString().slice(0, 10)
  const applyPreset = days => {
    const to = new Date()
    const from = new Date()
    from.setDate(from.getDate() - days + 1)
    onApplyPreset(toIso(from), toIso(to))
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
        {presets.map(p => (
          <button
            key={p.days}
            onClick={() => applyPreset(p.days)}
            className="px-3 py-1.5 bg-white text-gray-600 hover:bg-gray-50 transition-colors border-r border-gray-200 last:border-0"
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1.5">
        <input
          type="date"
          value={dateFrom}
          onChange={e => onChangeDateFrom(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
        />
        <span className="text-gray-400 text-sm">—</span>
        <input
          type="date"
          value={dateTo}
          min={dateFrom || undefined}
          onChange={e => onChangeDateTo(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmtVND = v => {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`
  return String(v)
}
const toIso = d => d.toISOString().slice(0, 10)
const fmtPercent = v => `${Number(v || 0).toFixed(1)}%`

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function AdminDashboardPage() {
  const { t, i18n } = useTranslation()
  const [stats, setStats] = useState(null)
  const [trends, setTrends] = useState([])
  const [paymentTrends, setPaymentTrends] = useState([])
  const [contentTypes, setContentTypes] = useState([])
  const [topUsersTopup, setTopUsersTopup] = useState([])
  const [topUsersTextbooks, setTopUsersTextbooks] = useState([])
  const [setupStatus, setSetupStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [chartsLoading, setChartsLoading] = useState(false)
  const [error, setError] = useState(null)

  // Default: last 30 days
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 29); return toIso(d)
  })
  const [dateTo, setDateTo] = useState(() => toIso(new Date()))
  const locale = i18n.language === 'vi' ? 'vi-VN' : 'en-US'
  const formatShortDate = iso => new Date(`${iso}T00:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'numeric' })

  useEffect(() => {
    adminAPI.getOverview()
      .then(r => setStats(r.data))
      .catch(e => setError(e.response?.data?.detail || t('admin.dashboard.loadError')))
      .finally(() => setLoading(false))
    configAPI.getSetupStatus()
      .then(r => setSetupStatus(r.data || null))
      .catch(() => setSetupStatus(null))
  }, [t])

  const loadCharts = useCallback(async () => {
    await Promise.resolve()
    setChartsLoading(true)
    try {
      const params = { date_from: dateFrom, date_to: dateTo }
      const [trendsRes, payRes, ctRes, topupRes, tbRes] = await Promise.all([
        adminAPI.getGenerationTrends(params),
        adminAPI.getPaymentTrends(params),
        adminAPI.getTopContentTypes(5),
        adminAPI.getTopUsersTopup(5),
        adminAPI.getTopUsersTextbooks(5),
      ])
      setTrends(trendsRes.data)
      setPaymentTrends(payRes.data)
      setContentTypes(ctRes.data)
      setTopUsersTopup(topupRes.data)
      setTopUsersTextbooks(tbRes.data)
    } catch {
      // non-fatal, charts stay empty
    } finally {
      setChartsLoading(false)
    }
  }, [dateFrom, dateTo])

  useEffect(() => {
    const timer = setTimeout(() => { loadCharts() }, 0)
    return () => clearTimeout(timer)
  }, [loadCharts])

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />

      <div className="max-w-6xl mx-auto w-full px-6 py-8">
        <AdminNavigation className="mb-6" />

        {/* Header */}
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Admin Dashboard</h1>
            <p className="text-xs text-gray-400 mt-0.5">{t('admin.dashboard.subtitle')}</p>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700 text-sm">{error}</div>
        )}

        <DeploymentProfileNotice profile={setupStatus?.deployment_profile} compact={loading} />

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" />
          </div>
        ) : (
          <>
            {/* ── Stats grid ── */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              <StatCard label={t('admin.dashboard.totalUsers')} value={stats?.total_users} sub={t('admin.dashboard.activeUsers', { count: stats?.active_users || 0 })} icon="👥" />
              <StatCard label={t('admin.dashboard.totalTextbooks')} value={stats?.total_textbooks} sub={t('admin.dashboard.textbookOutcome', { completed: stats?.completed_textbooks || 0, failed: stats?.failed_textbooks || 0 })} icon="📚" />
              <StatCard label={t('admin.dashboard.textbooksThisMonth')} value={stats?.textbooks_this_month} color="text-blue-600" icon="📅" />
              <StatCard label={t('admin.dashboard.pendingPayments')} value={stats?.pending_payments} color={stats?.pending_payments > 0 ? 'text-yellow-600' : 'text-gray-900'} icon="⏳" />
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
              <StatCard label={t('admin.dashboard.totalRevenue')} value={`${(stats?.total_revenue || 0).toLocaleString(locale)} ₫`} color="text-green-600" icon="💰" />
              <StatCard label={t('admin.dashboard.revenueThisMonth')} value={`${(stats?.revenue_this_month || 0).toLocaleString(locale)} ₫`} color="text-green-600" icon="📈" />
              <StatCard label={t('admin.dashboard.creditsSold')} value={(stats?.total_credits_sold || 0).toLocaleString(locale)} icon="🪙" />
            </div>

            <div className="mb-4">
              <h2 className="text-base font-semibold text-gray-700 mb-3">{t('admin.dashboard.operationsCredits')}</h2>
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                <StatCard label={t('admin.dashboard.generatingTextbooks')} value={(stats?.generating_textbooks || 0).toLocaleString(locale)} color="text-blue-600" icon="⚙️" />
                <StatCard label={t('admin.dashboard.failedThisMonth')} value={(stats?.failed_textbooks_this_month || 0).toLocaleString(locale)} color={(stats?.failed_textbooks_this_month || 0) > 0 ? 'text-red-600' : 'text-gray-900'} icon="⚠️" />
                <StatCard label={t('admin.dashboard.successRate')} value={fmtPercent(stats?.success_rate)} color="text-emerald-600" icon="✅" />
                <StatCard label={t('admin.dashboard.creditsInCirculation')} value={(stats?.credits_in_circulation || 0).toLocaleString(locale)} icon="💳" />
                <StatCard label={t('admin.dashboard.creditsSpentTotal')} value={(stats?.credits_spent_total || 0).toLocaleString(locale)} icon="📉" />
              </div>
            </div>

            {/* ── Date range filter ── */}
            <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
              <h2 className="text-base font-semibold text-gray-700">{t('admin.dashboard.timeCharts')}</h2>
              <DateRangeSelector
                dateFrom={dateFrom}
                dateTo={dateTo}
                onChangeDateFrom={setDateFrom}
                onChangeDateTo={setDateTo}
                onApplyPreset={(from, to) => { setDateFrom(from); setDateTo(to) }}
              />
            </div>

            {chartsLoading ? (
              <div className="flex items-center justify-center h-48">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
              </div>
            ) : (
              <>
                {/* ── Time series charts ── */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                    <p className="text-sm font-semibold text-gray-700 mb-3">{t('admin.dashboard.textbooksByDay')}</p>
                    <BarChart data={trends} xKey="date" yKey="count" color="#3b82f6" height={180} formatX={formatShortDate} />
                  </div>
                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                    <p className="text-sm font-semibold text-gray-700 mb-3">{t('admin.dashboard.transactionRevenue')}</p>
                    <BarChart data={paymentTrends} xKey="date" yKey="revenue" color="#10b981" height={180} formatY={fmtVND} formatX={formatShortDate} />
                  </div>
                </div>

                {/* ── Ranking section ── */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                    <p className="text-sm font-semibold text-gray-700 mb-4">{t('admin.dashboard.topContentTypes')}</p>
                    <HorizontalRankList
                      items={contentTypes.map(c => ({
                        ...c,
                        label: t(`textbook.contentType.${c.content_type}`, { defaultValue: c.content_type }),
                      }))}
                      labelKey="label"
                      valueKey="count"
                      valueLabel={t('admin.dashboard.textbookUnit')}
                      barColor="bg-blue-500"
                    />
                  </div>

                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                    <p className="text-sm font-semibold text-gray-700 mb-4">{t('admin.dashboard.topTopup')}</p>
                    <HorizontalRankList
                      items={topUsersTopup.map(u => ({
                        ...u,
                        label: u.user_name || u.user_email || `User #${u.user_id}`,
                      }))}
                      labelKey="label"
                      valueKey="total_amount"
                      valueLabel="₫"
                      barColor="bg-green-500"
                      formatValue={fmtVND}
                    />
                  </div>

                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                    <p className="text-sm font-semibold text-gray-700 mb-4">{t('admin.dashboard.topTextbookCreators')}</p>
                    <HorizontalRankList
                      items={topUsersTextbooks.map(u => ({
                        ...u,
                        label: u.user_name || u.user_email || `User #${u.user_id}`,
                      }))}
                      labelKey="label"
                      valueKey="textbook_count"
                      valueLabel={t('admin.dashboard.textbookUnit')}
                      barColor="bg-purple-500"
                    />
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
