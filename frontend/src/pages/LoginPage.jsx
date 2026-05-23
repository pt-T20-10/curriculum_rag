import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Input } from '../components/common/Input'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { GoogleLoginButton } from '../components/common/GoogleLoginButton'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const successMessage = location.state?.successMessage || ''

  const [formData, setFormData] = useState({
    email: '',
    password: '',
  })
  const [rememberMe, setRememberMe] = useState(false)
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState('')    // generic banner error
  const [fieldErrors, setFieldErrors] = useState({})  // per-field API errors

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }))
    if (fieldErrors[name]) setFieldErrors(prev => ({ ...prev, [name]: '' }))
    setApiError('')
  }

  const validate = () => {
    const newErrors = {}

    if (!formData.email) {
      newErrors.email = 'Email là bắt buộc'
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Email không hợp lệ'
    }

    if (!formData.password) {
      newErrors.password = 'Mật khẩu là bắt buộc'
    } else if (formData.password.length < 6) {
      newErrors.password = 'Mật khẩu phải có ít nhất 6 ký tự'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!validate()) return

    setLoading(true)
    setApiError('')

    try {
      await login(formData.email, formData.password, rememberMe)
      navigate('/dashboard', { replace: true })
    } catch (error) {
      const detail = error.response?.data?.detail || ''
      const status = error.response?.status

      if (status === 404 || detail.includes('email')) {
        // Account not found — highlight email field
        setFieldErrors({ email: detail || 'Không tìm thấy tài khoản với email này' })
      } else if (status === 401 || detail.includes('Mật khẩu')) {
        // Wrong password — highlight password field, keep email intact
        setFieldErrors({ password: detail || 'Mật khẩu không đúng' })
        setFormData(prev => ({ ...prev, password: '' }))
      } else if (status === 403) {
        setApiError(detail || 'Tài khoản đã bị khóa. Vui lòng liên hệ hỗ trợ.')
      } else {
        setApiError(detail || 'Đăng nhập thất bại. Vui lòng kiểm tra lại thông tin.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 className="text-3xl font-bold text-center text-primary mb-2">
          Chào mừng trở lại
        </h1>
        <p className="text-center text-gray-600 mb-6">
          Đăng nhập vào tài khoản Hệ Thống Tạo Giáo Trình AI
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label="Email"
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            error={errors.email || fieldErrors.email}
            placeholder="email@cuaban.com"
            autoFocus
          />

          <PasswordInput
            label="Mật khẩu"
            name="password"
            value={formData.password}
            onChange={handleChange}
            error={errors.password || fieldErrors.password}
            placeholder="Nhập mật khẩu của bạn"
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
                Ghi nhớ đăng nhập
                <span className="text-xs text-gray-400 ml-1">(30 ngày)</span>
              </label>
            </div>
            <Link to="/forgot-password" className="text-sm text-primary hover:underline">
              Quên mật khẩu?
            </Link>
          </div>

          {successMessage && (
            <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
              <p className="text-sm text-green-700">{successMessage}</p>
            </div>
          )}

          {apiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-600">{apiError}</p>
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            loading={loading}
          >
            Đăng nhập
          </Button>
        </form>

        <div className="mt-6">
          <div className="relative flex items-center gap-3 mb-4">
            <div className="flex-1 border-t border-gray-200" />
            <span className="text-xs text-gray-400">hoặc</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
          <GoogleLoginButton />
        </div>

        <p className="mt-4 text-center text-sm text-gray-600">
          Chưa có tài khoản?{' '}
          <Link to="/register" className="text-primary hover:underline font-medium">
            Đăng ký ngay
          </Link>
        </p>
      </div>
    </div>
  )
}
