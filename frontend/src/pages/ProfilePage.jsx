import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authAPI } from '../api/auth'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { Navbar } from '../components/layout/Navbar'

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

export function ProfilePage() {
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
    // keep confirmPassword in sync when newPassword changes
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

    // touch all fields to reveal any hidden errors
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
        setApiError(
          detail || 'Không thể cập nhật mật khẩu. Vui lòng thử lại.'
        )
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />

      <div className="max-w-2xl mx-auto px-4 py-10">
        {/* Breadcrumb */}
        <div className="mb-6 flex items-center gap-2 text-sm text-gray-500">
          <Link to="/dashboard" className="hover:text-primary transition-colors">
            Trang chủ
          </Link>
          <span>/</span>
          <span className="text-gray-700 font-medium">Cài đặt tài khoản</span>
        </div>

        {/* Page header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Cài đặt tài khoản</h1>
          <p className="text-gray-500 mt-1">{user?.email}</p>
        </div>

        {/* Change Password Card */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 max-w-md">
          <h2 className="text-lg font-semibold text-gray-800 mb-5">Đổi mật khẩu</h2>

          {user?.auth_provider === 'google' ? (
            <p className="text-sm text-gray-500">
              Tài khoản của bạn đăng nhập qua Google và không sử dụng mật khẩu.
            </p>
          ) : (
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

              <Button
                type="submit"
                className="w-full"
                loading={loading}
                disabled={!isFormValid}
              >
                Cập nhật mật khẩu
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
