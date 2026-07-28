import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { en } from './locales/en'
import { vi } from './locales/vi'

export const LANGUAGE_STORAGE_KEY = 'app_language'
export const DEFAULT_LANGUAGE = 'en'
export const SUPPORTED_LANGUAGES = ['vi', 'en']

function getInitialLanguage() {
  if (typeof window === 'undefined') return DEFAULT_LANGUAGE

  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (SUPPORTED_LANGUAGES.includes(stored)) return stored

  return DEFAULT_LANGUAGE
}

function syncDocumentLanguage(language) {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = language
  }
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      vi: { translation: vi },
      en: { translation: en },
    },
    lng: getInitialLanguage(),
    fallbackLng: DEFAULT_LANGUAGE,
    interpolation: {
      escapeValue: false,
    },
    returnNull: false,
  })

syncDocumentLanguage(i18n.language)

i18n.on('languageChanged', (language) => {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  }
  syncDocumentLanguage(language)
})

export default i18n
