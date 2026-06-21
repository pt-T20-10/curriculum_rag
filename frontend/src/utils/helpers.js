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

export const getPdfUrl = getOutputUrl
