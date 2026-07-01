export function RunningIndicator({
  label,
  description,
  size = 'md',
  tone = 'blue',
  allowHtml = false,
  className = '',
}) {
  const sizes = {
    sm: 'h-4 w-4 border-2',
    md: 'h-6 w-6 border-[3px]',
    lg: 'h-9 w-9 border-4',
  }

  const tones = {
    blue: {
      container: 'border-blue-200 bg-blue-50 text-blue-700',
      spinner: 'border-blue-200 border-t-blue-600',
      description: 'text-blue-600',
    },
    gray: {
      container: 'border-gray-200 bg-gray-50 text-gray-700',
      spinner: 'border-gray-200 border-t-gray-600',
      description: 'text-gray-500',
    },
  }

  const currentTone = tones[tone] || tones.blue

  return (
    <div className={`rounded-lg border px-4 py-3 ${currentTone.container} ${className}`}>
      <div className="flex items-center gap-3">
        <span
          className={`flex-shrink-0 animate-spin rounded-full ${sizes[size] || sizes.md} ${currentTone.spinner}`}
          aria-hidden="true"
        />
        <div className="min-w-0">
          {label && allowHtml ? (
            <div
              className="text-sm font-semibold leading-5"
              dangerouslySetInnerHTML={{ __html: label }}
            />
          ) : label ? (
            <div className="text-sm font-semibold leading-5">
              {label}
            </div>
          ) : null}
          {description && (
            <p className={`mt-0.5 text-xs ${currentTone.description}`}>
              {description}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
