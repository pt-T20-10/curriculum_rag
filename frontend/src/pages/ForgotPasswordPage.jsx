import { useState } from 'react'
import { Link } from 'react-router-dom'
import { authAPI } from '../api/auth'
import { Input } from '../components/common/Input'
import { Button } from '../components/common/Button'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [apiError, setApiError] = useState('')

  const validate = () => {
    if (!email) {
      setEmailError('Email là bắt buộc')
      return false
    }
    if (!/\S+@\S+\.\S+/.test(email)) {
      setEmailError('Email không hợp lệ')
      return false
    }
    setEmailError('')
    return true
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!validate()) return

    setLoading(true)
    setApiError('')
    try {
      await authAPI.forgotPassword(email)
      setSent(true)
    } catch {
      setApiError('Đã xảy ra lỗi. Vui lòng thử lại sau.')
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-800 mb-2">Kiểm tra email của bạn</h2>
          <p className="text-gray-600 mb-2">
            Nếu địa chỉ <strong>{email}</strong> tồn tại trong hệ thống, chúng tôi đã gửi mã xác nhận 6 chữ số.
          </p>
          <p className="text-sm text-gray-400 mb-6">Mã có hiệu lực trong 15 phút.</p>
          <Link
            to={`/reset-password?email=${encodeURIComponent(email)}`}
            className="inline-block w-full py-2.5 px-4 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 transition-colors text-center"
          >
            Nhập mã xác nhận
          </Link>
          <p className="mt-4 text-sm text-gray-500">
            <button
              onClick={() => { setSent(false); setEmail('') }}
              className="text-primary hover:underline"
            >
              Thử email khác
            </button>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-center text-gray-800 mb-2">Quên mật khẩu?</h1>
        <p className="text-center text-gray-500 mb-6 text-sm">
          Nhập email tài khoản của bạn và chúng tôi sẽ gửi mã xác nhận.
        </p>

        <form onSubmit={handleSubmit}>
          <Input
            label="Email"
            type="email"
            name="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setEmailError('') }}
            error={emailError}
            placeholder="email@cuaban.com"
            autoFocus
          />

          {apiError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-600">{apiError}</p>
            </div>
          )}

          <Button type="submit" className="w-full" loading={loading}>
            Gửi mã xác nhận
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Nhớ mật khẩu rồi?{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            Đăng nhập
          </Link>
        </p>
      </div>
    </div>
  )
}
