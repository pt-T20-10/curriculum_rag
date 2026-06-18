import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { configAPI } from '../../api/config'
import { translateConfigGroup, translateConfigParam } from '../../utils/configTranslations'

// ---------------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------------
function Spinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------
function Tooltip({ text }) {
  const [show, setShow] = useState(false)
  return (
    <span className="relative inline-block ml-1">
      <button
        type="button"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        className="text-gray-400 hover:text-gray-600 transition-colors"
        tabIndex={-1}
      >
        <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
      </button>
      {show && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-56 px-3 py-2 text-xs text-white bg-gray-800 rounded-lg shadow-lg pointer-events-none">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
        </div>
      )}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Batch save confirmation modal — shows all pending changes at once
// ---------------------------------------------------------------------------
function SaveConfirmModal({ changes, onConfirm, onCancel }) {
  const { t } = useTranslation()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-shrink-0 w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center">
            <svg className="w-5 h-5 text-amber-600" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
          <div>
            <h3 className="text-base font-semibold text-gray-900">{t('settings.confirmSaveTitle')}</h3>
            <p className="text-xs text-gray-500 mt-0.5">{t('settings.confirmSaveCount', { count: changes.length })}</p>
          </div>
        </div>

        {/* Change summary table */}
        <div className="border border-gray-200 rounded-lg overflow-hidden mb-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-3 py-2 font-medium text-gray-600">{t('settings.param')}</th>
                <th className="text-left px-3 py-2 font-medium text-gray-600">{t('settings.oldValue')}</th>
                <th className="text-left px-3 py-2 font-medium text-gray-600">{t('settings.newValue')}</th>
              </tr>
            </thead>
            <tbody>
              {changes.map(c => (
                <tr key={c.key} className="border-b border-gray-100 last:border-0">
                  <td className="px-3 py-2">
                    <p className="font-medium text-gray-700">{c.label}</p>
                    <code className="text-gray-400 font-mono">{c.key}</code>
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-500">{String(c.oldValue)}</td>
                  <td className="px-3 py-2 font-mono text-green-700 font-semibold">{String(c.newValue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-5">
          {t('settings.saveWarning')}
        </p>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            {t('settings.cancelEdit')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="flex-1 px-4 py-2 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-blue-600 transition-colors"
          >
            {t('settings.confirmSave', { count: changes.length })}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Reset-all confirmation modal
// ---------------------------------------------------------------------------
function ResetAllModal({ onConfirm, onCancel }) {
  const { t } = useTranslation()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6">
        <h3 className="text-base font-semibold text-gray-900 mb-3">{t('settings.resetTitle')}</h3>
        <p className="text-sm text-gray-500 mb-6">
          {t('settings.resetText')}
        </p>
        <div className="flex gap-3">
          <button type="button" onClick={onCancel}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
            {t('app.cancel')}
          </button>
          <button type="button" onClick={onConfirm}
            className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-semibold hover:bg-red-700 transition-colors">
            {t('settings.resetAll')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Field badges
// ---------------------------------------------------------------------------
function FieldBadge({ isModified, isPending }) {
  const { t } = useTranslation()

  if (isPending) return (
    <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-medium">{t('app.unsaved')}</span>
  )
  if (isModified) return (
    <span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-medium">{t('app.saved')}</span>
  )
  return null
}

// ---------------------------------------------------------------------------
// Single parameter field — no confirm modal, just free editing
// ---------------------------------------------------------------------------
function ParamField({ param, pendingValue, savedValue, defaultValue, onChange, onReset, disabled }) {
  const { t } = useTranslation()
  const effectiveValue = pendingValue !== undefined ? pendingValue
    : savedValue !== undefined ? savedValue
    : defaultValue

  const isModified = savedValue !== undefined && savedValue !== defaultValue
  const isPending = pendingValue !== undefined && pendingValue !== (savedValue !== undefined ? savedValue : defaultValue)

  const borderClass = disabled
    ? 'border-gray-200 bg-gray-50'
    : isPending
    ? 'border-amber-400 ring-1 ring-amber-200'
    : isModified
    ? 'border-blue-400 ring-1 ring-blue-100'
    : 'border-gray-300'

  const commonCls = `w-full px-3 py-2 rounded-lg text-sm border focus:outline-none focus:ring-2 focus:ring-primary ${borderClass}`

  const renderInput = () => {
    if (disabled) {
      return (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
          </svg>
          <span className="font-mono">{String(effectiveValue)}</span>
          <span className="text-xs italic">({t('settings.adminOnly')})</span>
        </div>
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
          onChange={e => onChange(parseInt(e.target.value, 10))}
          className={commonCls} placeholder={String(defaultValue)} />
      )
    }

    if (param.type === 'float') {
      return (
        <input type="number" value={effectiveValue} min={param.min} max={param.max} step={0.01}
          onChange={e => onChange(parseFloat(e.target.value))}
          className={commonCls} placeholder={String(defaultValue)} />
      )
    }

    return (
      <input type="text" value={effectiveValue} onChange={e => onChange(e.target.value)}
        className={commonCls} placeholder={String(defaultValue)} />
    )
  }

  const showReset = (isModified || isPending) && !disabled

  return (
    <div className="mb-5">
      <div className="flex items-center gap-2 mb-1">
        <code className="text-xs font-mono text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">{param.key}</code>
        <span className="text-sm font-medium text-gray-700">{param.label}</span>
        <Tooltip text={param.description} />
        <FieldBadge isModified={isModified} isPending={isPending} />
        {showReset && (
          <button type="button" onClick={onReset}
            className="ml-auto text-xs text-gray-400 hover:text-red-500 transition-colors flex items-center gap-1"
            title={t('settings.restoreDefault')}>
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            {t('settings.restore')}
          </button>
        )}
      </div>
      {param.min != null && param.max != null && param.type !== 'bool' && (
        <p className="text-xs text-gray-400 mb-1">
          {t('settings.range', { min: param.min, max: param.max, defaultValue: String(defaultValue) })}
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

const GROUP_ORDER = ['rag', 'generation', 'ingestion', 'domain_caps']

// ---------------------------------------------------------------------------
// Main AdvancedSettings component
// ---------------------------------------------------------------------------
export function AdvancedSettings() {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)

  const [registry, setRegistry] = useState(null)
  const [savedOverrides, setSavedOverrides] = useState({})
  const [pending, setPending] = useState({})           // unsaved edits

  const [showSaveConfirm, setShowSaveConfirm] = useState(false)
  const [showResetAll, setShowResetAll] = useState(false)

  const [saveSuccess, setSaveSuccess] = useState(false)
  const [apiError, setApiError] = useState('')

  const load = useCallback(async () => {
    await Promise.resolve()
    setLoading(true)
    try {
      const [regRes, overridesRes] = await Promise.all([
        configAPI.getRegistry(),
        configAPI.getUserOverrides(),
      ])
      setRegistry(regRes.data)
      setSavedOverrides(overridesRes.data.overrides || {})
      setPending({})
    } catch {
      setApiError(t('settings.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (!expanded || registry) return undefined
    const timer = setTimeout(() => { load() }, 0)
    return () => clearTimeout(timer)
  }, [expanded, registry, load])

  const getDefault = (key) => registry?.parameters?.[key]?.default

  const handleChange = (key, newValue) => {
    const savedVal = savedOverrides[key]
    const defaultVal = getDefault(key)
    const baseline = savedVal !== undefined ? savedVal : defaultVal

    if (newValue === baseline) {
      // reverting to current saved/default — remove from pending
      setPending(prev => { const n = { ...prev }; delete n[key]; return n })
    } else {
      setPending(prev => ({ ...prev, [key]: newValue }))
    }
  }

  const handleReset = (key) => {
    const defaultVal = getDefault(key)
    if (savedOverrides[key] !== undefined) {
      // field has a saved override → queue its removal by setting to default
      setPending(prev => ({ ...prev, [key]: defaultVal }))
    } else {
      // field only has a pending edit → discard the pending edit
      setPending(prev => { const n = { ...prev }; delete n[key]; return n })
    }
  }

  // Build the list of changes to display in the confirm modal
  const buildChangeSummary = () => {
    if (!registry) return []
    return Object.entries(pending).map(([key, newValue]) => {
      const param = registry.parameters[key]
      const translatedParam = translateConfigParam(param, t)
      const oldValue = savedOverrides[key] !== undefined ? savedOverrides[key] : getDefault(key)
      return { key, label: translatedParam?.label ?? key, oldValue, newValue }
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
      const toSave = { ...savedOverrides }
      for (const [key, val] of Object.entries(pending)) {
        const defaultVal = getDefault(key)
        if (val === defaultVal) {
          delete toSave[key]       // resetting to default → remove override
        } else {
          toSave[key] = val
        }
      }
      const res = await configAPI.saveUserOverrides(toSave)
      setSavedOverrides(res.data.overrides || {})
      setPending({})
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (e) {
      const detail = e.response?.data?.detail
      setApiError(typeof detail === 'object' ? JSON.stringify(detail) : (detail || t('settings.saveError')))
    } finally {
      setSaving(false)
    }
  }

  const handleResetAll = async () => {
    setShowResetAll(false)
    setResetting(true)
    try {
      await configAPI.resetUserOverrides()
      setSavedOverrides({})
      setPending({})
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch {
      setApiError(t('settings.resetError'))
    } finally {
      setResetting(false)
    }
  }

  const pendingCount = Object.keys(pending).length
  const hasSavedOverrides = Object.keys(savedOverrides).length > 0

  const groupedParams = (groupKey) => {
    if (!registry) return []
    return Object.values(registry.parameters).filter(p => p.group === groupKey)
  }

  return (
    <div className="mt-6">
      <div className="border border-gray-200 rounded-xl overflow-hidden bg-white shadow-sm">
        {/* Accordion header */}
        <button type="button" onClick={() => setExpanded(e => !e)}
          className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors">
          <div className="text-left">
            <p className="font-semibold text-gray-800">
              {t('settings.title')}{' '}
              <span className="text-xs font-normal text-gray-500 ml-1 bg-gray-100 px-2 py-0.5 rounded">{t('settings.developerMode')}</span>
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              {t('settings.description')}
            </p>
          </div>
          <svg className={`w-5 h-5 text-gray-400 transition-transform duration-200 flex-shrink-0 ml-4 ${expanded ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {expanded && (
          <div className="border-t border-gray-100 px-5 py-5">
            {/* Warning banner — shown once on expand */}
            <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-5">
              <svg className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <p className="text-xs text-amber-800">
                <span className="font-semibold">{t('settings.warningTitle')}</span> {t('settings.warningText')}
              </p>
            </div>

            {loading && <Spinner />}

            {!loading && registry && (
              <>
                {GROUP_ORDER.map(groupKey => {
                  const group = registry.groups[groupKey]
                  if (!group) return null
                  const translatedGroup = translateConfigGroup(groupKey, group, t)
                  const params = groupedParams(groupKey)
                  if (params.length === 0) return null
                  return (
                    <GroupAccordion key={groupKey} title={translatedGroup.label} description={translatedGroup.description}
                      defaultOpen={groupKey === 'rag'}>
                      {params.map(param => {
                        const translatedParam = translateConfigParam(param, t)
                        return (
                        <ParamField
                          key={param.key}
                          param={translatedParam}
                          pendingValue={pending[param.key]}
                          savedValue={savedOverrides[param.key]}
                          defaultValue={param.default}
                          onChange={(val) => handleChange(param.key, val)}
                          onReset={() => handleReset(param.key)}
                          disabled={param.admin_only}
                        />
                        )
                      })}
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
                      {t('settings.saveSuccess')}
                    </p>
                  </div>
                )}

                {/* Footer actions */}
                <div className="flex items-center justify-between pt-3 mt-2 border-t border-gray-100">
                  <button type="button" onClick={() => setShowResetAll(true)}
                    disabled={resetting || !hasSavedOverrides}
                    className="text-sm text-gray-400 hover:text-red-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                    {resetting ? t('app.processing') : t('settings.resetButton')}
                  </button>
                  <div className="flex items-center gap-3">
                    {pendingCount > 0 && (
                      <span className="text-xs text-amber-600 font-medium">
                        {t('settings.pendingCount', { count: pendingCount })}
                      </span>
                    )}
                    <button type="button" onClick={handleSaveClick}
                      disabled={saving || pendingCount === 0}
                      className={`px-5 py-2 rounded-lg text-sm font-semibold transition-colors ${
                        pendingCount > 0
                          ? 'bg-primary text-white hover:bg-blue-600'
                          : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                      }`}>
                      {saving ? t('settings.saving') : t('settings.saveButton')}
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Batch save confirm modal */}
      {showSaveConfirm && (
        <SaveConfirmModal
          changes={buildChangeSummary()}
          onConfirm={handleSaveConfirmed}
          onCancel={() => setShowSaveConfirm(false)}
        />
      )}

      {showResetAll && (
        <ResetAllModal onConfirm={handleResetAll} onCancel={() => setShowResetAll(false)} />
      )}
    </div>
  )
}
