import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { Input } from '../components/common/Input'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { GoogleLoginButton } from '../components/common/GoogleLoginButton'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { errorMessage, errorMessages, i18nError, mapLoginError } from '../utils/formErrors'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const { t } = useTranslation()
  const successMessage = location.state?.successKey
    ? t(location.state.successKey)
    : location.state?.successMessage || ''

  const [formData, setFormData] = useState({
    identifier: '',
    password: '',
  })
  const [rememberMe, setRememberMe] = useState(false)
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [formRenderKey, setFormRenderKey] = useState(0)
  const visibleErrors = errorMessages(errors, t)
  const visibleFieldErrors = errorMessages(fieldErrors, t)
  const visibleApiError = errorMessage(apiError, t)

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }))
    if (fieldErrors[name]) setFieldErrors(prev => ({ ...prev, [name]: '' }))
    setApiError('')
  }

  const validate = () => {
    const newErrors = {}

    if (!formData.identifier) {
      newErrors.identifier = i18nError('auth.login.identifierRequired')
    }

    if (!formData.password) {
      newErrors.password = i18nError('auth.validation.passwordRequired')
    } else if (formData.password.length < 6) {
      newErrors.password = i18nError('auth.login.passwordShort')
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!validate()) return

    setLoading(true)
    setApiError('')
    setFieldErrors({})

    // Capture values before async — browser may clear DOM fields on HTTP error,
    // and React skips DOM update when state hasn't changed (same reference optimization).
    const savedIdentifier = formData.identifier
    const savedPassword = formData.password

    try {
      await login(savedIdentifier, savedPassword, rememberMe)
      navigate('/dashboard', { replace: true })
    } catch (error) {
      const detail = error.response?.data?.detail || ''
      const status = error.response?.status

      if (status === 404) {
        // Keep both fields so the user can correct only the identifier.
        setFormData({ identifier: savedIdentifier, password: savedPassword })
        setFormRenderKey(k => k + 1)
        setFieldErrors({ identifier: mapLoginError(detail, status) })
      } else if (status === 401 || detail.includes('M\u1eadt kh\u1ea9u')) {
        // Wrong password: keep username/email, clear only password.
        setFormData({ identifier: savedIdentifier, password: '' })
        setFormRenderKey(k => k + 1)
        setFieldErrors({ password: mapLoginError(detail, status) })
      } else if (status === 400) {
        setFormData({ identifier: savedIdentifier, password: savedPassword })
        setFormRenderKey(k => k + 1)
        setApiError(mapLoginError(detail, status))
      } else if (status === 403) {
        setFormData({ identifier: savedIdentifier, password: savedPassword })
        setFormRenderKey(k => k + 1)
        setApiError(mapLoginError(detail, status))
      } else {
        setFormData({ identifier: savedIdentifier, password: savedPassword })
        setFormRenderKey(k => k + 1)
        setApiError(mapLoginError(detail, status))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <div className="flex justify-end mb-4">
          <LanguageSwitcher compact />
        </div>
        <h1 className="text-3xl font-bold text-center text-primary mb-2">
          {t('auth.login.welcome')}
        </h1>
        <p className="text-center text-gray-600 mb-6">
          {t('auth.login.title')}
        </p>

        <form key={formRenderKey} onSubmit={handleSubmit}>
          <Input
            label={t('auth.login.identifier')}
            type="text"
            name="identifier"
            value={formData.identifier}
            onChange={handleChange}
            error={visibleErrors.identifier || visibleFieldErrors.identifier}
            placeholder={t('auth.login.identifierPlaceholder')}
            autoFocus
          />

          <PasswordInput
            label={t('auth.fields.password')}
            name="password"
            value={formData.password}
            onChange={handleChange}
            error={visibleErrors.password || visibleFieldErrors.password}
            placeholder={t('auth.placeholders.password')}
          />

          {/* Remember Me + Forgot password row */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <input
                id="rememberMe"
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
              />
              <label
                htmlFor="rememberMe"
                className="text-sm text-gray-700 cursor-pointer select-none"
              >
                {t('auth.login.remember')}
                <span className="text-xs text-gray-400 ml-1">({t('auth.login.rememberDays')})</span>
              </label>
            </div>
            <Link to="/forgot-password" className="text-sm text-primary hover:underline">
              {t('auth.login.forgotPassword')}
            </Link>
          </div>

          {successMessage && (
            <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
              <p className="text-sm text-green-700">{successMessage}</p>
            </div>
          )}

          {visibleApiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-600">{visibleApiError}</p>
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            loading={loading}
          >
            {t('auth.login.button')}
          </Button>
        </form>

        <div className="mt-6">
          <div className="relative flex items-center gap-3 mb-4">
            <div className="flex-1 border-t border-gray-200" />
            <span className="text-xs text-gray-400">{t('auth.login.or')}</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
          <GoogleLoginButton />
        </div>

        <p className="mt-4 text-center text-sm text-gray-600">
          {t('auth.login.registerPrompt')}{' '}
          <Link to="/register" className="text-primary hover:underline font-medium">
            {t('auth.login.registerLink')}
          </Link>
        </p>
      </div>
    </div>
  )
}
