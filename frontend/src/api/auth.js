import apiClient from './axios'

export const authAPI = {
  // Login
  login: (email, password, remember_me = false) =>
    apiClient.post('/auth/login', { email, password, remember_me }),
  
  // Register
  register: (email, password, full_name) => 
    apiClient.post('/auth/register', { email, password, full_name }),
  
  // Get current user
  me: () => 
    apiClient.get('/auth/me'),
}