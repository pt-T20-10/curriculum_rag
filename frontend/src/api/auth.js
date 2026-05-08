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
}