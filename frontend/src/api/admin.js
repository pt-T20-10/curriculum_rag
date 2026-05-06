import axios from './axios'

export const adminAPI = {
  // Stats
  getOverview: () => axios.get('/admin/stats/overview'),
  getGenerationTrends: (days = 30) => axios.get('/admin/stats/generation-trends', { params: { days } }),
  getTopTopics: (limit = 5) => axios.get('/admin/stats/top-topics', { params: { limit } }),
  getPaymentTrends: (days = 30) => axios.get('/admin/stats/payment-trends', { params: { days } }),

  // Users
  listUsers: (params) => axios.get('/admin/users', { params }),
  lockUser: (userId, reason) => axios.post(`/admin/users/${userId}/lock`, { reason }),
  unlockUser: (userId) => axios.post(`/admin/users/${userId}/unlock`),
  changeUserRole: (userId, role) => axios.put(`/admin/users/${userId}/role`, null, { params: { role } }),

  // Textbooks
  listTextbooks: (params) => axios.get('/admin/textbooks', { params }),
}
