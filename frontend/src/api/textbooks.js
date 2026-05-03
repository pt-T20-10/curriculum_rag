import axios from './axios'

export const textbooksAPI = {
  // List textbooks
  list: (params) => axios.get('/textbooks', { params }),
  
  // Get single textbook
  get: (id) => axios.get(`/textbooks/${id}`),
  
  // Create textbook
  create: (data) => axios.post('/textbooks', data),
  
  // Delete textbook
  delete: (id) => axios.delete(`/textbooks/${id}`),
  
  // Get progress (for polling)
  getProgress: (id) => axios.get(`/textbooks/${id}/progress`),
  
  // Stop generation
  stop: (id) => axios.post(`/textbooks/${id}/stop`),
  
  // ⭐ Confirm curriculum (simplified - no Chapter 1 preview)
  confirmCurriculum: (id, curriculum) => 
    axios.post(`/textbooks/${id}/confirm-curriculum`, { curriculum }),
}