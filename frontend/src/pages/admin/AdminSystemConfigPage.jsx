import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'
import { configAPI } from '../../api/config'

const MASKED_VALUE = '••••••••'

// ---------------------------------------------------------------------------
// Spinner / Tooltip
// ---------------------------------------------------------------------------
function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
    </div>
  )
}

function Tooltip({ text }) {
  const [show, setShow] = useState(false)
  return (
    <span className="relative inline-block ml-1">
      <button type="button"
        onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}
        className="text-gray-400 hover:text-gray-600 transition-colors" tabIndex={-1}>
        <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
      </button>
      {show && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-60 px-3 py-2 text-xs text-white bg-gray-800 rounded-lg shadow-lg pointer-events-none">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
        </div>
      )}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Batch save confirm modal — shows ALL pending changes with admin warning
// ---------------------------------------------------------------------------
function SaveConfirmModal({ changes, overrideCounts, onConfirm, onCancel }) {
  const totalAffectedUsers = changes.reduce((sum, c) => sum + (overrideCounts[c.key] || 0), 0)
  const displayValue = (change, value) => change.sensitive && value ? MASKED_VALUE : String(value)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
            <svg className="w-5 h-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
          <div>
            <h3 className="text-base font-semibold text-gray-900">Xác nhận thay đổi mặc định hệ thống?</h3>
            <p className="text-xs text-gray-500 mt-0.5">{changes.length} tham số sẽ được cập nhật trên toàn hệ thống</p>
          </div>
        </div>

        {/* Change summary table */}
        <div className="border border-gray-200 rounded-lg overflow-hidden mb-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-3 py-2 font-medium text-gray-600">Tham số</th>
                <th className="text-left px-3 py-2 font-medium text-gray-600">Giá trị cũ</th>
                <th className="text-left px-3 py-2 font-medium text-gray-600">Giá trị mới</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600">Ghi đè người dùng</th>
              </tr>
            </thead>
            <tbody>
              {changes.map(c => (
                <tr key={c.key} className="border-b border-gray-100 last:border-0">
                  <td className="px-3 py-2">
                    <p className="font-medium text-gray-700">{c.label}</p>
                    <code className="text-gray-400 font-mono">{c.key}</code>
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-500">{displayValue(c, c.oldValue)}</td>
                  <td className="px-3 py-2 font-mono text-green-700 font-semibold">{displayValue(c, c.newValue)}</td>
                  <td className="px-3 py-2 text-right">
                    {(overrideCounts[c.key] || 0) > 0
                      ? <span className="text-purple-600 font-medium">{overrideCounts[c.key]}</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Admin warning */}
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-5 text-xs text-red-800 space-y-1">
          <p className="font-semibold">Thay đổi này sẽ ảnh hưởng đến TẤT CẢ người dùng chưa đặt ghi đè cá nhân.</p>
          {totalAffectedUsers > 0 && (
            <p>
              Tổng cộng <strong>{totalAffectedUsers}</strong> ghi đè người dùng hiện có sẽ vẫn được ưu tiên hơn giá trị mới.
            </p>
          )}
        </div>

        <div className="flex gap-3">
          <button type="button" onClick={onCancel}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
            Hủy, tiếp tục chỉnh sửa
          </button>
          <button type="button" onClick={onConfirm}
            className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-semibold hover:bg-red-700 transition-colors">
            Xác nhận thay đổi toàn hệ thống
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Parameter field — free editing, no per-field modal
// ---------------------------------------------------------------------------
function AdminParamField({ param, pendingValue, savedValue, defaultValue, overrideCount, onChange, onReset }) {
  const isMaskedSensitive = param.sensitive && savedValue === MASKED_VALUE && pendingValue === undefined
  const effectiveValue = isMaskedSensitive ? ''
    : pendingValue !== undefined ? pendingValue
    : savedValue !== undefined ? savedValue
    : defaultValue

  const isModified = savedValue !== undefined && savedValue !== defaultValue
  const isPending = pendingValue !== undefined &&
    pendingValue !== (savedValue !== undefined ? savedValue : defaultValue)

  const borderClass = isPending
    ? 'border-amber-400 ring-1 ring-amber-200'
    : isModified
    ? 'border-blue-400 ring-1 ring-blue-100'
    : param.sensitive
    ? 'border-gray-200 bg-gray-50'
    : 'border-gray-300'

  const commonCls = `w-full px-3 py-2 rounded-lg text-sm border focus:outline-none focus:ring-2 focus:ring-primary ${borderClass}`

  const renderInput = () => {
    if (param.sensitive) {
      return (
        <input type="password" value={effectiveValue}
          onChange={e => onChange(e.target.value)}
          placeholder={savedValue === MASKED_VALUE ? 'Đã có giá trị, nhập giá trị mới để thay đổi' : 'Nhập giá trị'}
          className={commonCls} />
      )
    }
    if (param.type === 'bool') {
      return (
        <button type="button" onClick={() => onChange(!effectiveValue)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${effectiveValue ? 'bg-primary' : 'bg-gray-300'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform shadow ${effectiveValue ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      )
    }
    if (param.choices) {
      return (
        <select value={effectiveValue} onChange={e => onChange(e.target.value)} className={commonCls}>
          {param.choices.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      )
    }
    if (param.type === 'int') {
      return (
        <input type="number" value={effectiveValue} min={param.min} max={param.max} step={1}
          onChange={e => onChange(parseInt(e.target.value, 10))} className={commonCls} />
      )
    }
    if (param.type === 'float') {
      return (
        <input type="number" value={effectiveValue} min={param.min} max={param.max} step={0.01}
          onChange={e => onChange(parseFloat(e.target.value))} className={commonCls} />
      )
    }
    return (
      <input type="text" value={effectiveValue} onChange={e => onChange(e.target.value)} className={commonCls} />
    )
  }

  const showReset = isModified || isPending

  return (
    <div className="mb-5">
      <div className="flex items-center flex-wrap gap-2 mb-1">
        <code className="text-xs font-mono text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">{param.key}</code>
        <span className="text-sm font-medium text-gray-700">{param.label}</span>
        <Tooltip text={param.description} />
        {overrideCount > 0 && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-medium">
            {overrideCount} ghi đè người dùng
          </span>
        )}
        {isPending && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-medium">Chưa lưu</span>
        )}
        {isModified && !isPending && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-medium">Đã sửa</span>
        )}
        {showReset && (
          <button type="button" onClick={onReset}
            className="ml-auto text-xs text-gray-400 hover:text-red-500 transition-colors flex items-center gap-1"
            title="Khôi phục về mặc định config.py">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            Khôi phục mặc định
          </button>
        )}
      </div>
      {param.min != null && param.max != null && param.type !== 'bool' && !param.sensitive && (
        <p className="text-xs text-gray-400 mb-1">
          Phạm vi: {param.min} – {param.max}&nbsp;·&nbsp;Mặc định:{' '}
          <span className="font-mono">{String(defaultValue)}</span>
        </p>
      )}
      {renderInput()}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Group accordion
// ---------------------------------------------------------------------------
function GroupAccordion({ title, description, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden mb-4 bg-white">
      <button type="button" onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors">
        <div className="text-left">
          <p className="font-semibold text-gray-800 text-sm">{title}</p>
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
        </div>
        <svg className={`w-5 h-5 text-gray-400 transition-transform duration-200 flex-shrink-0 ml-4 ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && <div className="px-5 pt-4 pb-2 border-t border-gray-100">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Audit log table
// ---------------------------------------------------------------------------
function AuditTable({ entries }) {
  if (entries.length === 0) {
    return <p className="text-sm text-gray-400 text-center py-6">Chưa có thay đổi nào được ghi lại.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-200 text-gray-500">
            <th className="text-left pb-2 pr-3 font-medium">Thời gian</th>
            <th className="text-left pb-2 pr-3 font-medium">Quản trị viên</th>
            <th className="text-left pb-2 pr-3 font-medium">Tham số</th>
            <th className="text-left pb-2 pr-3 font-medium">Giá trị cũ</th>
            <th className="text-left pb-2 font-medium">Giá trị mới</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(entry => (
            <tr key={entry.id} className="border-b border-gray-100 last:border-0">
              <td className="py-2 pr-3 text-gray-500 whitespace-nowrap">
                {new Date(entry.created_at).toLocaleString('vi-VN')}
              </td>
              <td className="py-2 pr-3 text-gray-700 truncate max-w-[140px]">
                {entry.admin_email || `#${entry.admin_id}`}
              </td>
              <td className="py-2 pr-3">
                <code className="font-mono bg-gray-100 px-1 rounded">{entry.key}</code>
              </td>
              <td className="py-2 pr-3 text-gray-500 font-mono">
                {entry.old_value != null
                  ? (() => { try { return JSON.parse(entry.old_value) } catch { return entry.old_value } })()
                  : <span className="italic">—</span>}
              </td>
              <td className="py-2 text-green-700 font-mono">
                {(() => { try { return JSON.parse(entry.new_value) } catch { return entry.new_value } })()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const GROUP_ORDER = ['api_keys', 'rag', 'generation', 'ingestion', 'domain_caps']

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function AdminSystemConfigPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [apiError, setApiError] = useState('')

  const [registry, setRegistry] = useState(null)
  const [systemConfig, setSystemConfig] = useState({})
  const [overrideCounts, setOverrideCounts] = useState({})
  const [auditLog, setAuditLog] = useState([])
  const [pending, setPending] = useState({})

  const [showSaveConfirm, setShowSaveConfirm] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [regRes, sysRes, overRes, auditRes] = await Promise.all([
        configAPI.getRegistry(),
        configAPI.getSystemConfig(),
        configAPI.getOverrideCounts(),
        configAPI.getAuditLog(20),
      ])
      setRegistry(regRes.data)
      setSystemConfig(sysRes.data.config || {})
      const countMap = {}
      for (const item of overRes.data) countMap[item.key] = item.override_count
      setOverrideCounts(countMap)
      setAuditLog(auditRes.data || [])
    } catch {
      setApiError('Không thể tải cấu hình hệ thống.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const getDefault = (key) => registry?.parameters?.[key]?.default

  const handleChange = (param, newValue) => {
    const key = param.key
    const savedVal = systemConfig[key]
    const defaultVal = getDefault(key)
    const baseline = savedVal !== undefined ? savedVal : defaultVal

    if (param.sensitive && savedVal === MASKED_VALUE && newValue === '') {
      setPending(prev => { const n = { ...prev }; delete n[key]; return n })
      return
    }

    if (newValue === baseline) {
      setPending(prev => { const n = { ...prev }; delete n[key]; return n })
    } else {
      setPending(prev => ({ ...prev, [key]: newValue }))
    }
  }

  const handleReset = (key) => {
    const defaultVal = getDefault(key)
    if (systemConfig[key] !== undefined) {
      setPending(prev => ({ ...prev, [key]: defaultVal }))
    } else {
      setPending(prev => { const n = { ...prev }; delete n[key]; return n })
    }
  }

  const buildChangeSummary = () => {
    if (!registry) return []
    return Object.entries(pending).map(([key, newValue]) => {
      const param = registry.parameters[key]
      const oldValue = systemConfig[key] !== undefined ? systemConfig[key] : getDefault(key)
      return { key, label: param?.label ?? key, oldValue, newValue, sensitive: Boolean(param?.sensitive) }
    })
  }

  const handleSaveClick = () => {
    if (Object.keys(pending).length === 0) return
    setShowSaveConfirm(true)
  }

  const handleSaveConfirmed = async () => {
    setShowSaveConfirm(false)
    setApiError('')
    setSaving(true)
    try {
      const sanitizedPending = Object.fromEntries(
        Object.entries(pending).filter(([key, value]) => {
          const param = registry?.parameters?.[key]
          return !(param?.sensitive && value === MASKED_VALUE)
        })
      )
      const res = await configAPI.updateSystemConfig(sanitizedPending)
      setSystemConfig(res.data.config || {})
      setPending({})
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
      const auditRes = await configAPI.getAuditLog(20)
      setAuditLog(auditRes.data || [])
    } catch (e) {
      const detail = e.response?.data?.detail
      setApiError(typeof detail === 'object' ? JSON.stringify(detail) : (detail || 'Không thể lưu.'))
    } finally {
      setSaving(false)
    }
  }

  const pendingCount = Object.keys(pending).length
  const groupedParams = (groupKey) => {
    if (!registry) return []
    return Object.values(registry.parameters).filter(p => p.group === groupKey)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />

      <div className="max-w-4xl mx-auto px-4 py-10">
        <AdminNavigation className="mb-6" />

        {/* Breadcrumb */}
        <div className="mb-6 flex items-center gap-2 text-sm text-gray-500">
          <Link to="/admin" className="hover:text-primary transition-colors">Admin</Link>
          <span>/</span>
          <span className="text-gray-700 font-medium">Cấu hình hệ thống</span>
        </div>

        {/* Header + nav */}
        <div className="mb-8 flex items-start justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Cấu hình hệ thống</h1>
            <p className="text-sm text-gray-500 mt-1 max-w-xl">
              Mặc định hệ thống — Thay đổi ở đây sẽ trở thành mặc định mới cho tất cả người dùng.
              Người dùng vẫn có thể ghi đè trong phần Cài đặt nâng cao của họ.
            </p>
          </div>
        </div>

        {loading && <Spinner />}

        {!loading && registry && (
          <>
            {/* Warning banner */}
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-6">
              <svg className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <p className="text-xs text-red-800">
                <span className="font-semibold">Chú ý:</span> Thay đổi tại đây ảnh hưởng đến tất cả người dùng không có ghi đè cá nhân.
                Xem lại kỹ trước khi lưu. Số <span className="font-semibold text-purple-700">ghi đè người dùng</span> trên mỗi tham số hiển thị số tài khoản đang dùng giá trị riêng.
              </p>
            </div>

            {GROUP_ORDER.map(groupKey => {
              const group = registry.groups[groupKey]
              if (!group) return null
              const params = groupedParams(groupKey)
              if (params.length === 0) return null
              return (
                <GroupAccordion key={groupKey} title={group.label} description={group.description}
                  defaultOpen={groupKey === 'api_keys'}>
                  {params.map(param => (
                    <AdminParamField
                      key={param.key}
                      param={param}
                      pendingValue={pending[param.key]}
                      savedValue={systemConfig[param.key]}
                      defaultValue={param.default}
                      overrideCount={overrideCounts[param.key] || 0}
                      onChange={(val) => handleChange(param, val)}
                      onReset={() => handleReset(param.key)}
                    />
                  ))}
                </GroupAccordion>
              )
            })}

            {apiError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-sm text-red-600">{apiError}</p>
              </div>
            )}

            {saveSuccess && (
              <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
                <p className="text-sm text-green-700">
                  Đã lưu cấu hình hệ thống. Thay đổi có hiệu lực ngay cho tất cả yêu cầu mới.
                </p>
              </div>
            )}

            {/* Sticky save bar */}
            <div className="sticky bottom-6 mt-4">
              <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 shadow-lg flex items-center justify-between">
                <span className="text-sm text-gray-500">
                  {pendingCount > 0
                    ? <span className="text-amber-600 font-medium">{pendingCount} thay đổi chưa lưu</span>
                    : 'Đã lưu tất cả thay đổi'}
                </span>
                <button type="button" onClick={handleSaveClick}
                  disabled={saving || pendingCount === 0}
                  className={`px-6 py-2 rounded-lg text-sm font-semibold transition-colors ${
                    pendingCount > 0
                      ? 'bg-primary text-white hover:bg-blue-600'
                      : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  }`}>
                  {saving ? 'Đang lưu…' : 'Lưu mặc định hệ thống'}
                </button>
              </div>
            </div>

            {/* Audit log */}
            <div className="mt-10">
              <h2 className="text-base font-semibold text-gray-800 mb-3">Nhật ký thay đổi cấu hình</h2>
              <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
                <AuditTable entries={auditLog} />
              </div>
            </div>
          </>
        )}
      </div>

      {/* Batch save confirm modal */}
      {showSaveConfirm && (
        <SaveConfirmModal
          changes={buildChangeSummary()}
          overrideCounts={overrideCounts}
          onConfirm={handleSaveConfirmed}
          onCancel={() => setShowSaveConfirm(false)}
        />
      )}
    </div>
  )
}
