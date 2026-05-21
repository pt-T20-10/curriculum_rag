import apiClient from './axios'

export const authAPI = {
  login: (email, password, remember_me = false) =>
    apiClient.post('/auth/login', { email, password, remember_me }),

  register: (email, password, full_name) =>
    apiClient.post('/auth/register', { email, password, full_name }),

  me: () =>
    apiClient.get('/auth/me'),

  // Returns { auth_url, state } — caller stores state and redirects to auth_url
  getGoogleLoginUrl: () =>
    apiClient.get('/auth/google/login'),

  forgotPassword: (email) =>
    apiClient.post('/auth/forgot-password', { email }),

  resetPassword: (email, code, new_password) =>
    apiClient.post('/auth/reset-password', { email, code, new_password }),

  changePassword: (current_password, new_password) =>
    apiClient.patch('/auth/change-password', { current_password, new_password }),
}