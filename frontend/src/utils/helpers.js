import { buildBackendUrl } from './apiConfig'

export const getOutputUrl = (outputPath) => {
  if (!outputPath) return null

  const normalized = outputPath.replace(/\\/g, '/')
  const outputsMatch = normalized.match(/(?:^|\/)outputs\/(.+)$/)
  const relativePath = outputsMatch
    ? outputsMatch[1]
    : normalized.replace(/^backend\//, '').replace(/^\//, '').replace(/^outputs\//, '')
  const encodedPath = relativePath.split('/').map(encodeURIComponent).join('/')

  return buildBackendUrl(`/outputs/${encodedPath}`)
}

const hasExtension = (outputPath, extension) => {
  if (!outputPath) return false
  const pathOnly = String(outputPath).split(/[?#]/, 1)[0]
  return pathOnly.toLowerCase().endsWith(extension)
}

export const isPdfPath = (outputPath) => hasExtension(outputPath, '.pdf')
export const isDocxPath = (outputPath) => hasExtension(outputPath, '.docx')

export const getPdfUrl = (outputPath) => (
  isPdfPath(outputPath) ? getOutputUrl(outputPath) : null
)

export const getDocxUrl = (outputPath) => (
  isDocxPath(outputPath) ? getOutputUrl(outputPath) : null
)
