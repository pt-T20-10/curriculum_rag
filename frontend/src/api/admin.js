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

  // Bank config
  getBankConfig: () => axios.get('/admin/bank-config'),
  updateBankConfig: (data) => axios.put('/admin/bank-config', data),

  // Plans
  listPlans: () => axios.get('/admin/plans'),
  createPlan: (data) => axios.post('/admin/plans', data),
  updatePlan: (id, data) => axios.put(`/admin/plans/${id}`, data),
  deletePlan: (id) => axios.delete(`/admin/plans/${id}`),

  // Transactions
  listTransactions: (params) => axios.get('/admin/transactions', { params }),
  confirmTransaction: (id) => axios.post(`/admin/transactions/${id}/confirm`),
  rejectTransaction: (id, reason) => axios.post(`/admin/transactions/${id}/reject`, { reason }),
}
