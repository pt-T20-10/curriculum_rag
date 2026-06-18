import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Trans, useTranslation } from 'react-i18next'
import { authAPI } from '../api/auth'
import { Input } from '../components/common/Input'
import { Button } from '../components/common/Button'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { errorMessage, i18nError } from '../utils/formErrors'

export function ForgotPasswordPage() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [apiError, setApiError] = useState('')
  const visibleEmailError = errorMessage(emailError, t)
  const visibleApiError = errorMessage(apiError, t)

  const validate = () => {
    if (!email) {
      setEmailError(i18nError('auth.validation.emailRequired'))
      return false
    }
    if (!/\S+@\S+\.\S+/.test(email)) {
      setEmailError(i18nError('auth.validation.emailInvalid'))
      return false
    }
    setEmailError('')
    return true
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!validate()) return

    setLoading(true)
    setApiError('')
    try {
      await authAPI.forgotPassword(email)
      setSent(true)
    } catch {
      setApiError(i18nError('auth.forgot.genericLater'))
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md text-center">
          <div className="flex justify-end mb-4">
            <LanguageSwitcher compact />
          </div>
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-800 mb-2">{t('auth.forgot.checkTitle')}</h2>
          <p className="text-gray-600 mb-2">
            <Trans i18nKey="auth.forgot.checkText" values={{ email }} components={{ strong: <strong /> }} />
          </p>
          <p className="text-sm text-gray-400 mb-6">{t('auth.forgot.expiry')}</p>
          <Link
            to={`/reset-password?email=${encodeURIComponent(email)}`}
            className="inline-block w-full py-2.5 px-4 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 transition-colors text-center"
          >
            {t('auth.forgot.enterCode')}
          </Link>
          <p className="mt-4 text-sm text-gray-500">
            <button
              onClick={() => { setSent(false); setEmail('') }}
              className="text-primary hover:underline"
            >
              {t('auth.forgot.tryAnother')}
            </button>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <div className="flex justify-end mb-4">
          <LanguageSwitcher compact />
        </div>
        <h1 className="text-2xl font-bold text-center text-gray-800 mb-2">{t('auth.forgot.title')}</h1>
        <p className="text-center text-gray-500 mb-6 text-sm">
          {t('auth.forgot.subtitle')}
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label={t('auth.fields.email')}
            type="email"
            name="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setEmailError('') }}
            error={visibleEmailError}
            placeholder="email@cuaban.com"
            autoFocus
          />

          {visibleApiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-600">{visibleApiError}</p>
            </div>
          )}

          <Button type="submit" className="w-full" loading={loading}>
            {t('auth.forgot.button')}
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          {t('auth.forgot.remembered')}{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            {t('auth.forgot.backToLogin')}
          </Link>
        </p>
      </div>
    </div>
  )
}
