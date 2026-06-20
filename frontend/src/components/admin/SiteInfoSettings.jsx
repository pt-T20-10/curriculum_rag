import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { siteInfoAPI } from '../../api/siteInfo'
import { SITE_INFO_UPDATED_EVENT } from '../../hooks/useSiteInfo'
import { loadLegacySiteInfo } from '../../utils/landingConfig'

const EMPTY_DATA = {
  service_name_vi: '',
  service_name_en: '',
  operator_name: '',
  address_vi: '',
  address_en: '',
  support_email: '',
  privacy_email: '',
  phone: '',
  support_hours_vi: '',
  support_hours_en: '',
  response_time_vi: '',
  response_time_en: '',
  effective_date: '',
}

const inputClassName = 'mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100'

function normalizeLegacyDate(...values) {
  for (const value of values) {
    if (!value) continue
    const text = String(value).trim()
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text

    const viMatch = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
    if (viMatch) {
      const [, day, month, year] = viMatch
      return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
    }

    const parsed = new Date(text)
    if (!Number.isNaN(parsed.getTime())) {
      const year = parsed.getFullYear()
      const month = String(parsed.getMonth() + 1).padStart(2, '0')
      const day = String(parsed.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }
  }
  return ''
}

function legacyDraft(serverData) {
  const vi = loadLegacySiteInfo('vi') || {}
  const en = loadLegacySiteInfo('en') || {}
  const shared = (key) => vi[key] || en[key] || serverData[key] || ''

  return {
    ...EMPTY_DATA,
    ...serverData,
    service_name_vi: vi.service_name || serverData.service_name_vi,
    service_name_en: en.service_name || serverData.service_name_en,
    operator_name: shared('operator_name'),
    address_vi: vi.address || serverData.address_vi,
    address_en: en.address || serverData.address_en,
    support_email: shared('support_email'),
    privacy_email: shared('privacy_email'),
    phone: shared('phone'),
    support_hours_vi: vi.support_hours || serverData.support_hours_vi,
    support_hours_en: en.support_hours || serverData.support_hours_en,
    response_time_vi: vi.response_time || serverData.response_time_vi,
    response_time_en: en.response_time || serverData.response_time_en,
    effective_date: normalizeLegacyDate(
      vi.effective_date,
      en.effective_date,
      serverData.effective_date,
    ),
  }
}

function Field({ label, children, className = '' }) {
  return (
    <label className={`block text-sm font-medium text-gray-700 ${className}`}>
      {label}
      {children}
    </label>
  )
}

export function SiteInfoSettings() {
  const { t } = useTranslation()
  const [language, setLanguage] = useState('vi')
  const [data, setData] = useState(EMPTY_DATA)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const response = await siteInfoAPI.getAdmin()
        if (!active) return
        const next = response.data.configured
          ? { ...EMPTY_DATA, ...response.data }
          : legacyDraft(response.data)
        setData(next)
      } catch {
        if (active) setMessage({ type: 'error', text: t('admin.siteInfo.loadError') })
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [t])

  const set = (key, value) => {
    setData(current => ({ ...current, [key]: value }))
    setMessage(null)
  }

  const handleSubmit = async event => {
    event.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const payload = {
        ...data,
        support_email: data.support_email || null,
        privacy_email: data.privacy_email || null,
        effective_date: data.effective_date || null,
      }
      delete payload.configured
      delete payload.updated_at
      delete payload.updated_by
      const response = await siteInfoAPI.updateAdmin(payload)
      setData({ ...EMPTY_DATA, ...response.data })
      setMessage({ type: 'success', text: t('admin.siteInfo.saveSuccess') })
      window.dispatchEvent(new CustomEvent(SITE_INFO_UPDATED_EVENT))
    } catch (error) {
      const detail = error.response?.data?.detail
      setMessage({
        type: 'error',
        text: typeof detail === 'string' ? detail : t('admin.siteInfo.saveError'),
      })
    } finally {
      setSaving(false)
    }
  }

  const localized = suffix => `${suffix}_${language}`

  return (
    <section className="mb-8 rounded-lg border border-gray-200 bg-white p-5" aria-labelledby="site-info-settings-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id="site-info-settings-title" className="text-base font-semibold text-gray-900">
            {t('admin.siteInfo.title')}
          </h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-gray-500">
            {t('admin.siteInfo.description')}
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1" role="group" aria-label={t('admin.siteInfo.language')}>
          {['vi', 'en'].map(option => (
            <button
              key={option}
              type="button"
              onClick={() => setLanguage(option)}
              className={`px-3 py-1.5 text-xs font-semibold uppercase transition-colors ${
                language === option ? 'rounded-md bg-primary text-white' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-10">
          <div className="h-7 w-7 animate-spin rounded-full border-b-2 border-primary" />
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-6 space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('admin.siteInfo.serviceName')}>
              <input
                required
                maxLength={200}
                value={data[localized('service_name')] || ''}
                onChange={event => set(localized('service_name'), event.target.value)}
                className={inputClassName}
              />
            </Field>
            <Field label={t('admin.siteInfo.operatorName')}>
              <input
                maxLength={255}
                value={data.operator_name || ''}
                onChange={event => set('operator_name', event.target.value)}
                className={inputClassName}
              />
            </Field>
          </div>

          <Field label={t('admin.siteInfo.address')}>
            <textarea
              rows={2}
              maxLength={2000}
              value={data[localized('address')] || ''}
              onChange={event => set(localized('address'), event.target.value)}
              className={`${inputClassName} resize-y`}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('admin.siteInfo.supportEmail')}>
              <input
                type="email"
                value={data.support_email || ''}
                onChange={event => set('support_email', event.target.value)}
                className={inputClassName}
                placeholder="support@example.com"
              />
            </Field>
            <Field label={t('admin.siteInfo.privacyEmail')}>
              <input
                type="email"
                value={data.privacy_email || ''}
                onChange={event => set('privacy_email', event.target.value)}
                className={inputClassName}
                placeholder="privacy@example.com"
              />
            </Field>
            <Field label={t('admin.siteInfo.phone')}>
              <input
                type="tel"
                maxLength={50}
                value={data.phone || ''}
                onChange={event => set('phone', event.target.value)}
                className={inputClassName}
              />
            </Field>
            <Field label={t('admin.siteInfo.effectiveDate')}>
              <input
                type="date"
                value={data.effective_date || ''}
                onChange={event => set('effective_date', event.target.value)}
                className={inputClassName}
              />
            </Field>
          </div>

          <Field label={t('admin.siteInfo.supportHours')}>
            <input
              maxLength={255}
              value={data[localized('support_hours')] || ''}
              onChange={event => set(localized('support_hours'), event.target.value)}
              className={inputClassName}
            />
          </Field>

          <Field label={t('admin.siteInfo.responseTime')}>
            <textarea
              rows={2}
              maxLength={2000}
              value={data[localized('response_time')] || ''}
              onChange={event => set(localized('response_time'), event.target.value)}
              className={`${inputClassName} resize-y`}
            />
          </Field>

          {message && (
            <p className={`border px-3 py-2 text-sm ${
              message.type === 'success'
                ? 'border-green-200 bg-green-50 text-green-700'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}>
              {message.text}
            </p>
          )}

          <button
            type="submit"
            disabled={saving}
            className="bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-600 disabled:cursor-wait disabled:opacity-60"
          >
            {saving ? t('app.saving') : t('admin.siteInfo.save')}
          </button>
        </form>
      )}
    </section>
  )
}
