import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FiAlertCircle, FiCheckCircle, FiSend } from 'react-icons/fi'
import { supportAPI } from '../../api/support'

const EMPTY_FORM = {
  name: '',
  email: '',
  subject: '',
  description: '',
  website: '',
}

const inputClassName =
  'mt-1.5 w-full border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-blue-100'

export function SupportRequestForm({ language }) {
  const { t } = useTranslation()
  const [form, setForm] = useState(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)

  const setField = (key, value) => {
    setForm(current => ({ ...current, [key]: value }))
    if (result) setResult(null)
  }

  const handleSubmit = async event => {
    event.preventDefault()
    setSubmitting(true)
    setResult(null)

    try {
      await supportAPI.sendRequest({
        ...form,
        ui_language: language,
      })
      setForm(current => ({ ...EMPTY_FORM, name: current.name, email: current.email }))
      setResult({ type: 'success', key: 'supportForm.success' })
    } catch (error) {
      const status = error.response?.status
      const key = status === 429
        ? 'supportForm.errors.rateLimited'
        : status === 422
          ? 'supportForm.errors.invalid'
          : status === 503
            ? 'supportForm.errors.unavailable'
            : 'supportForm.errors.generic'
      setResult({ type: 'error', key })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section id="support-request">
      <h2 className="text-xl font-bold text-gray-950">{t('supportForm.title')}</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
        {t('supportForm.description')}
      </p>

      <form className="mt-7 max-w-2xl space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="text-sm font-medium text-gray-800">
            {t('supportForm.name')}
            <input
              type="text"
              required
              minLength={2}
              maxLength={100}
              autoComplete="name"
              value={form.name}
              onChange={event => setField('name', event.target.value)}
              placeholder={t('supportForm.placeholders.name')}
              className={inputClassName}
            />
          </label>
          <label className="text-sm font-medium text-gray-800">
            {t('supportForm.email')}
            <input
              type="email"
              required
              maxLength={254}
              autoComplete="email"
              value={form.email}
              onChange={event => setField('email', event.target.value)}
              placeholder={t('supportForm.placeholders.email')}
              className={inputClassName}
            />
          </label>
        </div>

        <label className="block text-sm font-medium text-gray-800">
          {t('supportForm.subject')}
          <input
            type="text"
            required
            minLength={3}
            maxLength={150}
            value={form.subject}
            onChange={event => setField('subject', event.target.value)}
            placeholder={t('supportForm.placeholders.subject')}
            className={inputClassName}
          />
        </label>

        <label className="block text-sm font-medium text-gray-800">
          {t('supportForm.issue')}
          <textarea
            required
            minLength={10}
            maxLength={5000}
            rows={7}
            value={form.description}
            onChange={event => setField('description', event.target.value)}
            placeholder={t('supportForm.placeholders.issue')}
            className={`${inputClassName} resize-y`}
          />
          <span className="mt-1 block text-right text-xs text-gray-400">
            {t('supportForm.characterCount', { count: form.description.length })}
          </span>
        </label>

        <label className="absolute -left-[10000px] top-auto h-px w-px overflow-hidden" aria-hidden="true">
          Website
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={form.website}
            onChange={event => setField('website', event.target.value)}
          />
        </label>

        <p className="text-xs leading-5 text-gray-500">{t('supportForm.privacyNote')}</p>

        {result && (
          <div
            role="status"
            aria-live="polite"
            className={`flex items-start gap-2 border px-4 py-3 text-sm ${
              result.type === 'success'
                ? 'border-green-200 bg-green-50 text-green-800'
                : 'border-red-200 bg-red-50 text-red-800'
            }`}
          >
            {result.type === 'success' ? (
              <FiCheckCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            ) : (
              <FiAlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            )}
            <span>{t(result.key)}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex min-h-11 items-center justify-center gap-2 bg-primary px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60"
        >
          <FiSend className="h-4 w-4" aria-hidden="true" />
          {submitting ? t('supportForm.sending') : t('supportForm.submit')}
        </button>
      </form>
    </section>
  )
}
