import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { configAPI } from '../../api/config'

const ADMIN_NAV_ITEMS = [
  { to: '/admin', labelKey: 'app.dashboard', end: true },
  { to: '/admin/users', labelKey: 'nav.adminUsers' },
  { to: '/admin/textbooks', labelKey: 'nav.adminTextbooks' },
  { to: '/admin/landing', labelKey: 'nav.adminLanding' },
  { to: '/admin/plans', labelKey: 'nav.adminPlans' },
  { to: '/admin/payments', labelKey: 'nav.adminPayments' },
  { to: '/admin/config', labelKey: 'nav.adminConfig' },
]

export function AdminNavigation({ className = '' }) {
  const { t } = useTranslation()
  const [setupStatus, setSetupStatus] = useState(null)

  useEffect(() => {
    let cancelled = false
    const loadSetupStatus = async () => {
      try {
        const response = await configAPI.getSetupStatus()
        if (!cancelled) setSetupStatus(response.data || null)
      } catch {
        if (!cancelled) setSetupStatus(null)
      }
    }
    loadSetupStatus()
    return () => {
      cancelled = true
    }
  }, [])

  const missing = setupStatus?.missing_required || []

  return (
    <div className={`w-full ${className}`}>
      <div className="mx-auto flex w-full max-w-7xl justify-center px-4 sm:px-6 lg:px-8">
        <div className="max-w-full">
          <nav
            aria-label="Admin navigation"
            className="inline-flex w-fit min-w-max gap-1 overflow-x-auto rounded-lg border border-gray-200 bg-white p-1 shadow-sm"
          >
            {ADMIN_NAV_ITEMS.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-primary text-white shadow-sm'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`
                }
              >
                {t(item.labelKey)}
              </NavLink>
            ))}
          </nav>
          {missing.length > 0 && (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Còn thiếu {missing.length} cấu hình bắt buộc.{' '}
              <NavLink to={`/admin/config?setup=1&focus=${encodeURIComponent(missing[0].key)}`} className="font-semibold underline">
                Đi tới cấu hình
              </NavLink>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
