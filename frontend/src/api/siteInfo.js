import apiClient from './axios'

export const siteInfoAPI = {
  getPublic: language => apiClient.get('/site-info', { params: { language } }),
  getAdmin: () => apiClient.get('/admin/site-info'),
  updateAdmin: data => apiClient.put('/admin/site-info', data),
}
