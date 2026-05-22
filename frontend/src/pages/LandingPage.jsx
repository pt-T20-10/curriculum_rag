import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { loadConfig } from '../utils/landingConfig'
import { plansAPI } from '../api/plans'

// ---------------------------------------------------------------------------
// IntersectionObserver hook — fires once when element enters viewport
// ---------------------------------------------------------------------------
function useInView(threshold = 0.12) {
  const ref = useRef(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setInView(true) },
      { threshold },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [threshold])
  return [ref, inView]
}

// Convenience: wrap children in a div that fades+slides up when it enters view
function FadeUp({ children, delay = 0, className = '' }) {
  const [ref, inView] = useInView()
  return (
    <div
      ref={ref}
      className={`transition-all duration-700 ease-out ${
        inView ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'
      } ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Initials avatar (no external image dependency)
// ---------------------------------------------------------------------------
function InitialsAvatar({ name }) {
  const initials = name
    .split(' ')
    .filter(Boolean)
    .map(w => w[0].toUpperCase())
    .slice(0, 2)
    .join('')
  const palette = [
    'bg-blue-500',
    'bg-purple-500',
    'bg-emerald-500',
    'bg-amber-500',
    'bg-rose-500',
    'bg-indigo-500',
  ]
  const color = palette[(name.charCodeAt(0) || 0) % palette.length]
  return (
    <div
      className={`w-12 h-12 rounded-full ${color} flex items-center justify-center text-white font-bold text-lg flex-shrink-0`}
    >
      {initials}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CTA button — respects auth state
// ---------------------------------------------------------------------------
function CtaButton({ label, url, variant = 'primary', user, className = '' }) {
  const navigate = useNavigate()
  const dest = user ? '/dashboard' : url
  const base =
    'inline-flex items-center justify-center font-semibold rounded-xl px-7 py-3.5 text-base transition-all duration-200 active:scale-95'
  const styles =
    variant === 'primary'
      ? `${base} bg-primary hover:bg-blue-500 text-white shadow-lg hover:shadow-xl hover:scale-[1.02]`
      : `${base} bg-white/10 hover:bg-white/20 text-white border border-white/30 hover:scale-[1.02]`

  return (
    <button className={`${styles} ${className}`} onClick={() => navigate(dest)}>
      {label}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Section 1 — Hero
// ---------------------------------------------------------------------------
function HeroSection({ cfg, user }) {
  const bgStyle =
    cfg.bg_type === 'image' && cfg.bg_image_url
      ? {
          backgroundImage: `linear-gradient(to bottom right, rgba(30,0,60,0.85), rgba(15,23,42,0.90)), url(${cfg.bg_image_url})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }
      : {}

  return (
    <section
      className="relative min-h-screen flex flex-col items-center justify-center text-white overflow-hidden"
      style={
        cfg.bg_type === 'image' && cfg.bg_image_url
          ? bgStyle
          : undefined
      }
    >
      {/* Gradient background (default or fallback) */}
      {!(cfg.bg_type === 'image' && cfg.bg_image_url) && (
        <div className="absolute inset-0 bg-gradient-to-br from-indigo-950 via-purple-900 to-slate-900" />
      )}

      {/* Decorative blobs */}
      <div className="absolute top-1/4 -left-32 w-96 h-96 bg-purple-600/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 -right-32 w-96 h-96 bg-indigo-500/20 rounded-full blur-3xl pointer-events-none" />

      {/* Nav bar inside hero */}
      <nav className="absolute top-0 left-0 right-0 flex items-center justify-between px-6 md:px-12 py-5 z-10">
        <span className="font-bold text-xl tracking-tight text-white">
          📖 AI Textbook
        </span>
        <div className="flex items-center gap-3">
          {user ? (
            <Link
              to="/dashboard"
              className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white text-sm font-medium rounded-lg border border-white/20 transition-colors"
            >
              Dashboard →
            </Link>
          ) : (
            <>
              <Link
                to="/login"
                className="px-4 py-2 text-white/80 hover:text-white text-sm font-medium transition-colors"
              >
                Đăng nhập
              </Link>
              <Link
                to="/register"
                className="px-4 py-2 bg-primary hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Đăng ký
              </Link>
            </>
          )}
        </div>
      </nav>

      {/* Hero content */}
      <div className="relative z-10 text-center px-6 max-w-4xl mx-auto pt-20">
        <div
          className="inline-block text-xs font-semibold tracking-widest uppercase text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-full px-4 py-1.5 mb-6"
          style={{ opacity: 1 }}
        >
          Powered by LangGraph · CRAG · GPT-4.1
        </div>

        <h1 className="text-4xl md:text-6xl lg:text-7xl font-extrabold leading-tight tracking-tight mb-6 text-white">
          {cfg.headline}
        </h1>

        <p className="text-lg md:text-xl text-white/70 leading-relaxed max-w-2xl mx-auto mb-10">
          {cfg.subheadline}
        </p>

        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <CtaButton
            label={cfg.cta_primary_label}
            url={cfg.cta_primary_url}
            variant="primary"
            user={user}
          />
          <CtaButton
            label={cfg.cta_secondary_label}
            url={cfg.cta_secondary_url}
            variant="outline"
            user={user}
          />
        </div>

        {/* Scroll hint */}
        <div className="mt-20 flex flex-col items-center gap-2 text-white/30 text-xs animate-bounce">
          <span>Cuộn xuống để khám phá</span>
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 2 — Feature highlights
// ---------------------------------------------------------------------------
function FeaturesSection({ cfg }) {
  return (
    <section className="py-24 bg-white">
      <div className="content-container">
        <FadeUp className="text-center mb-14">
          <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
            Tất cả những gì bạn cần
          </h2>
          <p className="text-gray-500 text-lg max-w-xl mx-auto">
            Một hệ thống duy nhất từ chủ đề đến giáo trình xuất bản.
          </p>
        </FadeUp>

        <div className="grid md:grid-cols-3 gap-8">
          {cfg.features.map((f, i) => (
            <FadeUp key={i} delay={i * 120}>
              <div className="group p-8 rounded-2xl border border-gray-100 hover:border-primary/30 hover:shadow-xl hover:-translate-y-1 transition-all duration-300 bg-white">
                <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center text-2xl mb-5 group-hover:bg-primary/20 transition-colors">
                  {f.icon}
                </div>
                <h3 className="text-xl font-bold text-gray-900 mb-3">{f.title}</h3>
                <p className="text-gray-500 leading-relaxed">{f.description}</p>
              </div>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 3 — Pricing
// ---------------------------------------------------------------------------
function PricingSection({ cfg, user }) {
  const navigate = useNavigate()

  return (
    <section className="py-24 bg-gray-50">
      <div className="content-container">
        <FadeUp className="text-center mb-14">
          <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
            Bảng Giá Đơn Giản
          </h2>
          <p className="text-gray-500 text-lg">
            Chọn gói phù hợp với nhu cầu của bạn.
          </p>
        </FadeUp>

        <div className="grid md:grid-cols-3 gap-6 items-start max-w-5xl mx-auto">
          {cfg.plans.map((plan, i) => (
            <FadeUp key={plan.id || i} delay={i * 100}>
              <div
                className={`relative rounded-2xl p-8 flex flex-col transition-all duration-300 hover:-translate-y-1 ${
                  plan.is_recommended
                    ? 'bg-primary text-white shadow-2xl shadow-primary/30 border-2 border-primary scale-[1.02]'
                    : 'bg-white border border-gray-200 hover:border-primary/40 hover:shadow-lg text-gray-900'
                }`}
              >
                {plan.is_recommended && (
                  <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-amber-400 text-gray-900 text-xs font-bold px-4 py-1 rounded-full uppercase tracking-wide shadow">
                    Phổ biến nhất
                  </div>
                )}

                <div className="mb-6">
                  <h3
                    className={`text-xl font-bold mb-2 ${
                      plan.is_recommended ? 'text-white' : 'text-gray-900'
                    }`}
                  >
                    {plan.name}
                  </h3>
                  <div
                    className={`text-3xl font-extrabold ${
                      plan.is_recommended ? 'text-white' : 'text-gray-900'
                    }`}
                  >
                    {plan.price}
                  </div>
                </div>

                <ul className="space-y-3 flex-1 mb-8">
                  {(plan.features || []).map((feat, fi) => (
                    <li key={fi} className="flex items-start gap-2.5">
                      <svg
                        className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
                          plan.is_recommended ? 'text-white/80' : 'text-primary'
                        }`}
                        fill="currentColor"
                        viewBox="0 0 20 20"
                      >
                        <path
                          fillRule="evenodd"
                          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                          clipRule="evenodd"
                        />
                      </svg>
                      <span
                        className={`text-sm ${
                          plan.is_recommended ? 'text-white/90' : 'text-gray-600'
                        }`}
                      >
                        {feat}
                      </span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={() =>
                    navigate(
                      user ? '/dashboard' : `${plan.cta_label === 'Liên hệ chúng tôi' ? '/register' : `/register?plan=${plan.id}`}`,
                    )
                  }
                  className={`w-full py-3 rounded-xl font-semibold text-sm transition-all duration-200 hover:scale-[1.02] active:scale-95 ${
                    plan.is_recommended
                      ? 'bg-white text-primary hover:bg-gray-50 shadow-lg'
                      : 'bg-primary text-white hover:bg-blue-500 shadow-md'
                  }`}
                >
                  {plan.cta_label}
                </button>
              </div>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 4 — Stats bar
// ---------------------------------------------------------------------------
function StatsSection({ cfg }) {
  return (
    <section className="py-20 bg-gray-900">
      <div className="content-container">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 md:gap-4">
          {cfg.stats.map((s, i) => (
            <FadeUp key={i} delay={i * 80} className="text-center">
              <div className="text-3xl md:text-4xl font-extrabold text-white mb-2">
                {s.value}
              </div>
              <div className="text-sm text-gray-400 font-medium">{s.label}</div>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 5 — Testimonials
// ---------------------------------------------------------------------------
function TestimonialsSection({ cfg }) {
  if (!cfg.testimonials || cfg.testimonials.length === 0) return null

  return (
    <section className="py-24 bg-white">
      <div className="content-container">
        <FadeUp className="text-center mb-14">
          <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
            Người dùng nói gì?
          </h2>
        </FadeUp>

        <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
          {cfg.testimonials.map((t, i) => (
            <FadeUp key={i} delay={i * 120}>
              <div className="bg-gray-50 rounded-2xl p-8 border border-gray-100 hover:shadow-lg hover:-translate-y-0.5 transition-all duration-300">
                {/* Quote mark */}
                <div className="text-5xl text-primary/20 font-serif leading-none mb-4">"</div>
                <p className="text-gray-700 leading-relaxed mb-6 italic">
                  {t.quote}
                </p>
                <div className="flex items-center gap-3">
                  {t.avatar ? (
                    <img
                      src={t.avatar}
                      alt={t.name}
                      className="w-12 h-12 rounded-full object-cover"
                    />
                  ) : (
                    <InitialsAvatar name={t.name} />
                  )}
                  <div>
                    <div className="font-semibold text-gray-900">{t.name}</div>
                    <div className="text-sm text-gray-500">{t.role}</div>
                  </div>
                </div>
              </div>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 6 — Partner logos
// ---------------------------------------------------------------------------
function PartnersSection({ cfg }) {
  if (!cfg.partner_logos || cfg.partner_logos.length === 0) return null

  return (
    <section className="py-16 bg-gray-50 border-t border-gray-100">
      <div className="content-container">
        <FadeUp>
          <p className="text-center text-sm font-semibold text-gray-400 uppercase tracking-widest mb-8">
            Được xây dựng trên nền tảng
          </p>
          <div className="flex flex-wrap justify-center items-center gap-10 md:gap-16">
            {cfg.partner_logos.map((logo, i) => (
              <div key={i} className="flex items-center justify-center h-10">
                <img
                  src={logo.url}
                  alt={logo.name}
                  className="h-8 max-w-[120px] object-contain"
                  style={{ filter: 'grayscale(100%) opacity(0.45)' }}
                  onError={e => {
                    e.currentTarget.style.display = 'none'
                  }}
                />
              </div>
            ))}
          </div>
        </FadeUp>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 7 — Final CTA banner
// ---------------------------------------------------------------------------
function CtaBannerSection({ cfg, user }) {
  const navigate = useNavigate()
  const dest = user ? '/dashboard' : (cfg.cta_banner.button_url || '/register')

  return (
    <section
      className="py-24 text-white text-center relative overflow-hidden"
      style={{ backgroundColor: cfg.cta_banner.bg_color || '#4F46E5' }}
    >
      <div className="absolute inset-0 opacity-10 pointer-events-none"
        style={{
          backgroundImage:
            'radial-gradient(circle at 20% 50%, white 1px, transparent 1px), radial-gradient(circle at 80% 50%, white 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }}
      />
      <div className="content-container relative z-10">
        <FadeUp>
          <h2 className="text-3xl md:text-5xl font-extrabold mb-6 leading-tight">
            {cfg.cta_banner.headline}
          </h2>
          <button
            onClick={() => navigate(dest)}
            className="inline-flex items-center gap-2 bg-white text-indigo-700 hover:bg-gray-100 font-bold px-10 py-4 rounded-2xl text-lg shadow-xl hover:shadow-2xl transition-all duration-200 hover:scale-[1.03] active:scale-95"
          >
            {cfg.cta_banner.button_label}
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </button>
        </FadeUp>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 8 — Footer
// ---------------------------------------------------------------------------
function FooterSection({ cfg }) {
  if (!cfg) return null
  return (
    <footer className="bg-gray-950 text-gray-500 py-10">
      <div className="content-container flex flex-col md:flex-row items-center justify-between gap-4">
        <p className="text-sm">{cfg.copyright}</p>
        <nav className="flex gap-6">
          {(cfg.links || []).map((link, i) => (
            <Link
              key={i}
              to={link.url}
              className="text-sm hover:text-gray-300 transition-colors"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  )
}

// ---------------------------------------------------------------------------
// Page root
// ---------------------------------------------------------------------------
export function LandingPage() {
  const { user, loading } = useAuth()
  // Lazy initializer: loadConfig() runs once synchronously before first render
  const [config, setConfig] = useState(() => loadConfig())

  // Re-load config when window regains focus so admin changes in another tab
  // take effect immediately — only registers/unregisters a listener, no sync setState
  useEffect(() => {
    const onFocus = () => setConfig(loadConfig())
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])

  // Fetch live plans from DB and replace the static plan list
  useEffect(() => {
    plansAPI.listActive().then(r => {
      if (!r.data || r.data.length === 0) return
      const apiPlans = r.data.map(p => ({
        id: String(p.id),
        name: p.name,
        price: p.price_vnd.toLocaleString('vi-VN') + '₫',
        features: p.features,
        is_recommended: p.is_recommended,
        cta_label: 'Mua ngay',
      }))
      setConfig(prev => ({ ...prev, plans: apiPlans }))
    }).catch(() => {/* keep default config on error */})
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-white" />
      </div>
    )
  }

  return (
    <div className="overflow-x-hidden">
      <HeroSection cfg={config.hero} user={user} />
      <FeaturesSection cfg={config} />
      <PricingSection cfg={config} user={user} />
      <StatsSection cfg={config} />
      <TestimonialsSection cfg={config} />
      <PartnersSection cfg={config} />
      <CtaBannerSection cfg={config} user={user} />
      <FooterSection cfg={config.footer} />
    </div>
  )
}
