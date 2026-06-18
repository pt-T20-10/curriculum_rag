export function i18nError(key, values = undefined, fallback = undefined) {
  return { key, values, fallback }
}

export function rawError(fallback) {
  return fallback ? { fallback } : null
}

export function errorMessage(error, t) {
  if (!error) return ''
  if (typeof error === 'string') {
    const known = mapKnownRawMessage(error)
    return known ? errorMessage(known, t) : error
  }
  if (error.key) {
    return t(error.key, {
      ...(error.values || {}),
      defaultValue: error.fallback,
    })
  }
  if (error.fallback) {
    const known = mapKnownRawMessage(error.fallback)
    if (known) return errorMessage(known, t)
  }
  return error.fallback || ''
}

export function errorMessages(errors, t) {
  return Object.fromEntries(
    Object.entries(errors || {}).map(([field, error]) => [field, errorMessage(error, t)])
  )
}

function normalizeDetail(detail) {
  return String(detail || '').toLowerCase()
}

function mapKnownRawMessage(detail) {
  const text = normalizeDetail(detail)

  if (!text) return null
  if (text.includes('mật khẩu không đúng') || text.includes('incorrect password')) {
    return i18nError('auth.login.wrongPassword')
  }
  if (text.includes('không tìm thấy tài khoản') || text.includes('no account found')) {
    return i18nError('auth.login.accountNotFound')
  }
  if (text.includes('tài khoản đã bị khóa') || text.includes('account is locked')) {
    return i18nError('auth.login.locked')
  }
  if (text.includes('chưa được kích hoạt') || text.includes('not been activated')) {
    return i18nError('auth.login.inactive')
  }
  if (text.includes('đăng ký qua google') || text.includes('google sign-in')) {
    return i18nError('auth.login.googleAccount')
  }
  if (text.includes('tên đăng nhập')) {
    return i18nError('auth.validation.usernameTaken')
  }
  if (text.includes('email') && (text.includes('đăng ký') || text.includes('registered') || text.includes('in use'))) {
    return i18nError('auth.validation.emailTaken')
  }
  if (text.includes('mã xác nhận') || text.includes('verification code')) {
    return i18nError('auth.reset.invalidCode')
  }
  if (text.includes('mật khẩu hiện tại') || text.includes('current password')) {
    return i18nError('auth.validation.currentPasswordWrong')
  }
  if (text.includes('mật khẩu mới phải khác') || text.includes('new password must be different')) {
    return i18nError('auth.validation.passwordDifferent')
  }

  return null
}

export function mapLoginError(detail, status) {
  const text = normalizeDetail(detail)

  if (status === 404 || text.includes('không tìm thấy') || text.includes('not found')) {
    return i18nError('auth.login.accountNotFound')
  }
  if (
    status === 401 ||
    text.includes('mật khẩu') ||
    text.includes('password incorrect') ||
    text.includes('incorrect password') ||
    text.includes('wrong password')
  ) {
    return i18nError('auth.login.wrongPassword')
  }
  if (status === 403 || text.includes('khóa') || text.includes('locked') || text.includes('disabled')) {
    return i18nError('auth.login.locked')
  }
  if (text.includes('chưa được kích hoạt') || text.includes('inactive') || text.includes('not active')) {
    return i18nError('auth.login.inactive')
  }
  if (text.includes('google')) {
    return i18nError('auth.login.googleAccount')
  }
  if (status === 400) return i18nError('auth.login.badRequest')

  return detail ? rawError(detail) : i18nError('auth.login.failed')
}

export function mapRegisterError(detail) {
  const text = normalizeDetail(detail)

  if (text.includes('tên đăng nhập') || text.includes('username')) {
    return i18nError('auth.validation.usernameTaken')
  }
  if (text.includes('email')) {
    return i18nError('auth.validation.emailTaken')
  }

  return detail ? rawError(detail) : i18nError('auth.register.failed')
}

export function mapPasswordError(detail, fallbackKey = 'auth.validation.generic') {
  const text = normalizeDetail(detail)

  if (text.includes('mã xác nhận') || text.includes('code') || text.includes('otp')) {
    return i18nError('auth.reset.invalidCode')
  }
  if (
    text.includes('mật khẩu mới phải khác') ||
    text.includes('new password must be different')
  ) {
    return i18nError('auth.validation.passwordDifferent')
  }
  if (
    text.includes('mật khẩu hiện tại') ||
    text.includes('current password') ||
    text.includes('incorrect password') ||
    text.includes('wrong password')
  ) {
    return i18nError('auth.validation.currentPasswordWrong')
  }
  if (text.includes('không sử dụng mật khẩu') || text.includes('google')) {
    return i18nError('profile.password.googleAccount')
  }

  return detail ? rawError(detail) : i18nError(fallbackKey)
}
