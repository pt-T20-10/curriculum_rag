import apiClient from './axios'

export const authAPI = {
  login: (identifier, password, remember_me = false) =>
    apiClient.post('/auth/login', { identifier, password, remember_me }),

  register: (email, password, full_name, username) =>
    apiClient.post('/auth/register', { email, username: username || undefined, password, full_name }),

  me: () =>
    apiClient.get('/auth/me'),

  // Returns { auth_url, state } — caller stores state and redirects to auth_url
  getGoogleLoginUrl: () =>
    apiClient.get('/auth/google/login'),

  forgotPassword: (email) =>
    apiClient.post('/auth/forgot-password', { email }),

  resetPassword: (email, code, new_password) =>
    apiClient.post('/auth/reset-password', { email, code, new_password }),

  verifyEmail: (email, code) =>
    apiClient.post('/auth/verify-email', { email, code }),

  resendVerification: (email) =>
    apiClient.post('/auth/resend-verification', { email }),

  changePassword: (current_password, new_password) =>
    apiClient.patch('/auth/change-password', { current_password, new_password }),
}
