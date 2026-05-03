export function WorkflowCard({ stage, status, message }) {
  const icons = {
    ingestion: '🔍',
    planner: '📋',
    publisher: '📦',
  }
  
  const statusClasses = {
    completed: 'border-l-4 border-l-green-500 bg-green-50',
    active: 'border-l-4 border-l-blue-500 bg-blue-50 shadow-lg',
    pending: 'border-l-4 border-l-gray-300 bg-gray-50 opacity-60',
  }
  
  const badgeClasses = {
    completed: 'bg-green-100 text-green-800',
    active: 'bg-blue-100 text-blue-800 border border-blue-300',
    pending: 'bg-gray-100 text-gray-600',
  }
  
  const badgeText = {
    completed: '✓ Hoàn tất',
    active: '⏳ Đang xử lý',
    pending: '⏸️ Chờ xử lý',
  }

  return (
    <div className={`p-4 rounded-lg border ${statusClasses[status]} mb-3`}>
      <div className="flex justify-between items-center">
        <div>
          <span className="text-xl mr-2">{icons[stage]}</span>
          <span className="text-gray-600 text-sm">{message}</span>
        </div>
        <span className={`px-3 py-1 rounded-full text-xs font-semibold ${badgeClasses[status]}`}>
          {badgeText[status]}
        </span>
      </div>
    </div>
  )
}