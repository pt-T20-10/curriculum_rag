import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { plansAPI } from '../../api/plans'
import { transactionsAPI } from '../../api/transactions'
import { PlanCard } from './PlanCard'
import { PaymentModal } from './PaymentModal'
import { TransactionHistory } from './TransactionHistory'

export function TopUpTab() {
  const { user, loadUser } = useAuth()
  const [plans, setPlans] = useState([])
  const [transactions, setTransactions] = useState([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [txnLoading, setTxnLoading] = useState(true)
  const [selectedPlan, setSelectedPlan] = useState(null)

  const fetchPlans = async () => {
    try {
      const r = await plansAPI.listActive()
      setPlans(r.data)
    } finally {
      setPlansLoading(false)
    }
  }

  const fetchTransactions = async () => {
    try {
      const r = await transactionsAPI.listMine()
      setTransactions(r.data)
    } finally {
      setTxnLoading(false)
    }
  }

  useEffect(() => {
    fetchPlans()
    fetchTransactions()
  }, [])

  const handlePaymentSuccess = () => {
    setSelectedPlan(null)
    fetchTransactions()
    if (loadUser) loadUser()
  }

  return (
    <div className="space-y-8">
      {/* Balance banner */}
      <div className="bg-gradient-to-r from-primary to-blue-500 rounded-2xl p-6 text-white">
        <p className="text-sm text-white/70 mb-1">Số dư hiện tại</p>
        <div className="flex items-end gap-2">
          <span className="text-4xl font-extrabold">{user?.credits ?? 0}</span>
          <span className="text-lg text-white/80 mb-1">credits</span>
        </div>
        <p className="text-xs text-white/60 mt-2">Mỗi lần tạo giáo trình tốn 1 credit</p>
      </div>

      {/* Plans */}
      <div>
        <h3 className="text-base font-semibold text-gray-800 mb-4">Chọn gói nạp tiền</h3>
        {plansLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" />
          </div>
        ) : plans.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-6">Chưa có gói nào. Liên hệ quản trị viên.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {plans.map((plan) => (
              <PlanCard key={plan.id} plan={plan} onSelect={setSelectedPlan} />
            ))}
          </div>
        )}
      </div>

      {/* Transaction history */}
      <div>
        <h3 className="text-base font-semibold text-gray-800 mb-4">Lịch sử giao dịch</h3>
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <TransactionHistory transactions={transactions} loading={txnLoading} />
        </div>
      </div>

      {/* Payment modal */}
      {selectedPlan && (
        <PaymentModal
          plan={selectedPlan}
          onClose={() => setSelectedPlan(null)}
          onSuccess={handlePaymentSuccess}
        />
      )}
    </div>
  )
}
