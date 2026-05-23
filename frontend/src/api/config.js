import apiClient from './axios'

export const configAPI = {
  // Parameter registry — drives field rendering in both user and admin UIs
  getRegistry: () => apiClient.get('/config/registry'),

  // Merged effective config for the current logged-in user
  getEffective: () => apiClient.get('/config/effective'),

  // User advanced settings
  getUserOverrides: () => apiClient.get('/config/user/advanced'),
  saveUserOverrides: (overrides) => apiClient.post('/config/user/advanced', { overrides }),
  resetUserOverrides: () => apiClient.delete('/config/user/advanced'),

  // Admin system config
  getSystemConfig: () => apiClient.get('/config/admin/system'),
  updateSystemConfig: (updates) => apiClient.put('/config/admin/system', { updates }),
  getAuditLog: (limit = 20) => apiClient.get('/config/admin/system/audit', { params: { limit } }),
  getOverrideCounts: () => apiClient.get('/config/admin/system/overrides'),
}
