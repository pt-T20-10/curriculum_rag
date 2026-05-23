import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authAPI } from '../api/auth'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { Navbar } from '../components/layout/Navbar'
import { TopUpTab } from '../components/topup/TopUpTab'
import { AdvancedSettings } from '../components/settings/AdvancedSettings'

const EMPTY_FORM = { currentPassword: '', newPassword: '', confirmPassword: '' }

function validateField(name, value, allData) {
  switch (name) {
    case 'currentPassword':
      if (!value.trim()) return 'Mật khẩu hiện tại là bắt buộc'
      return ''
    case 'newPassword':
      if (!value) return 'Mật khẩu mới là bắt buộc'
      if (value.length < 8) return 'Mật khẩu phải có ít nhất 8 ký tự'
      if (!/[A-Z]/.test(value)) return 'Mật khẩu phải có ít nhất 1 chữ hoa'
      if (!/[0-9]/.test(value)) return 'Mật khẩu phải có ít nhất 1 chữ số'
      if (allData?.currentPassword && value === allData.currentPassword)
        return 'Mật khẩu mới phải khác mật khẩu hiện tại'
      return ''
    case 'confirmPassword':
      if (value !== allData?.newPassword) return 'Mật khẩu xác nhận không khớp'
      return ''
    default:
      return ''
  }
}

function ChangePasswordTab() {
  const { user } = useAuth()
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState({})
  const [loading, setLoading] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')
  const [apiError, setApiError] = useState('')

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
      setSuccessMessage('Mật khẩu đã được cập nhật thành công!')
      setTimeout(() => setSuccessMessage(''), 2000)
    } catch (error) {
      const detail = error.response?.data?.detail
      if (detail === 'Mật khẩu hiện tại không đúng') {
        setErrors(prev => ({ ...prev, currentPassword: detail }))
      } else {
        setApiError(detail || 'Không thể cập nhật mật khẩu. Vui lòng thử lại.')
      }
    } finally {
      setLoading(false)
    }
  }

  if (user?.auth_provider === 'google') {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 max-w-md">
        <h2 className="text-lg font-semibold text-gray-800 mb-5">Đổi mật khẩu</h2>
        <p className="text-sm text-gray-500">
          Tài khoản của bạn đăng nhập qua Google và không sử dụng mật khẩu.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 max-w-md">
      <h2 className="text-lg font-semibold text-gray-800 mb-5">Đổi mật khẩu</h2>
      <form onSubmit={handleSubmit} noValidate>
        <PasswordInput
          label="Mật khẩu hiện tại"
          name="currentPassword"
          value={formData.currentPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          error={errors.currentPassword}
          placeholder="Nhập mật khẩu hiện tại"
          autoComplete="current-password"
        />
        <PasswordInput
          label="Mật khẩu mới"
          name="newPassword"
          value={formData.newPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          error={errors.newPassword}
          placeholder="Ít nhất 8 ký tự, 1 chữ hoa, 1 số"
          autoComplete="new-password"
        />
        <PasswordInput
          label="Xác nhận mật khẩu mới"
          name="confirmPassword"
          value={formData.confirmPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          error={errors.confirmPassword}
          placeholder="Nhập lại mật khẩu mới"
          autoComplete="new-password"
        />
        {apiError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600">{apiError}</p>
          </div>
        )}
        {successMessage && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-sm text-green-700">{successMessage}</p>
          </div>
        )}
        <Button type="submit" className="w-full" loading={loading} disabled={!isFormValid}>
          Cập nhật mật khẩu
        </Button>
      </form>
    </div>
  )
}

const ALL_TABS = [
  { key: 'topup', label: 'Credits & Nạp tiền' },
  { key: 'password', label: 'Đổi mật khẩu' },
  { key: 'advanced', label: 'Nâng cao', hideForAdmin: true },
]

export function ProfilePage() {
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
            Trang chủ
          </Link>
          <span>/</span>
          <span className="text-gray-700 font-medium">Cài đặt tài khoản</span>
        </div>

        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Cài đặt tài khoản</h1>
          <p className="text-gray-500 mt-1">{user?.email}</p>
          {isAdmin && (
            <p className="text-xs text-purple-600 mt-1">
              Để chỉnh cấu hình hệ thống, vào{' '}
              <Link to="/admin/config" className="underline hover:text-purple-700">Admin → Cấu hình hệ thống</Link>.
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
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'topup' && <TopUpTab />}
        {activeTab === 'password' && <ChangePasswordTab />}
        {activeTab === 'advanced' && (
          <div>
            <p className="text-sm text-gray-500 mb-4">
              Ghi đè tham số tạo nội dung cho tài khoản của bạn. Thay đổi áp dụng từ lần tạo giáo trình tiếp theo.
            </p>
            <AdvancedSettings />
          </div>
        )}
      </div>
    </div>
  )
}
