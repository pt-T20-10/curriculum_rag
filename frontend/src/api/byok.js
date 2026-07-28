import axios from './axios'

export const byokAPI = {
  status: () => axios.get('/byok/status'),
  validate: (data) => axios.post('/byok/validate', data),
}
