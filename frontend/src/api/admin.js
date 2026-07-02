import axios from './axios'

export const adminAPI = {
  // Stats
  getOverview: () => axios.get('/admin/stats/overview'),
  getGenerationTrends: (params) => axios.get('/admin/stats/generation-trends', { params }),
  getTopContentTypes: (limit = 5) => axios.get('/admin/stats/top-content-types', { params: { limit } }),
  getPaymentTrends: (params) => axios.get('/admin/stats/payment-trends', { params }),
  getTopUsersTopup: (limit = 5) => axios.get('/admin/stats/top-users-topup', { params: { limit } }),
  getTopUsersTextbooks: (limit = 5) => axios.get('/admin/stats/top-users-textbooks', { params: { limit } }),

  // Users
  listUsers: (params) => axios.get('/admin/users', { params }),
  lockUser: (userId, reason) => axios.post(`/admin/users/${userId}/lock`, { reason }),
  unlockUser: (userId) => axios.post(`/admin/users/${userId}/unlock`),
  deleteUser: (userId) => axios.delete(`/admin/users/${userId}`),
  changeUserRole: (userId, role) => axios.put(`/admin/users/${userId}/role`, null, { params: { role } }),
  adjustUserCredits: (userId, data) => axios.post(`/admin/users/${userId}/credits/adjust`, data),

  // Textbooks
  listTextbooks: (params) => axios.get('/admin/textbooks', { params }),
  getTextbook: (id) => axios.get(`/admin/textbooks/${id}`),

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
