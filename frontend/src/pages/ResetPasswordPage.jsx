import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { authAPI } from '../api/auth'
import { Input } from '../components/common/Input'
import { Button } from '../components/common/Button'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { errorMessage, errorMessages, i18nError, mapPasswordError } from '../utils/formErrors'

export function ResetPasswordPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const prefillEmail = searchParams.get('email') || ''

  const [formData, setFormData] = useState({
    email: prefillEmail,
    code: '',
    new_password: '',
    confirm_password: '',
  })
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState('')
  const visibleErrors = errorMessages(errors, t)
  const visibleApiError = errorMessage(apiError, t)

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }))
    setApiError('')
  }

  const validate = () => {
    const newErrors = {}

    if (!formData.email) newErrors.email = i18nError('auth.validation.emailRequired')
    else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = i18nError('auth.validation.emailInvalid')

    if (!formData.code) newErrors.code = i18nError('auth.validation.codeRequired')
    else if (!/^\d{6}$/.test(formData.code)) newErrors.code = i18nError('auth.validation.codeInvalid')

    if (!formData.new_password) newErrors.new_password = i18nError('auth.validation.newPasswordRequired')
    else if (formData.new_password.length < 8) newErrors.new_password = i18nError('auth.validation.passwordMin')

    if (!formData.confirm_password) newErrors.confirm_password = i18nError('auth.validation.confirmRequired')
    else if (formData.new_password !== formData.confirm_password)
      newErrors.confirm_password = i18nError('auth.validation.confirmMismatch')

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!validate()) return

    setLoading(true)
    setApiError('')
    try {
      await authAPI.resetPassword(formData.email, formData.code, formData.new_password)
      navigate('/login', {
        state: { successKey: 'auth.reset.success' },
        replace: true,
      })
    } catch (err) {
      setApiError(mapPasswordError(err.response?.data?.detail, 'auth.validation.generic'))
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
        <h1 className="text-2xl font-bold text-center text-gray-800 mb-2">{t('auth.reset.title')}</h1>
        <p className="text-center text-gray-500 mb-6 text-sm">
          {t('auth.reset.subtitle')}
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label={t('auth.fields.email')}
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            error={visibleErrors.email}
            placeholder="email@cuaban.com"
          />

          <Input
            label={t('auth.fields.code')}
            type="text"
            name="code"
            value={formData.code}
            onChange={handleChange}
            error={visibleErrors.code}
            placeholder="123456"
            maxLength={6}
            inputMode="numeric"
            autoComplete="one-time-code"
          />

          <Input
            label={t('auth.fields.newPassword')}
            type="password"
            name="new_password"
            value={formData.new_password}
            onChange={handleChange}
            error={visibleErrors.new_password}
            placeholder={t('auth.placeholders.password')}
          />

          <Input
            label={t('auth.fields.confirmNewPassword')}
            type="password"
            name="confirm_password"
            value={formData.confirm_password}
            onChange={handleChange}
            error={visibleErrors.confirm_password}
            placeholder={t('auth.placeholders.confirmNewPassword')}
          />

          {visibleApiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-600">{visibleApiError}</p>
            </div>
          )}

          <Button type="submit" className="w-full" loading={loading}>
            {t('auth.reset.button')}
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          {t('auth.reset.resendPrompt')}{' '}
          <Link to="/forgot-password" className="text-primary hover:underline font-medium">
            {t('auth.reset.resend')}
          </Link>
          {' · '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            {t('auth.forgot.backToLogin')}
          </Link>
        </p>
      </div>
    </div>
  )
}
