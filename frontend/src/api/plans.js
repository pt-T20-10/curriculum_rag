import axios from './axios'

export const plansAPI = {
  listActive: () => axios.get('/plans'),
  getBankConfig: () => axios.get('/plans/bank-config'),
  getUserCredits: () => axios.get('/user/credits'),
  getCreditHistory: () => axios.get('/user/credit-history'),
}
