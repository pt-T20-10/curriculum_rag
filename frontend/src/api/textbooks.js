import axios from './axios'

export const textbooksAPI = {
  // List textbooks
  list: (params) => axios.get('/textbooks/', { params }),
  
  // Get single textbook
  get: (id) => axios.get(`/textbooks/${id}`),
  
  // Create textbook
  create: (data) => axios.post('/textbooks/', data),

  // Parse an uploaded outline file into the manual structure editor shape
  parseStructureFile: (formData) =>
    axios.post('/textbooks/parse-structure-file', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  
  // Delete textbook
  delete: (id) => axios.delete(`/textbooks/${id}`),
  
  // Get progress (for polling)
  getProgress: (id) => axios.get(`/textbooks/${id}/progress`),

  // Get server task status (preferred realtime polling path)
  getTask: (taskId) => axios.get(`/tasks/${taskId}`),
  
  // Stop generation
  stop: (id) => axios.post(`/textbooks/${id}/stop`),

  // Estimate credits for the confirmed curriculum without charging
  estimateCredits: (id, curriculum) =>
    axios.post(`/textbooks/${id}/estimate-credits`, { curriculum }),
  
  // ⭐ Confirm curriculum (simplified - no Chapter 1 preview)
  confirmCurriculum: (id, curriculum, pagePlanConfirmed = false, options = {}) =>
    axios.post(`/textbooks/${id}/confirm-curriculum`, {
      curriculum,
      page_plan_confirmed: pagePlanConfirmed,
      ...options,
    }),
}
