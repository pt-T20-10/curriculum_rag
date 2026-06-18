import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { Input } from '../components/common/Input'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { GoogleLoginButton } from '../components/common/GoogleLoginButton'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { errorMessage, errorMessages, i18nError, mapRegisterError } from '../utils/formErrors'

const USERNAME_REGEX = /^[a-zA-Z0-9_.-]+$/

export function RegisterPage() {
  const navigate = useNavigate()
  const { register } = useAuth()
  const { t } = useTranslation()

  const [formData, setFormData] = useState({
    fullName: '',
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
  })
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
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

    if (!formData.fullName.trim()) {
      newErrors.fullName = i18nError('auth.validation.fullNameRequired')
    }

    if (formData.username) {
      const u = formData.username.trim()
      if (u.length < 3) {
        newErrors.username = i18nError('auth.validation.usernameMin')
      } else if (u.length > 50) {
        newErrors.username = i18nError('auth.validation.usernameMax')
      } else if (!USERNAME_REGEX.test(u)) {
        newErrors.username = i18nError('auth.validation.usernameChars')
      }
    }

    if (!formData.email) {
      newErrors.email = i18nError('auth.validation.emailRequired')
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = i18nError('auth.validation.emailInvalid')
    }

    if (!formData.password) {
      newErrors.password = i18nError('auth.validation.passwordRequired')
    } else if (formData.password.length < 8) {
      newErrors.password = i18nError('auth.validation.passwordMin')
    }

    if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = i18nError('auth.validation.confirmMismatch')
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

    try {
      await register(
        formData.email,
        formData.password,
        formData.fullName,
        formData.username.trim() || undefined,
      )
      navigate('/dashboard')
    } catch (error) {
      const detail = error.response?.data?.detail || ''
      const status = error.response?.status

      if (status === 400 && detail.includes('T\u00ean \u0111\u0103ng nh\u1eadp')) {
        setFieldErrors({ username: mapRegisterError(detail) })
      } else if (status === 400 && (detail.includes('Email') || detail.includes('email'))) {
        setFieldErrors({ email: mapRegisterError(detail) })
      } else if (status === 422) {
        // Pydantic validation error — extract first message
        const msgs = error.response?.data?.detail
        const first = Array.isArray(msgs) ? msgs[0]?.msg : detail
        setApiError(first ? mapRegisterError(first) : i18nError('auth.validation.invalidData'))
      } else {
        setApiError(mapRegisterError(detail))
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
          {t('auth.register.title')}
        </h1>
        <p className="text-center text-gray-600 mb-6">
          {t('auth.register.subtitle')}
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label={t('auth.fields.fullName')}
            type="text"
            name="fullName"
            value={formData.fullName}
            onChange={handleChange}
            error={visibleErrors.fullName}
            placeholder={t('auth.placeholders.fullName')}
            autoFocus
          />

          <Input
            label={<>{t('auth.fields.username')} <span className="text-gray-400 font-normal">({t('auth.fields.usernameOptional')})</span></>}
            type="text"
            name="username"
            value={formData.username}
            onChange={handleChange}
            error={visibleErrors.username || visibleFieldErrors.username}
            placeholder={t('auth.placeholders.username')}
          />

          <Input
            label={t('auth.fields.email')}
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            error={visibleErrors.email || visibleFieldErrors.email}
            placeholder="email@cuaban.com"
          />

          <PasswordInput
            label={t('auth.fields.password')}
            name="password"
            value={formData.password}
            onChange={handleChange}
            error={visibleErrors.password}
            placeholder={t('auth.placeholders.password')}
          />

          <PasswordInput
            label={t('auth.fields.confirmPassword')}
            name="confirmPassword"
            value={formData.confirmPassword}
            onChange={handleChange}
            error={visibleErrors.confirmPassword}
            placeholder={t('auth.placeholders.confirmPassword')}
          />

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
            {t('auth.register.button')}
          </Button>
        </form>

        <div className="mt-6">
          <div className="relative flex items-center gap-3 mb-4">
            <div className="flex-1 border-t border-gray-200" />
            <span className="text-xs text-gray-400">{t('auth.register.quick')}</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
          <GoogleLoginButton label={t('auth.register.google')} />
        </div>

        <p className="mt-4 text-center text-sm text-gray-600">
          {t('auth.register.loginPrompt')}{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            {t('auth.register.loginLink')}
          </Link>
        </p>
      </div>
    </div>
  )
}
