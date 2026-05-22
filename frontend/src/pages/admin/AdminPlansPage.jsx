import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminAPI } from '../../api/admin'
import { Navbar } from '../../components/layout/Navbar'

const EMPTY_PLAN = { name: '', price_vnd: '', credits: '', features: '', is_recommended: false, is_active: true, sort_order: 0 }

function Toggle({ checked, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${checked ? 'bg-primary' : 'bg-gray-200'}`}
    >
      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : 'translate-x-1'}`} />
    </button>
  )
}

function PlanForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({
      ...form,
      price_vnd: parseInt(form.price_vnd) || 0,
      credits: parseInt(form.credits) || 0,
      sort_order: parseInt(form.sort_order) || 0,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Tên gói</label>
          <input
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            value={form.name}
            onChange={e => set('name', e.target.value)}
            required
            placeholder="VD: Starter"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Giá (VND)</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            value={form.price_vnd}
            onChange={e => set('price_vnd', e.target.value)}
            required min={0}
            placeholder="50000"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Credits</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            value={form.credits}
            onChange={e => set('credits', e.target.value)}
            required min={1}
            placeholder="5"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Thứ tự hiển thị</label>
          <input
            type="number"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            value={form.sort_order}
            onChange={e => set('sort_order', e.target.value)}
          />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Tính năng (mỗi dòng một tính năng)</label>
        <textarea
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 h-28 resize-none"
          value={form.features}
          onChange={e => set('features', e.target.value)}
          placeholder="5 giáo trình / tháng&#10;Tối đa 3 chương&#10;Xuất PDF"
        />
      </div>

      <div className="flex gap-6">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <Toggle checked={!!form.is_recommended} onChange={v => set('is_recommended', v)} />
          Phổ biến nhất
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <Toggle checked={!!form.is_active} onChange={v => set('is_active', v)} />
          Hiển thị
        </label>
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-500 disabled:opacity-60 transition-colors"
        >
          {saving ? 'Đang lưu...' : 'Lưu'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
        >
          Hủy
        </button>
      </div>
    </form>
  )
}

export function AdminPlansPage() {
  const [plans, setPlans] = useState([])
  const [bankConfig, setBankConfig] = useState({ bank_name: '', bank_id: '', account_number: '', account_holder: '' })
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null) // plan id or 'new'
  const [saving, setSaving] = useState(false)
  const [bankSaving, setBankSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const flash = (msg, isError = false) => {
    if (isError) setError(msg)
    else setSuccess(msg)
    setTimeout(() => { setError(''); setSuccess('') }, 3000)
  }

  const fetchAll = async () => {
    try {
      const [p, b] = await Promise.all([adminAPI.listPlans(), adminAPI.getBankConfig()])
      setPlans(p.data)
      setBankConfig(b.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll() }, [])

  const savePlan = async (data) => {
    setSaving(true)
    try {
      if (editing === 'new') {
        await adminAPI.createPlan(data)
        flash('Đã tạo gói mới')
      } else {
        await adminAPI.updatePlan(editing, data)
        flash('Đã cập nhật gói')
      }
      setEditing(null)
      fetchAll()
    } catch (e) {
      flash(e.response?.data?.detail || 'Lỗi khi lưu', true)
    } finally {
      setSaving(false)
    }
  }

  const deletePlan = async (id) => {
    if (!window.confirm('Vô hiệu hóa gói này?')) return
    try {
      await adminAPI.deletePlan(id)
      flash('Đã vô hiệu hóa gói')
      fetchAll()
    } catch (e) {
      flash(e.response?.data?.detail || 'Lỗi', true)
    }
  }

  const saveBankConfig = async (e) => {
    e.preventDefault()
    setBankSaving(true)
    try {
      await adminAPI.updateBankConfig(bankConfig)
      flash('Đã cập nhật thông tin ngân hàng')
    } catch (e) {
      flash(e.response?.data?.detail || 'Lỗi', true)
    } finally {
      setBankSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Gói & Ngân hàng</h1>
            <p className="text-sm text-gray-500 mt-1">Quản lý gói nạp tiền và thông tin thanh toán</p>
          </div>
          <Link to="/admin" className="text-sm text-gray-500 hover:text-primary transition-colors">
            ← Quay lại Dashboard
          </Link>
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        ) : (
    <div className="space-y-8">
      {/* Flash messages */}
      {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{error}</div>}
      {success && <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">{success}</div>}

      {/* Bank config card */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-semibold text-gray-800 mb-4">Thông tin ngân hàng</h2>
        <form onSubmit={saveBankConfig} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[
            ['bank_name', 'Tên ngân hàng', 'Vietcombank'],
            ['bank_id', 'Bank ID (VietQR)', 'vietcombank'],
            ['account_number', 'Số tài khoản', '9782832044'],
            ['account_holder', 'Chủ tài khoản', 'Nguyễn Văn A'],
          ].map(([key, label, placeholder]) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                value={bankConfig[key] || ''}
                onChange={e => setBankConfig(c => ({ ...c, [key]: e.target.value }))}
                placeholder={placeholder}
              />
            </div>
          ))}
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={bankSaving}
              className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-500 disabled:opacity-60 transition-colors"
            >
              {bankSaving ? 'Đang lưu...' : 'Cập nhật thông tin ngân hàng'}
            </button>
          </div>
        </form>
      </div>

      {/* Plans list */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-gray-800">Quản lý gói</h2>
          {editing !== 'new' && (
            <button
              onClick={() => setEditing('new')}
              className="px-3 py-1.5 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-500 transition-colors"
            >
              + Thêm gói
            </button>
          )}
        </div>

        {editing === 'new' && (
          <div className="mb-6 p-4 bg-gray-50 rounded-xl border border-gray-100">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">Thêm gói mới</h3>
            <PlanForm initial={EMPTY_PLAN} onSave={savePlan} onCancel={() => setEditing(null)} saving={saving} />
          </div>
        )}

        <div className="space-y-3">
          {plans.map((plan) => (
            <div key={plan.id} className={`rounded-xl border p-4 ${!plan.is_active ? 'opacity-50 bg-gray-50' : 'bg-white border-gray-200'}`}>
              {editing === plan.id ? (
                <div className="p-2">
                  <PlanForm
                    initial={{ ...plan, features: plan.features || '' }}
                    onSave={savePlan}
                    onCancel={() => setEditing(null)}
                    saving={saving}
                  />
                </div>
              ) : (
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-gray-900">{plan.name}</span>
                      {plan.is_recommended && (
                        <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">Phổ biến</span>
                      )}
                      {!plan.is_active && (
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">Ẩn</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-0.5">
                      {plan.price_vnd.toLocaleString('vi-VN')}₫ · {plan.credits} credits · sort: {plan.sort_order}
                    </p>
                  </div>
                  <div className="flex gap-2 flex-shrink-0">
                    <button
                      onClick={() => setEditing(plan.id)}
                      className="px-3 py-1.5 text-xs border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      Sửa
                    </button>
                    <button
                      onClick={() => deletePlan(plan.id)}
                      className="px-3 py-1.5 text-xs border border-red-200 text-red-500 rounded-lg hover:bg-red-50 transition-colors"
                    >
                      Xóa
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {plans.length === 0 && !editing && (
            <p className="text-sm text-gray-400 text-center py-6">Chưa có gói nào. Nhấn "+ Thêm gói" để bắt đầu.</p>
          )}
        </div>
      </div>
    </div>
        )}
      </div>
    </div>
  )
}
