import { useTranslation } from 'react-i18next'

export function PlanCard({ plan, onSelect }) {
  const { i18n, t } = useTranslation()
  const locale = i18n.resolvedLanguage === 'en' ? 'en-US' : 'vi-VN'
  const price = plan.price_vnd.toLocaleString(locale) + '₫'

  return (
    <div
      className={`relative rounded-2xl p-6 flex flex-col transition-all duration-300 hover:-translate-y-1 cursor-pointer ${
        plan.is_recommended
          ? 'bg-primary text-white shadow-2xl shadow-primary/30 border-2 border-primary scale-[1.02]'
          : 'bg-white border border-gray-200 hover:border-primary/40 hover:shadow-lg text-gray-900'
      }`}
      onClick={() => onSelect(plan)}
    >
      {plan.is_recommended && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-amber-400 text-gray-900 text-xs font-bold px-3 py-0.5 rounded-full uppercase tracking-wide shadow">
          {t('topup.recommended')}
        </div>
      )}

      <div className="mb-4">
        <h3 className={`text-lg font-bold mb-1 ${plan.is_recommended ? 'text-white' : 'text-gray-900'}`}>
          {plan.name}
        </h3>
        <div className={`text-2xl font-extrabold ${plan.is_recommended ? 'text-white' : 'text-primary'}`}>
          {price}
        </div>
        <div className={`text-sm mt-1 ${plan.is_recommended ? 'text-white/80' : 'text-gray-500'}`}>
          {plan.credits.toLocaleString(locale)} credits
        </div>
      </div>

      <ul className="space-y-2 flex-1 mb-5">
        {plan.features.map((feat, i) => (
          <li key={i} className="flex items-start gap-2">
            <svg
              className={`w-4 h-4 flex-shrink-0 mt-0.5 ${plan.is_recommended ? 'text-white/80' : 'text-primary'}`}
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                clipRule="evenodd"
              />
            </svg>
            <span className={`text-sm ${plan.is_recommended ? 'text-white/90' : 'text-gray-600'}`}>{feat}</span>
          </li>
        ))}
      </ul>

      <button
        onClick={(e) => { e.stopPropagation(); onSelect(plan) }}
        className={`w-full py-2.5 rounded-xl font-semibold text-sm transition-all duration-200 hover:scale-[1.02] active:scale-95 ${
          plan.is_recommended
            ? 'bg-white text-primary hover:bg-gray-50 shadow'
            : 'bg-primary text-white hover:bg-blue-500 shadow-md'
        }`}
      >
        {t('topup.buy')}
      </button>
    </div>
  )
}
