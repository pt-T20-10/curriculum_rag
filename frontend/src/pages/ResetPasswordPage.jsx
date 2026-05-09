import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authAPI } from '../api/auth'
import { Input } from '../components/common/Input'
import { Button } from '../components/common/Button'

export function ResetPasswordPage() {
  const navigate = useNavigate()
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

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }))
    setApiError('')
  }

  const validate = () => {
    const newErrors = {}

    if (!formData.email) newErrors.email = 'Email là bắt buộc'
    else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = 'Email không hợp lệ'

    if (!formData.code) newErrors.code = 'Mã xác nhận là bắt buộc'
    else if (!/^\d{6}$/.test(formData.code)) newErrors.code = 'Mã phải gồm đúng 6 chữ số'

    if (!formData.new_password) newErrors.new_password = 'Mật khẩu mới là bắt buộc'
    else if (formData.new_password.length < 8) newErrors.new_password = 'Mật khẩu phải có ít nhất 8 ký tự'

    if (!formData.confirm_password) newErrors.confirm_password = 'Vui lòng xác nhận mật khẩu'
    else if (formData.new_password !== formData.confirm_password)
      newErrors.confirm_password = 'Mật khẩu xác nhận không khớp'

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
        state: { successMessage: 'Mật khẩu đã được đặt lại. Vui lòng đăng nhập.' },
        replace: true,
      })
    } catch (err) {
      setApiError(
        err.response?.data?.detail ||
        'Đã xảy ra lỗi. Vui lòng thử lại.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-center text-gray-800 mb-2">Đặt lại mật khẩu</h1>
        <p className="text-center text-gray-500 mb-6 text-sm">
          Nhập mã 6 số đã gửi về email và mật khẩu mới của bạn.
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label="Email"
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            error={errors.email}
            placeholder="email@cuaban.com"
          />

          <Input
            label="Mã xác nhận (6 chữ số)"
            type="text"
            name="code"
            value={formData.code}
            onChange={handleChange}
            error={errors.code}
            placeholder="123456"
            maxLength={6}
            inputMode="numeric"
            autoComplete="one-time-code"
          />

          <Input
            label="Mật khẩu mới"
            type="password"
            name="new_password"
            value={formData.new_password}
            onChange={handleChange}
            error={errors.new_password}
            placeholder="Tối thiểu 8 ký tự"
          />

          <Input
            label="Xác nhận mật khẩu mới"
            type="password"
            name="confirm_password"
            value={formData.confirm_password}
            onChange={handleChange}
            error={errors.confirm_password}
            placeholder="Nhập lại mật khẩu mới"
          />

          {apiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-600">{apiError}</p>
            </div>
          )}

          <Button type="submit" className="w-full" loading={loading}>
            Đặt lại mật khẩu
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Chưa có mã?{' '}
          <Link to="/forgot-password" className="text-primary hover:underline font-medium">
            Gửi lại
          </Link>
          {' · '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            Đăng nhập
          </Link>
        </p>
      </div>
    </div>
  )
}
