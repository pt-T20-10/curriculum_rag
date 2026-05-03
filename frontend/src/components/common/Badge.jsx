export function StatusBadge({ status }) {
  const styles = {
    pending: 'bg-gray-100 text-gray-800 border border-gray-300',
    generating: 'bg-blue-100 text-blue-800 border border-blue-300',
    completed: 'bg-green-100 text-green-800 border border-green-300',
    failed: 'bg-red-100 text-red-800 border border-red-300',
  }

  const labels = {
    pending: 'Đang chờ',
    generating: 'Đang tạo',
    completed: 'Hoàn thành',
    failed: 'Thất bại',
  }

  return (
    <span className={`
      px-2 py-1 rounded-full text-xs font-medium inline-flex items-center gap-1
      ${styles[status] || styles.pending}
    `}>
      {status === 'generating' && (
        <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12" cy="12" r="10"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {labels[status] || status}
    </span>
  )
}

export function ContentTypeBadge({ type }) {
  const styles = {
    scholarly: 'bg-purple-100 text-purple-800 border border-purple-300',
    technical: 'bg-blue-100 text-blue-800 border border-blue-300',
    practical: 'bg-green-100 text-green-800 border border-green-300',
    lifestyle: 'bg-orange-100 text-orange-800 border border-orange-300',
  }

  const labels = {
    scholarly: '📚 Học thuật',
    technical: '🔧 Kỹ thuật',
    practical: '💼 Thực tiễn',
    lifestyle: '🌱 Đời sống',
  }

  return (
    <span className={`
      px-2 py-1 rounded-full text-xs font-medium
      ${styles[type] || styles.technical}
    `}>
      {labels[type] || type}
    </span>
  )
}
