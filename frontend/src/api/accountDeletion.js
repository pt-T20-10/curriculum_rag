import apiClient from './axios'

export const accountDeletionAPI = {
  sendRequest: data => apiClient.post('/account-deletion-requests', data),
}
