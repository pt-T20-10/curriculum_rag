import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'

export function GoogleCallbackPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { loginWithToken } = useAuth()
  const { t } = useTranslation()
  const [status, setStatus] = useState('loading') // 'loading' | 'error'
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    const handleCallback = async () => {
      const error = searchParams.get('error')
      const token = searchParams.get('token')
      const state = searchParams.get('state')

      // Handle backend-reported errors
      if (error) {
        setErrorMsg(t(`auth.google.errors.${error}`, t('auth.google.errors.default')))
        setStatus('error')
        return
      }

      if (!token) {
        setErrorMsg(t('auth.google.errors.noToken'))
        setStatus('error')
        return
      }

      // State verification (CSRF guard)
      const savedState = localStorage.getItem('google_oauth_state')
      if (savedState && state && savedState !== state) {
        setErrorMsg(t('auth.google.errors.invalid_state'))
        setStatus('error')
        return
      }
      localStorage.removeItem('google_oauth_state')

      try {
        await loginWithToken(token)
        navigate('/dashboard', { replace: true })
      } catch {
        setErrorMsg(t('auth.google.errors.profile'))
        setStatus('error')
      }
    }

    handleCallback()
  }, [loginWithToken, navigate, searchParams, t])

  if (status === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-sm text-center">
          <div className="text-4xl mb-4">❌</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">{t('auth.google.failedTitle')}</h2>
          <p className="text-sm text-gray-600 mb-6">{errorMsg}</p>
          <button
            onClick={() => navigate('/login', { replace: true })}
            className="w-full px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/90 transition-colors"
          >
            {t('auth.google.backToLogin')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4" />
        <p className="text-gray-600 text-sm">{t('auth.google.authenticating')}</p>
      </div>
    </div>
  )
}
