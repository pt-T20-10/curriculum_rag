import { useCallback, useEffect, useState } from 'react'
import { siteInfoAPI } from '../api/siteInfo'

export const SITE_INFO_UPDATED_EVENT = 'site-info-updated'

const EMPTY_SITE_INFO = {
  service_name: '',
  operator_name: '',
  address: '',
  support_email: '',
  privacy_email: '',
  phone: '',
  support_hours: '',
  response_time: '',
  effective_date: null,
}

export function useSiteInfo(language = 'vi') {
  const normalizedLanguage = language === 'en' ? 'en' : 'vi'
  const [siteInfo, setSiteInfo] = useState(EMPTY_SITE_INFO)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const response = await siteInfoAPI.getPublic(normalizedLanguage)
      setSiteInfo({ ...EMPTY_SITE_INFO, ...response.data })
    } catch {
      setSiteInfo(EMPTY_SITE_INFO)
    } finally {
      setLoading(false)
    }
  }, [normalizedLanguage])

  useEffect(() => {
    let active = true
    const reload = () => {
      if (active) load()
    }

    queueMicrotask(reload)
    window.addEventListener(SITE_INFO_UPDATED_EVENT, reload)
    window.addEventListener('focus', reload)
    return () => {
      active = false
      window.removeEventListener(SITE_INFO_UPDATED_EVENT, reload)
      window.removeEventListener('focus', reload)
    }
  }, [load])

  return { siteInfo, loading, reload: load }
}
