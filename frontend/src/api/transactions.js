import axios from './axios'

export const transactionsAPI = {
  create: (planId) => axios.post('/transactions', { plan_id: planId }),
  listMine: () => axios.get('/user/transactions'),
}
