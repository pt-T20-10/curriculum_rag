export function ProgressBar({ value, statusText }) {
  return (
    <div className="mb-6">
      <div className="w-full bg-gray-200 rounded-full h-2.5">
        <div 
          className="bg-gradient-to-r from-blue-400 to-primary h-2.5 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(value * 100, 100)}%` }}
        />
      </div>
      {statusText && (
        <p className="text-sm text-gray-600 mt-2" 
           dangerouslySetInnerHTML={{ __html: statusText }} 
        />
      )}
    </div>
  )
}