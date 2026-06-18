import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

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

  return (
    <div className={`w-full ${className}`}>
      <div className="mx-auto flex w-full max-w-7xl justify-center px-4 sm:px-6 lg:px-8">
        <div className="max-w-full overflow-x-auto">
          <nav
            aria-label="Admin navigation"
            className="inline-flex w-fit min-w-max gap-1 rounded-lg border border-gray-200 bg-white p-1 shadow-sm"
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
        </div>
      </div>
    </div>
  )
}
