import { useTranslation } from 'react-i18next'
import { SUPPORTED_LANGUAGES } from '../../i18n'

export function LanguageSwitcher({ compact = false, className = '' }) {
  const { i18n, t } = useTranslation()

  return (
    <div
      className={`inline-flex items-center rounded-lg border border-gray-200 bg-white/90 p-1 shadow-sm ${className}`}
      aria-label={t('language.label')}
    >
      {SUPPORTED_LANGUAGES.map((language) => {
        const active = i18n.resolvedLanguage === language || i18n.language === language
        return (
          <button
            key={language}
            type="button"
            onClick={() => i18n.changeLanguage(language)}
            className={`rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors ${
              active
                ? 'bg-primary text-white shadow-sm'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            }`}
            title={t(`language.${language}`)}
            aria-pressed={active}
          >
            {compact ? t(`language.short${language === 'vi' ? 'Vi' : 'En'}`) : t(`language.short${language === 'vi' ? 'Vi' : 'En'}`)}
          </button>
        )
      })}
    </div>
  )
}
