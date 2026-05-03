export const getPdfUrl = (pdfPath) => {
  if (!pdfPath) return null
  
  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  
  // ⭐ Convert Windows backslash to forward slash
  let cleanPath = pdfPath.replace(/\\/g, '/')
  
  // Remove prefixes
  cleanPath = cleanPath
    .replace(/^backend\//, '')     // Remove "backend/"
    .replace(/^\//, '')             // Remove leading "/"
    .replace(/^outputs\//, '')      // Remove "outputs/" prefix
  
  // Build final URL
  return `${API_BASE}/outputs/${cleanPath}`
}