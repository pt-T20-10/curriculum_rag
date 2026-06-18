import { useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { plansAPI } from '../../api/plans'
import { transactionsAPI } from '../../api/transactions'

function CopyButton({ text }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <button
      onClick={copy}
      className="ml-2 px-2 py-0.5 text-xs bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded transition-colors flex-shrink-0"
    >
      {copied ? t('app.copied') : t('app.copy')}
    </button>
  )
}

export function PaymentModal({ plan, onClose, onSuccess }) {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const [step, setStep] = useState('info')   // 'info' | 'qr' | 'done'
  const [bank, setBank] = useState(null)
  const [txnData, setTxnData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // Synchronous guard — useRef prevents double-create even before React re-renders
  const creatingRef = useRef(false)

  // Only fetch bank config on open — no transaction created yet
  useEffect(() => {
    let cancelled = false
    plansAPI.getBankConfig().then(r => { if (!cancelled) setBank(r.data) })
    return () => { cancelled = true }
  }, [])

  // Step 1 → Step 2: create transaction only when user explicitly continues
  const handleContinue = async () => {
    if (creatingRef.current) return
    creatingRef.current = true
    setLoading(true)
    setError('')
    try {
      const r = await transactionsAPI.create(plan.id)
      setTxnData(r.data)
      setStep('qr')
    } catch {
      setError(t('topup.initError'))
      creatingRef.current = false   // allow retry on failure
    } finally {
      setLoading(false)
    }
  }

  // Step 2 → Step 3: transaction already in DB, just confirm intent
  const handleConfirm = () => {
    setStep('done')
    if (onSuccess) onSuccess(txnData)
  }

  const qrUrl = bank && txnData
    ? `https://img.vietqr.io/image/${bank.bank_id}-${bank.account_number}-compact2.png?amount=${txnData.amount_vnd}&addInfo=${encodeURIComponent(txnData.transfer_content)}&accountName=${encodeURIComponent(bank.account_holder)}`
    : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900">{t('topup.payment')}</h2>
            <p className="text-sm text-gray-500">{plan.name} — {plan.price_vnd.toLocaleString(locale)}₫</p>
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5">
          {/* ── Step 1: Plan info confirmation ── */}
          {step === 'info' && (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{error}</div>
              )}

              {/* Plan summary */}
              <div className="bg-gray-50 rounded-xl border border-gray-200 p-4 mb-5 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">{t('topup.plan')}</span>
                  <span className="font-semibold text-gray-900">{plan.name}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">{t('topup.creditsReceived')}</span>
                  <span className="font-semibold text-primary">{plan.credits.toLocaleString(locale)} credits</span>
                </div>
                <div className="border-t border-gray-200 pt-3 flex justify-between text-sm">
                  <span className="text-gray-500">{t('topup.amount')}</span>
                  <span className="font-bold text-gray-900 text-base">{plan.price_vnd.toLocaleString(locale)}₫</span>
                </div>
              </div>

              {/* Features */}
              {plan.features && plan.features.length > 0 && (
                <ul className="mb-5 space-y-1.5">
                  {plan.features.map((f, i) => (
                    <li key={i} className="flex items-center gap-2 text-sm text-gray-600">
                      <svg className="w-4 h-4 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                      {f}
                    </li>
                  ))}
                </ul>
              )}

              <div className="mb-5 p-3 bg-blue-50 border border-blue-200 rounded-lg flex gap-2">
                <svg className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-xs text-blue-700">
                  <Trans i18nKey="topup.continuePaymentHint" components={{ strong: <strong /> }} />
                </p>
              </div>

              <button
                onClick={handleContinue}
                disabled={loading}
                className="w-full py-3 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-blue-500 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
              >
                {loading
                  ? <><span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" /> {t('topup.preparing')}</>
                  : `${t('topup.continuePayment')} →`}
              </button>
            </>
          )}

          {/* ── Step 2: QR + bank details ── */}
          {step === 'qr' && (
            <>
              {/* QR Code */}
              {qrUrl && (
                <div className="flex justify-center mb-5">
                  <img
                    src={qrUrl}
                    alt="VietQR"
                    className="rounded-xl border border-gray-200"
                    style={{ width: 220, height: 220, objectFit: 'contain' }}
                  />
                </div>
              )}

              {/* Bank details */}
              <div className="space-y-3 mb-5">
                <InfoRow label={t('topup.bank')} value={bank?.bank_name} />
                <InfoRow
                  label={t('topup.accountNumber')}
                  value={bank?.account_number}
                  action={<CopyButton text={bank?.account_number || ''} />}
                />
                <InfoRow label={t('topup.accountHolder')} value={bank?.account_holder} />
                <InfoRow label={t('topup.transferAmount')} value={txnData.amount_vnd.toLocaleString(locale) + '₫'} highlight />
                <InfoRow
                  label={t('topup.transferContent')}
                  value={txnData.transfer_content}
                  action={<CopyButton text={txnData.transfer_content} />}
                  mono
                />
              </div>

              {/* Warning */}
              <div className="mb-5 p-3 bg-amber-50 border border-amber-200 rounded-lg flex gap-2">
                <svg className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                </svg>
                <p className="text-xs text-amber-700">
                  <strong>{t('topup.importantNote')}</strong> {t('topup.noteText')}
                </p>
              </div>

              <button
                onClick={handleConfirm}
                className="w-full py-3 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-blue-500 transition-colors"
              >
                {t('topup.transferred')}
              </button>
            </>
          )}

          {/* ── Step 3: Done ── */}
          {step === 'done' && (
            <div className="text-center py-6">
              <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-7 h-7 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-lg font-bold text-gray-900 mb-2">{t('topup.requestRecorded')}</h3>
              <p className="text-sm text-gray-500 mb-6">
                {t('topup.reviewText')}
              </p>
              <button
                onClick={onClose}
                className="px-6 py-2.5 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-blue-500 transition-colors"
              >
                {t('app.close')}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function InfoRow({ label, value, action, highlight, mono }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-sm text-gray-500 flex-shrink-0 w-36">{label}</span>
      <div className="flex items-center gap-1 min-w-0">
        <span
          className={`text-sm font-medium break-all ${highlight ? 'text-primary font-bold' : 'text-gray-900'} ${mono ? 'font-mono' : ''}`}
        >
          {value || '—'}
        </span>
        {action}
      </div>
    </div>
  )
}
