import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

const STORAGE_PREFIX = 'deployment-profile-dismissed:'

const severityClasses = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  info: 'border-blue-200 bg-blue-50 text-blue-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  danger: 'border-red-200 bg-red-50 text-red-900',
}

function settingLine(settings = {}) {
  const items = [
    `Chroma: ${settings.CHROMA_MODE || 'unknown'}`,
    `Celery: ${settings.CELERY_POOL || 'unknown'} x ${settings.CELERY_CONCURRENCY || 1}`,
    `Global: ${settings.GENERATION_GLOBAL_CONCURRENCY || 1}`,
    `Per user: ${settings.GENERATION_PER_USER_CONCURRENCY || 1}`,
  ]
  return items.join(' · ')
}

export function DeploymentProfileNotice({ profile, compact = false, showPopup = true }) {
  const [popupOpen, setPopupOpen] = useState(false)

  useEffect(() => {
    if (!showPopup || !profile?.signature) return
    const key = `${STORAGE_PREFIX}${profile.signature}`
    if (window.localStorage.getItem(key) !== '1') {
      setPopupOpen(true)
    }
  }, [profile, showPopup])

  if (!profile) return null

  const cls = severityClasses[profile.severity] || severityClasses.info
  const dismiss = () => {
    if (profile.signature) {
      window.localStorage.setItem(`${STORAGE_PREFIX}${profile.signature}`, '1')
    }
    setPopupOpen(false)
  }

  return (
    <>
      <div className={`mb-6 rounded-xl border px-5 py-4 shadow-sm ${cls}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">{profile.title}</p>
            <p className="mt-1 text-xs opacity-90">{profile.summary}</p>
            {!compact && (
              <p className="mt-2 text-xs font-mono opacity-80">{settingLine(profile.settings)}</p>
            )}
          </div>
          <span className="rounded-md bg-white/70 px-2.5 py-1 text-xs font-semibold">
            {profile.max_parallel_jobs || 1} job song song
          </span>
        </div>
        {!compact && (
          <p className="mt-3 text-xs opacity-90">{profile.recommended_action}</p>
        )}
      </div>

      {popupOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl">
            <p className="text-base font-semibold text-gray-900">{profile.title}</p>
            <p className="mt-2 text-sm text-gray-600">{profile.summary}</p>
            <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-600">
              {settingLine(profile.settings)}
            </div>
            <p className="mt-4 text-sm text-gray-700">{profile.recommended_action}</p>
            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={dismiss}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Đã hiểu
              </button>
              <Link
                to="/admin/config?setup=1"
                onClick={dismiss}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-blue-600"
              >
                Mở cấu hình
              </Link>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
