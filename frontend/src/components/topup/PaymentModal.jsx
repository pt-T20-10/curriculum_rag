import { useEffect, useState } from 'react'
import { plansAPI } from '../../api/plans'
import { transactionsAPI } from '../../api/transactions'

function CopyButton({ text }) {
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
      {copied ? 'Đã sao chép!' : 'Sao chép'}
    </button>
  )
}

export function PaymentModal({ plan, onClose, onSuccess }) {
  const [step, setStep] = useState('qr')       // 'qr' | 'done'
  const [bank, setBank] = useState(null)
  const [txnData, setTxnData] = useState(null) // transaction from backend
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    plansAPI.getBankConfig().then(r => { if (!cancelled) setBank(r.data) })
    // Create the pending transaction immediately so TXN ID is server-generated
    transactionsAPI.create(plan.id).then(r => {
      if (!cancelled) setTxnData(r.data)
    }).catch(() => {
      if (!cancelled) setError('Không thể khởi tạo giao dịch. Vui lòng thử lại.')
    })
    return () => { cancelled = true }
  }, [plan.id])

  const handleConfirm = async () => {
    if (!txnData) return
    setLoading(true)
    setError('')
    try {
      // Transaction already created; just move to done step
      setStep('done')
      if (onSuccess) onSuccess(txnData)
    } catch (e) {
      setError('Có lỗi xảy ra. Vui lòng thử lại.')
    } finally {
      setLoading(false)
    }
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
            <h2 className="text-lg font-bold text-gray-900">Thanh toán</h2>
            <p className="text-sm text-gray-500">{plan.name} — {plan.price_vnd.toLocaleString('vi-VN')}₫</p>
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5">
          {step === 'qr' && (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{error}</div>
              )}

              {!txnData ? (
                <div className="flex justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              ) : (
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
                    <InfoRow label="Ngân hàng" value={bank?.bank_name} />
                    <InfoRow
                      label="Số tài khoản"
                      value={bank?.account_number}
                      action={<CopyButton text={bank?.account_number || ''} />}
                    />
                    <InfoRow label="Chủ tài khoản" value={bank?.account_holder} />
                    <InfoRow label="Số tiền" value={txnData.amount_vnd.toLocaleString('vi-VN') + '₫'} highlight />
                    <InfoRow
                      label="Nội dung chuyển khoản"
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
                      <strong>Lưu ý quan trọng:</strong> Nội dung chuyển khoản phải khớp chính xác, nếu không giao dịch sẽ không được xác nhận.
                    </p>
                  </div>

                  <button
                    onClick={handleConfirm}
                    disabled={loading}
                    className="w-full py-3 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-blue-500 disabled:opacity-60 transition-colors"
                  >
                    {loading ? 'Đang xử lý...' : 'Tôi đã chuyển khoản'}
                  </button>
                </>
              )}
            </>
          )}

          {step === 'done' && (
            <div className="text-center py-6">
              <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-7 h-7 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-lg font-bold text-gray-900 mb-2">Yêu cầu đã được ghi nhận!</h3>
              <p className="text-sm text-gray-500 mb-6">
                Thanh toán của bạn đang được kiểm duyệt. Credits sẽ được cộng trong vòng 24 giờ.
              </p>
              <button
                onClick={onClose}
                className="px-6 py-2.5 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-blue-500 transition-colors"
              >
                Đóng
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
