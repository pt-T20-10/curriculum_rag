import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FiAlertCircle, FiCheckCircle, FiTrash2 } from 'react-icons/fi'
import { accountDeletionAPI } from '../../api/accountDeletion'
import { useAuth } from '../../context/AuthContext'

const inputClassName =
  'mt-1.5 w-full border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100 disabled:text-gray-500'

const REASONS = [
  '',
  'no_longer_use',
  'privacy_concerns',
  'switching_service',
  'poor_experience',
  'other',
]

export function AccountDeletionRequestForm({ language }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [email, setEmail] = useState('')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [website, setWebsite] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const accountEmail = user?.email || email

  const clearResult = () => {
    if (result) setResult(null)
  }

  const handleSubmit = async event => {
    event.preventDefault()
    setSubmitting(true)
    setResult(null)
    try {
      await accountDeletionAPI.sendRequest({
        email: accountEmail,
        reason,
        notes,
        website,
        ui_language: language,
      })
      setReason('')
      setNotes('')
      setResult({ type: 'success', key: 'accountDeletionForm.success' })
    } catch (error) {
      const status = error.response?.status
      const key = status === 429
        ? 'accountDeletionForm.errors.rateLimited'
        : status === 422
          ? 'accountDeletionForm.errors.invalid'
          : status === 503
            ? 'accountDeletionForm.errors.unavailable'
            : 'accountDeletionForm.errors.generic'
      setResult({ type: 'error', key })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section id="account-deletion-request">
      <div className="border-l-4 border-amber-500 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
        <p className="font-semibold">{t('accountDeletionForm.warningTitle')}</p>
        <p>{t('accountDeletionForm.warningText')}</p>
      </div>

      <h2 className="mt-8 text-xl font-bold text-gray-950">{t('accountDeletionForm.title')}</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
        {t('accountDeletionForm.description')}
      </p>

      <form className="mt-7 max-w-2xl space-y-5" onSubmit={handleSubmit}>
        <label className="block text-sm font-medium text-gray-800">
          {t('accountDeletionForm.email')}
          <input
            type="email"
            required
            maxLength={254}
            autoComplete="email"
            readOnly={Boolean(user)}
            disabled={Boolean(user)}
            value={accountEmail}
            onChange={event => { setEmail(event.target.value); clearResult() }}
            placeholder={t('accountDeletionForm.placeholders.email')}
            className={inputClassName}
          />
          {user && (
            <span className="mt-1.5 block text-xs text-gray-500">
              {t('accountDeletionForm.authenticatedHint')}
            </span>
          )}
        </label>

        <label className="block text-sm font-medium text-gray-800">
          {t('accountDeletionForm.reason')}
          <select
            value={reason}
            onChange={event => { setReason(event.target.value); clearResult() }}
            className={inputClassName}
          >
            {REASONS.map(value => (
              <option key={value || 'none'} value={value}>
                {t(`accountDeletionForm.reasons.${value || 'none'}`)}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-gray-800">
          {t('accountDeletionForm.notes')}
          <textarea
            rows={6}
            maxLength={2000}
            value={notes}
            onChange={event => { setNotes(event.target.value); clearResult() }}
            placeholder={t('accountDeletionForm.placeholders.notes')}
            className={`${inputClassName} resize-y`}
          />
          <span className="mt-1 block text-right text-xs text-gray-400">
            {t('accountDeletionForm.characterCount', { count: notes.length })}
          </span>
        </label>

        <label className="absolute -left-[10000px] top-auto h-px w-px overflow-hidden" aria-hidden="true">
          Website
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={event => setWebsite(event.target.value)}
          />
        </label>

        <p className="text-xs leading-5 text-gray-500">{t('accountDeletionForm.privacyNote')}</p>

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
          disabled={submitting || !accountEmail}
          className="inline-flex min-h-11 items-center justify-center gap-2 bg-red-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-red-700 disabled:cursor-wait disabled:opacity-60"
        >
          <FiTrash2 className="h-4 w-4" aria-hidden="true" />
          {submitting ? t('accountDeletionForm.sending') : t('accountDeletionForm.submit')}
        </button>
      </form>
    </section>
  )
}
