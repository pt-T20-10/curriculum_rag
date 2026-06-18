import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { authAPI } from '../api/auth'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { Navbar } from '../components/layout/Navbar'
import { TopUpTab } from '../components/topup/TopUpTab'
import { AdvancedSettings } from '../components/settings/AdvancedSettings'
import { errorMessage, errorMessages, i18nError, mapPasswordError } from '../utils/formErrors'

const EMPTY_FORM = { currentPassword: '', newPassword: '', confirmPassword: '' }

function validateField(name, value, allData) {
  switch (name) {
    case 'currentPassword':
      if (!value.trim()) return i18nError('auth.validation.currentPasswordRequired')
      return ''
    case 'newPassword':
      if (!value) return i18nError('auth.validation.newPasswordRequired')
      if (value.length < 8) return i18nError('auth.validation.passwordMin')
      if (!/[A-Z]/.test(value)) return i18nError('auth.validation.passwordUpper')
      if (!/[0-9]/.test(value)) return i18nError('auth.validation.passwordNumber')
      if (allData?.currentPassword && value === allData.currentPassword)
        return i18nError('auth.validation.passwordDifferent')
      return ''
    case 'confirmPassword':
      if (value !== allData?.newPassword) return i18nError('auth.validation.confirmMismatch')
      return ''
    default:
      return ''
  }
}

function ChangePasswordTab() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState({})
  const [loading, setLoading] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')
  const [apiError, setApiError] = useState('')
  const visibleErrors = errorMessages(errors, t)
  const visibleApiError = errorMessage(apiError, t)

  const handleChange = (e) => {
    const { name, value } = e.target
    const newData = { ...formData, [name]: value }
    setFormData(newData)
    setApiError('')
    if (touched[name]) {
      setErrors(prev => ({ ...prev, [name]: validateField(name, value, newData) }))
    }
    if (name === 'newPassword' && touched.confirmPassword) {
      setErrors(prev => ({
        ...prev,
        confirmPassword: validateField('confirmPassword', newData.confirmPassword, newData),
      }))
    }
  }

  const handleBlur = (e) => {
    const { name, value } = e.target
    setTouched(prev => ({ ...prev, [name]: true }))
    setErrors(prev => ({ ...prev, [name]: validateField(name, value, formData) }))
  }

  const isFormValid =
    !validateField('currentPassword', formData.currentPassword, formData) &&
    !validateField('newPassword', formData.newPassword, formData) &&
    !validateField('confirmPassword', formData.confirmPassword, formData)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setTouched({ currentPassword: true, newPassword: true, confirmPassword: true })
    const newErrors = {}
    for (const name of ['currentPassword', 'newPassword', 'confirmPassword']) {
      const err = validateField(name, formData[name], formData)
      if (err) newErrors[name] = err
    }
    setErrors(newErrors)
    if (Object.keys(newErrors).length > 0) return

    setLoading(true)
    setApiError('')
    try {
      await authAPI.changePassword(formData.currentPassword, formData.newPassword)
      setFormData(EMPTY_FORM)
      setErrors({})
      setTouched({})
      setSuccessMessage('profile.password.success')
      setTimeout(() => setSuccessMessage(''), 2000)
    } catch (error) {
      const detail = error.response?.data?.detail
      const mappedError = mapPasswordError(detail, 'auth.validation.updatePasswordFailed')
      if (mappedError.key === 'auth.validation.currentPasswordWrong') {
        setErrors(prev => ({ ...prev, currentPassword: mappedError }))
      } else {
        setApiError(mappedError)
      }
    } finally {
      setLoading(false)
    }
  }

  if (user?.auth_provider === 'google') {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 max-w-md">
        <h2 className="text-lg font-semibold text-gray-800 mb-5">{t('profile.password.title')}</h2>
        <p className="text-sm text-gray-500">
          {t('profile.password.googleAccount')}
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 max-w-md">
      <h2 className="text-lg font-semibold text-gray-800 mb-5">{t('profile.password.title')}</h2>
      <form onSubmit={handleSubmit} noValidate>
        <PasswordInput
          label={t('auth.fields.currentPassword')}
          name="currentPassword"
          value={formData.currentPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          error={visibleErrors.currentPassword}
          placeholder={t('auth.placeholders.currentPassword')}
          autoComplete="current-password"
        />
        <PasswordInput
          label={t('auth.fields.newPassword')}
          name="newPassword"
          value={formData.newPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          error={visibleErrors.newPassword}
          placeholder={t('auth.placeholders.newPassword')}
          autoComplete="new-password"
        />
        <PasswordInput
          label={t('auth.fields.confirmNewPassword')}
          name="confirmPassword"
          value={formData.confirmPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          error={visibleErrors.confirmPassword}
          placeholder={t('auth.placeholders.confirmNewPassword')}
          autoComplete="new-password"
        />
        {visibleApiError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600">{visibleApiError}</p>
          </div>
        )}
        {successMessage && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-sm text-green-700">{t(successMessage)}</p>
          </div>
        )}
        <Button type="submit" className="w-full" loading={loading} disabled={!isFormValid}>
          {t('profile.password.submit')}
        </Button>
      </form>
    </div>
  )
}

const ALL_TABS = [
  { key: 'topup', labelKey: 'profile.tabs.topup' },
  { key: 'password', labelKey: 'profile.tabs.password' },
  { key: 'advanced', labelKey: 'profile.tabs.advanced', hideForAdmin: true },
]

export function ProfilePage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const TABS = ALL_TABS.filter(t => !(t.hideForAdmin && isAdmin))

  const [activeTab, setActiveTab] = useState('topup')

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />

      <div className="max-w-4xl mx-auto px-4 py-10">
        {/* Breadcrumb */}
        <div className="mb-6 flex items-center gap-2 text-sm text-gray-500">
          <Link to="/dashboard" className="hover:text-primary transition-colors">
            {t('profile.breadcrumbHome')}
          </Link>
          <span>/</span>
          <span className="text-gray-700 font-medium">{t('profile.title')}</span>
        </div>

        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{t('profile.title')}</h1>
          <p className="text-gray-500 mt-1">{user?.email}</p>
          {isAdmin && (
            <p className="text-xs text-purple-600 mt-1">
              {t('profile.adminConfigHint')}{' '}
              <Link to="/admin/config" className="underline hover:text-purple-700">{t('profile.adminConfigLink')}</Link>.
            </p>
          )}
        </div>

        {/* Tab nav */}
        <div className="flex gap-1 border-b border-gray-200 mb-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === tab.key
                  ? 'text-primary border-b-2 border-primary -mb-px bg-white'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t(tab.labelKey)}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'topup' && <TopUpTab />}
        {activeTab === 'password' && <ChangePasswordTab />}
        {activeTab === 'advanced' && (
          <div>
            <p className="text-sm text-gray-500 mb-4">
              {t('profile.advancedIntro')}
            </p>
            <AdvancedSettings />
          </div>
        )}
      </div>
    </div>
  )
}
