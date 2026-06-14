import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Input } from '../components/common/Input'
import { PasswordInput } from '../components/common/PasswordInput'
import { Button } from '../components/common/Button'
import { GoogleLoginButton } from '../components/common/GoogleLoginButton'

const USERNAME_REGEX = /^[a-zA-Z0-9_.-]+$/

export function RegisterPage() {
  const navigate = useNavigate()
  const { register } = useAuth()

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
      newErrors.fullName = 'Họ tên là bắt buộc'
    }

    if (formData.username) {
      const u = formData.username.trim()
      if (u.length < 3) {
        newErrors.username = 'Tên đăng nhập phải có ít nhất 3 ký tự'
      } else if (u.length > 50) {
        newErrors.username = 'Tên đăng nhập tối đa 50 ký tự'
      } else if (!USERNAME_REGEX.test(u)) {
        newErrors.username = 'Chỉ được dùng chữ cái, số, dấu _ . -'
      }
    }

    if (!formData.email) {
      newErrors.email = 'Email là bắt buộc'
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Email không hợp lệ'
    }

    if (!formData.password) {
      newErrors.password = 'Mật khẩu là bắt buộc'
    } else if (formData.password.length < 8) {
      newErrors.password = 'Mật khẩu phải có ít nhất 8 ký tự'
    }

    if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Mật khẩu xác nhận không khớp'
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

      if (status === 400 && detail.includes('Tên đăng nhập')) {
        setFieldErrors({ username: detail })
      } else if (status === 400 && (detail.includes('Email') || detail.includes('email'))) {
        setFieldErrors({ email: detail })
      } else if (status === 422) {
        // Pydantic validation error — extract first message
        const msgs = error.response?.data?.detail
        const first = Array.isArray(msgs) ? msgs[0]?.msg : detail
        setApiError(first || 'Dữ liệu không hợp lệ.')
      } else {
        setApiError(detail || 'Đăng ký thất bại. Vui lòng thử lại.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 className="text-3xl font-bold text-center text-primary mb-2">
          Tạo tài khoản
        </h1>
        <p className="text-center text-gray-600 mb-6">
          Bắt đầu tạo giáo trình bằng AI
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label="Họ và tên"
            type="text"
            name="fullName"
            value={formData.fullName}
            onChange={handleChange}
            error={errors.fullName}
            placeholder="Nguyễn Văn A"
            autoFocus
          />

          <Input
            label={<>Tên đăng nhập <span className="text-gray-400 font-normal">(tùy chọn)</span></>}
            type="text"
            name="username"
            value={formData.username}
            onChange={handleChange}
            error={errors.username || fieldErrors.username}
            placeholder="Dùng để đăng nhập thay cho email"
          />

          <Input
            label="Email"
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            error={errors.email || fieldErrors.email}
            placeholder="email@cuaban.com"
          />

          <PasswordInput
            label="Mật khẩu"
            name="password"
            value={formData.password}
            onChange={handleChange}
            error={errors.password}
            placeholder="Ít nhất 8 ký tự"
          />

          <PasswordInput
            label="Xác nhận mật khẩu"
            name="confirmPassword"
            value={formData.confirmPassword}
            onChange={handleChange}
            error={errors.confirmPassword}
            placeholder="Nhập lại mật khẩu"
          />

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
            Đăng ký
          </Button>
        </form>

        <div className="mt-6">
          <div className="relative flex items-center gap-3 mb-4">
            <div className="flex-1 border-t border-gray-200" />
            <span className="text-xs text-gray-400">hoặc đăng ký nhanh</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
          <GoogleLoginButton label="Đăng ký với Google" />
        </div>

        <p className="mt-4 text-center text-sm text-gray-600">
          Đã có tài khoản?{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            Đăng nhập tại đây
          </Link>
        </p>
      </div>
    </div>
  )
}
