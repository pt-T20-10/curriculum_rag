import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { LanguageSwitcher } from '../common/LanguageSwitcher'

export function PublicPageHeader() {
  const { user } = useAuth()
  const { t } = useTranslation()

  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="content-container flex min-h-16 items-center justify-between gap-4 py-3">
        <Link to="/" className="text-xl font-bold text-primary">
          {t('app.name')}
        </Link>
        <div className="flex items-center gap-3">
          <LanguageSwitcher compact />
          <Link
            to={user ? '/dashboard' : '/login'}
            className="text-sm font-semibold text-gray-600 transition-colors hover:text-primary"
          >
            {user ? t('app.dashboard') : t('footer.links.login')}
          </Link>
        </div>
      </div>
    </header>
  )
}
