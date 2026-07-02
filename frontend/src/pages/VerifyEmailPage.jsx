import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { authAPI } from '../api/auth'
import { useAuth } from '../context/AuthContext'
import { Button } from '../components/common/Button'
import { Input } from '../components/common/Input'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { errorMessage, i18nError, mapPasswordError } from '../utils/formErrors'

export function VerifyEmailPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { user, loginWithToken } = useAuth()
  const { t } = useTranslation()

  const initialEmail = location.state?.email || searchParams.get('email') || user?.email || ''
  const [email, setEmail] = useState(initialEmail)
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [resending, setResending] = useState(false)
  const [apiError, setApiError] = useState('')
  const [infoMessage, setInfoMessage] = useState(location.state?.messageKey ? i18nError(location.state.messageKey) : '')
  const [resultDialog, setResultDialog] = useState(null)

  const visibleApiError = errorMessage(apiError, t)
  const visibleInfoMessage = errorMessage(infoMessage, t)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setApiError('')
    setInfoMessage('')
    if (!email || !code || code.length !== 6) {
      setApiError(i18nError('auth.verify.invalidCode'))
      return
    }

    setLoading(true)
    try {
      const response = await authAPI.verifyEmail(email, code)
      if (response.data?.access_token) {
        await loginWithToken(response.data.access_token)
        setResultDialog({
          type: 'success',
          title: i18nError('auth.verify.successTitle'),
          message: i18nError('auth.verify.successDashboard'),
        })
        window.setTimeout(() => {
          navigate('/dashboard', { replace: true })
        }, 1400)
      } else {
        setResultDialog({
          type: 'success',
          title: i18nError('auth.verify.successTitle'),
          message: i18nError('auth.verify.successLogin'),
          next: 'login',
        })
      }
    } catch (error) {
      const detail = error.response?.data?.detail || ''
      const mappedError = mapPasswordError(detail, 'auth.verify.invalidCode')
      setApiError(mappedError)
      setResultDialog({
        type: 'error',
        title: i18nError('auth.verify.failedTitle'),
        message: mappedError,
      })
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    setApiError('')
    setInfoMessage('')
    if (!email) {
      setApiError(i18nError('auth.validation.emailRequired'))
      return
    }

    setResending(true)
    try {
      await authAPI.resendVerification(email)
      setInfoMessage(i18nError('auth.verify.resent'))
    } catch {
      setApiError(i18nError('auth.verify.resendError'))
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      {resultDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
            <div
              className={`mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full text-2xl ${
                resultDialog.type === 'success'
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-red-100 text-red-700'
              }`}
            >
              {resultDialog.type === 'success' ? '✓' : '×'}
            </div>
            <h2 className="text-center text-xl font-bold text-gray-900">
              {errorMessage(resultDialog.title, t)}
            </h2>
            <p className="mt-2 text-center text-sm text-gray-600">
              {errorMessage(resultDialog.message, t)}
            </p>
            <div className="mt-6 flex gap-3">
              {resultDialog.type === 'success' && resultDialog.next === 'login' ? (
                <Button
                  type="button"
                  className="w-full"
                  onClick={() => navigate('/login', { replace: true, state: { successKey: 'auth.verify.successLogin' } })}
                >
                  {t('auth.forgot.backToLogin')}
                </Button>
              ) : resultDialog.type === 'success' ? (
                <Button type="button" className="w-full" disabled>
                  {t('auth.verify.redirecting')}
                </Button>
              ) : (
                <>
                  <Button
                    type="button"
                    variant="secondary"
                    className="w-full"
                    onClick={() => setResultDialog(null)}
                  >
                    {t('auth.verify.tryAgain')}
                  </Button>
                  <Button
                    type="button"
                    className="w-full"
                    onClick={() => navigate('/login')}
                  >
                    {t('auth.forgot.backToLogin')}
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <div className="flex justify-end mb-4">
          <LanguageSwitcher compact />
        </div>
        <h1 className="text-3xl font-bold text-center text-primary mb-2">
          {t('auth.verify.title')}
        </h1>
        <p className="text-center text-gray-600 mb-6">
          {t('auth.verify.subtitle')}
        </p>

        {visibleInfoMessage && (
          <div className="mb-4 p-3 bg-emerald-50 border border-emerald-200 rounded-lg">
            <p className="text-sm text-emerald-700">{visibleInfoMessage}</p>
          </div>
        )}

        {visibleApiError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600">{visibleApiError}</p>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <Input
            label={t('auth.fields.email')}
            type="email"
            name="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email@cuaban.com"
            autoFocus={!email}
          />

          <Input
            label={t('auth.verify.code')}
            type="text"
            name="code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            autoFocus={Boolean(email)}
          />

          <Button type="submit" className="w-full" loading={loading}>
            {t('auth.verify.button')}
          </Button>
        </form>

        <div className="mt-5 text-center text-sm text-gray-600">
          {t('auth.verify.resendPrompt')}{' '}
          <button
            type="button"
            onClick={handleResend}
            disabled={resending}
            className="text-primary hover:underline font-medium disabled:opacity-60"
          >
            {resending ? t('app.processing') : t('auth.verify.resend')}
          </button>
        </div>

        <p className="mt-4 text-center text-sm text-gray-600">
          <Link to="/login" className="text-primary hover:underline font-medium">
            {t('auth.forgot.backToLogin')}
          </Link>
        </p>
      </div>
    </div>
  )
}
