import axios from './axios'

export const byokAPI = {
  status: () => axios.get('/byok/status'),
  updateCredentials: (data) => axios.put('/byok/credentials', data),
  deleteCredential: (provider) => axios.delete(`/byok/credentials/${provider}`),
  validate: (data) => axios.post('/byok/validate', data),
}
