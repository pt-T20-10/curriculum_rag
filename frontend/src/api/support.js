import apiClient from './axios'

export const supportAPI = {
  sendRequest: data => apiClient.post('/support/requests', data),
}
