import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { byokAPI } from '../../api/byok'
import { useAuth } from '../../context/AuthContext'
import { Button } from '../common/Button'
import { LanguageSwitcher } from '../common/LanguageSwitcher'

export function Navbar() {
  const { user, logout } = useAuth()
  const { t } = useTranslation()
  const [generationMode, setGenerationMode] = useState('user_provided_api_keys')
  const showCreditControls = generationMode === 'system_credit_billing'

  useEffect(() => {
    let cancelled = false
    const loadMode = async () => {
      if (!user) return
      try {
        const response = await byokAPI.status()
        if (!cancelled) {
          setGenerationMode(response.data?.generation_mode || 'user_provided_api_keys')
        }
      } catch {
        if (!cancelled) setGenerationMode('user_provided_api_keys')
      }
    }
    loadMode()
    return () => {
      cancelled = true
    }
  }, [user])

  return (
    <nav className="h-full bg-white shadow-sm border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <Link to="/dashboard" className="flex items-center gap-2.5">
            <img
              src="/favicon.svg"
              alt=""
              aria-hidden="true"
              className="h-8 w-8 shrink-0 rounded-lg"
            />
            <h1 className="text-2xl font-bold text-primary">
              {t('app.name')}
            </h1>
          </Link>

          {/* Right side */}
          <div className="flex items-center gap-4">
            {/* Admin link */}
            {user?.role === 'admin' && (
              <Link
                to="/admin"
                className="hidden sm:block text-sm font-medium text-blue-600 hover:text-blue-800 transition-colors"
              >
                {t('app.admin')}
              </Link>
            )}

            <LanguageSwitcher compact className="hidden sm:inline-flex" />

            {/* User info - clickable → dashboard */}
            <Link to="/dashboard" className="hidden sm:block text-sm text-gray-600 hover:text-primary transition-colors">
              {user?.email}
            </Link>

            {/* Profile / settings */}
            <Link
              to="/profile"
              className="hidden sm:block text-sm font-medium text-gray-600 hover:text-primary transition-colors"
              title={t('nav.settingsTitle')}
            >
              {t('nav.settings')}
            </Link>

            {/* Top-up link */}
            {showCreditControls && (
              <Link
                to="/profile"
                className="hidden sm:block text-sm font-medium text-primary hover:text-blue-500 transition-colors"
                title={t('nav.topupTitle')}
              >
                {t('nav.topup')}
              </Link>
            )}

            {/* Credits badge */}
            {showCreditControls && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-primary/10 rounded-full">
              <svg 
                className="w-5 h-5 text-primary" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
              >
                <path 
                  strokeLinecap="round" 
                  strokeLinejoin="round" 
                  strokeWidth={2} 
                  d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" 
                />
              </svg>
              <span className="font-semibold text-primary">
                {user?.credits || 0}
              </span>
            </div>
            )}

            {/* Logout button */}
            <Button
              variant="secondary"
              onClick={logout}
              className="text-sm"
            >
              {t('nav.logout')}
            </Button>
          </div>
        </div>
      </div>
    </nav>
  )
}
