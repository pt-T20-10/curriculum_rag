import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Navbar } from '../../components/layout/Navbar'
import { AdminNavigation } from '../../components/layout/AdminNavigation'
import { loadConfig, saveConfig, DEFAULT_CONFIG } from '../../utils/landingConfig'

// ---------------------------------------------------------------------------
// Tiny reusable field components
// ---------------------------------------------------------------------------
function Field({ label, hint, children }) {
  return (
    <div className="mb-5">
      <label className="block text-sm font-semibold text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1.5">{hint}</p>}
      {children}
    </div>
  )
}

function TextInput({ value, onChange, placeholder, className = '' }) {
  return (
    <input
      type="text"
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary ${className}`}
    />
  )
}

function TextArea({ value, onChange, rows = 3, placeholder }) {
  return (
    <textarea
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      rows={rows}
      placeholder={placeholder}
      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary resize-y"
    />
  )
}

// Collapsible section card
function SectionCard({ title, icon, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mb-4">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors"
      >
        <span className="flex items-center gap-2 font-semibold text-gray-800">
          <span>{icon}</span>
          {title}
        </span>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="px-6 py-5 border-t border-gray-100">{children}</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section editors
// ---------------------------------------------------------------------------

function HeroEditor({ hero, onChange }) {
  const set = (key, val) => onChange({ ...hero, [key]: val })
  return (
    <>
      <Field label="Tiêu đề chính (Headline)">
        <TextInput value={hero.headline} onChange={v => set('headline', v)} placeholder="Tạo Giáo Trình AI Hoàn Chỉnh" />
      </Field>
      <Field label="Mô tả (Subheadline)">
        <TextArea value={hero.subheadline} onChange={v => set('subheadline', v)} rows={2} />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Nút CTA chính — nhãn">
          <TextInput value={hero.cta_primary_label} onChange={v => set('cta_primary_label', v)} placeholder="Bắt đầu miễn phí" />
        </Field>
        <Field label="Nút CTA chính — URL">
          <TextInput value={hero.cta_primary_url} onChange={v => set('cta_primary_url', v)} placeholder="/register" />
        </Field>
        <Field label="Nút CTA phụ — nhãn">
          <TextInput value={hero.cta_secondary_label} onChange={v => set('cta_secondary_label', v)} placeholder="Đăng nhập" />
        </Field>
        <Field label="Nút CTA phụ — URL">
          <TextInput value={hero.cta_secondary_url} onChange={v => set('cta_secondary_url', v)} placeholder="/login" />
        </Field>
      </div>
      <Field label="Loại nền">
        <div className="flex gap-3">
          {['gradient', 'image'].map(t => (
            <button
              key={t}
              type="button"
              onClick={() => set('bg_type', t)}
              className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                hero.bg_type === t
                  ? 'bg-primary text-white border-primary'
                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
              }`}
            >
              {t === 'gradient' ? '🎨 Gradient' : '🖼 Ảnh'}
            </button>
          ))}
        </div>
      </Field>
      {hero.bg_type === 'image' && (
        <Field label="URL ảnh nền" hint="Ảnh từ Unsplash hoặc URL công khai khác">
          <TextInput value={hero.bg_image_url} onChange={v => set('bg_image_url', v)} placeholder="https://images.unsplash.com/..." />
        </Field>
      )}
    </>
  )
}

function FeaturesEditor({ features, onChange }) {
  const setFeature = (i, key, val) => {
    const next = features.map((f, idx) => (idx === i ? { ...f, [key]: val } : f))
    onChange(next)
  }
  return (
    <div className="space-y-6">
      {features.map((f, i) => (
        <div key={i} className="p-4 bg-gray-50 rounded-xl border border-gray-200">
          <p className="text-xs font-bold text-gray-400 uppercase mb-3">Tính năng {i + 1}</p>
          <div className="grid grid-cols-4 gap-3">
            <Field label="Icon (emoji)">
              <TextInput value={f.icon} onChange={v => setFeature(i, 'icon', v)} placeholder="🤖" />
            </Field>
            <div className="col-span-3">
              <Field label="Tiêu đề">
                <TextInput value={f.title} onChange={v => setFeature(i, 'title', v)} />
              </Field>
            </div>
          </div>
          <Field label="Mô tả">
            <TextArea value={f.description} onChange={v => setFeature(i, 'description', v)} rows={2} />
          </Field>
        </div>
      ))}
    </div>
  )
}

function StatsEditor({ stats, onChange }) {
  const setStat = (i, key, val) =>
    onChange(stats.map((s, idx) => (idx === i ? { ...s, [key]: val } : s)))
  const addStat = () => onChange([...stats, { value: '', label: '' }])
  const removeStat = i => onChange(stats.filter((_, idx) => idx !== i))

  return (
    <div className="space-y-3">
      {stats.map((s, i) => (
        <div key={i} className="flex gap-3 items-end">
          <div className="flex-1">
            <Field label={i === 0 ? 'Giá trị' : undefined}>
              <TextInput value={s.value} onChange={v => setStat(i, 'value', v)} placeholder="500+" />
            </Field>
          </div>
          <div className="flex-[2]">
            <Field label={i === 0 ? 'Nhãn' : undefined}>
              <TextInput value={s.label} onChange={v => setStat(i, 'label', v)} placeholder="Giáo trình đã tạo" />
            </Field>
          </div>
          {stats.length > 1 && (
            <button
              type="button"
              onClick={() => removeStat(i)}
              className="mb-5 text-red-400 hover:text-red-600 transition-colors text-lg leading-none"
            >
              ×
            </button>
          )}
        </div>
      ))}
      {stats.length < 6 && (
        <button
          type="button"
          onClick={addStat}
          className="text-sm text-primary hover:underline"
        >
          + Thêm thống kê
        </button>
      )}
    </div>
  )
}

function TestimonialsEditor({ testimonials, onChange }) {
  const set = (i, key, val) =>
    onChange(testimonials.map((t, idx) => (idx === i ? { ...t, [key]: val } : t)))
  const add = () =>
    onChange([...testimonials, { avatar: '', name: '', role: '', quote: '' }])
  const remove = i => onChange(testimonials.filter((_, idx) => idx !== i))

  return (
    <div className="space-y-4">
      {testimonials.map((t, i) => (
        <div key={i} className="p-4 bg-gray-50 rounded-xl border border-gray-200">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-bold text-gray-400 uppercase">Đánh giá {i + 1}</p>
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-xs text-red-500 hover:text-red-700"
            >
              Xóa
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Tên">
              <TextInput value={t.name} onChange={v => set(i, 'name', v)} />
            </Field>
            <Field label="Vai trò">
              <TextInput value={t.role} onChange={v => set(i, 'role', v)} placeholder="Giảng viên" />
            </Field>
          </div>
          <Field label="URL ảnh đại diện" hint="Để trống để dùng avatar chữ tắt">
            <TextInput value={t.avatar} onChange={v => set(i, 'avatar', v)} placeholder="https://..." />
          </Field>
          <Field label="Nội dung đánh giá">
            <TextArea value={t.quote} onChange={v => set(i, 'quote', v)} rows={3} />
          </Field>
        </div>
      ))}
      {testimonials.length < 6 && (
        <button
          type="button"
          onClick={add}
          className="w-full py-3 border-2 border-dashed border-gray-300 rounded-xl text-sm text-gray-500 hover:border-primary hover:text-primary transition-colors font-medium"
        >
          + Thêm đánh giá
        </button>
      )}
    </div>
  )
}

function PartnersEditor({ logos, onChange }) {
  const set = (i, key, val) =>
    onChange(logos.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)))
  const add = () => onChange([...logos, { name: '', url: '' }])
  const remove = i => onChange(logos.filter((_, idx) => idx !== i))

  return (
    <div className="space-y-3">
      {logos.map((l, i) => (
        <div key={i} className="flex gap-3 items-end">
          <div className="w-32">
            <Field label={i === 0 ? 'Tên' : undefined}>
              <TextInput value={l.name} onChange={v => set(i, 'name', v)} placeholder="OpenAI" />
            </Field>
          </div>
          <div className="flex-1">
            <Field label={i === 0 ? 'URL ảnh logo' : undefined}>
              <TextInput value={l.url} onChange={v => set(i, 'url', v)} placeholder="https://..." />
            </Field>
          </div>
          <button
            type="button"
            onClick={() => remove(i)}
            className="mb-5 text-red-400 hover:text-red-600 text-lg leading-none"
          >
            ×
          </button>
        </div>
      ))}
      {logos.length < 8 && (
        <button
          type="button"
          onClick={add}
          className="text-sm text-primary hover:underline"
        >
          + Thêm logo
        </button>
      )}
    </div>
  )
}

function CtaBannerEditor({ banner, onChange }) {
  const set = (key, val) => onChange({ ...banner, [key]: val })
  return (
    <>
      <Field label="Tiêu đề banner">
        <TextInput value={banner.headline} onChange={v => set('headline', v)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Nhãn nút">
          <TextInput value={banner.button_label} onChange={v => set('button_label', v)} />
        </Field>
        <Field label="URL nút">
          <TextInput value={banner.button_url} onChange={v => set('button_url', v)} placeholder="/register" />
        </Field>
      </div>
      <Field label="Màu nền" hint="Hex color (#rrggbb)">
        <div className="flex items-center gap-3">
          <input
            type="color"
            value={banner.bg_color || '#4F46E5'}
            onChange={e => set('bg_color', e.target.value)}
            className="h-9 w-16 rounded cursor-pointer border border-gray-300"
          />
          <TextInput
            value={banner.bg_color || '#4F46E5'}
            onChange={v => set('bg_color', v)}
            className="flex-1"
            placeholder="#4F46E5"
          />
        </div>
      </Field>
    </>
  )
}

function FooterEditor({ footer, onChange }) {
  const set = (key, val) => onChange({ ...footer, [key]: val })
  const setLink = (i, key, val) =>
    onChange({
      ...footer,
      links: footer.links.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)),
    })
  const addLink = () =>
    onChange({ ...footer, links: [...(footer.links || []), { label: '', url: '' }] })
  const removeLink = i =>
    onChange({ ...footer, links: footer.links.filter((_, idx) => idx !== i) })

  return (
    <>
      <Field label="Copyright">
        <TextInput value={footer.copyright} onChange={v => set('copyright', v)} />
      </Field>
      <Field label="Liên kết">
        <div className="space-y-2">
          {(footer.links || []).map((link, i) => (
            <div key={i} className="flex gap-2 items-center">
              <TextInput
                value={link.label}
                onChange={v => setLink(i, 'label', v)}
                placeholder="Nhãn"
                className="flex-1"
              />
              <TextInput
                value={link.url}
                onChange={v => setLink(i, 'url', v)}
                placeholder="/login"
                className="flex-1"
              />
              <button
                type="button"
                onClick={() => removeLink(i)}
                className="text-red-400 hover:text-red-600 text-lg leading-none px-1"
              >
                ×
              </button>
            </div>
          ))}
          {(footer.links || []).length < 5 && (
            <button
              type="button"
              onClick={addLink}
              className="text-sm text-primary hover:underline mt-1"
            >
              + Thêm liên kết
            </button>
          )}
        </div>
      </Field>
    </>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function AdminLandingPage() {
  const [config, setConfig] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setConfig(loadConfig())
  }, [])

  const set = useCallback((section, val) => {
    setConfig(prev => ({ ...prev, [section]: val }))
    setSaved(false)
  }, [])

  const handleSave = () => {
    saveConfig(config)
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  const handleReset = () => {
    if (window.confirm('Khôi phục tất cả cài đặt về mặc định?')) {
      setConfig(DEFAULT_CONFIG)
      saveConfig(DEFAULT_CONFIG)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    }
  }

  if (!config) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Navbar />
        <div className="flex-1 flex items-center justify-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" />
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />

      <div className="max-w-4xl mx-auto w-full px-6 py-8">
        <AdminNavigation className="mb-6" />

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link to="/admin" className="text-sm text-gray-400 hover:text-gray-600 transition-colors">
                Admin
              </Link>
              <span className="text-gray-300">/</span>
              <span className="text-sm font-medium text-gray-700">Landing Page</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-800">Tùy chỉnh Landing Page</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              Thay đổi được lưu vào trình duyệt và có hiệu lực ngay lập tức.
            </p>
          </div>
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between bg-white rounded-xl border border-gray-200 px-5 py-3 mb-6 shadow-sm">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => window.open('/', '_blank')}
              className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-primary transition-colors font-medium"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              Xem trước trang
            </button>
            <span className="text-gray-200">|</span>
            <button
              type="button"
              onClick={handleReset}
              className="text-sm text-gray-400 hover:text-red-500 transition-colors"
            >
              Khôi phục mặc định
            </button>
          </div>

          <button
            type="button"
            onClick={handleSave}
            className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all duration-200 ${
              saved
                ? 'bg-green-500 text-white'
                : 'bg-primary hover:bg-blue-600 text-white'
            }`}
          >
            {saved ? (
              <>
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                Đã lưu!
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                </svg>
                Lưu thay đổi
              </>
            )}
          </button>
        </div>

        {/* Section editors */}
        <SectionCard title="Hero" icon="🚀" defaultOpen>
          <HeroEditor hero={config.hero} onChange={v => set('hero', v)} />
        </SectionCard>

        <SectionCard title="Tính năng nổi bật" icon="✨">
          <FeaturesEditor features={config.features} onChange={v => set('features', v)} />
        </SectionCard>

        <SectionCard title="Thống kê" icon="📊">
          <StatsEditor stats={config.stats} onChange={v => set('stats', v)} />
        </SectionCard>

        <SectionCard title="Đánh giá người dùng" icon="💬">
          <TestimonialsEditor
            testimonials={config.testimonials}
            onChange={v => set('testimonials', v)}
          />
        </SectionCard>

        <SectionCard title="Logo đối tác" icon="🤝">
          <PartnersEditor
            logos={config.partner_logos}
            onChange={v => set('partner_logos', v)}
          />
        </SectionCard>

        <SectionCard title="Banner CTA cuối trang" icon="🎯">
          <CtaBannerEditor
            banner={config.cta_banner}
            onChange={v => set('cta_banner', v)}
          />
        </SectionCard>

        <SectionCard title="Footer" icon="🔗">
          <FooterEditor footer={config.footer} onChange={v => set('footer', v)} />
        </SectionCard>

        {/* Sticky save at bottom */}
        <div className="sticky bottom-6 flex justify-end mt-6">
          <button
            type="button"
            onClick={handleSave}
            className={`flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold shadow-xl transition-all duration-200 ${
              saved
                ? 'bg-green-500 text-white'
                : 'bg-primary hover:bg-blue-600 text-white'
            }`}
          >
            {saved ? '✓ Đã lưu!' : '💾 Lưu thay đổi'}
          </button>
        </div>
      </div>
    </div>
  )
}
