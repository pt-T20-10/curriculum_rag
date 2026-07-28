import { useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  FiClock,
  FiMail,
  FiMapPin,
  FiPhone,
  FiUser,
} from 'react-icons/fi'
import { PublicPageHeader } from '../components/layout/PublicPageHeader'
import { AccountDeletionRequestForm } from '../components/account/AccountDeletionRequestForm'
import { SupportRequestForm } from '../components/support/SupportRequestForm'
import { PUBLIC_PAGE_CONTENT } from '../content/publicPages'
import { useSiteInfo } from '../hooks/useSiteInfo'

const RELATED_PAGES = [
  { type: 'privacy', path: '/privacy-policy' },
  { type: 'terms', path: '/terms-of-service' },
  { type: 'deletion', path: '/data-deletion' },
  { type: 'support', path: '/support' },
  { type: 'contact', path: '/contact' },
]

function ContactDetails({ info }) {
  const { t } = useTranslation()
  const fields = [
    { key: 'operator_name', label: t('publicInfo.contact.operator'), icon: FiUser },
    { key: 'address', label: t('publicInfo.contact.address'), icon: FiMapPin },
    {
      key: 'support_email',
      label: t('publicInfo.contact.supportEmail'),
      icon: FiMail,
      href: value => `mailto:${value}`,
    },
    {
      key: 'privacy_email',
      label: t('publicInfo.contact.privacyEmail'),
      icon: FiMail,
      href: value => `mailto:${value}`,
    },
    {
      key: 'phone',
      label: t('publicInfo.contact.phone'),
      icon: FiPhone,
      href: value => `tel:${value.replace(/\s+/g, '')}`,
    },
    { key: 'support_hours', label: t('publicInfo.contact.hours'), icon: FiClock },
  ]

  const hasContactChannel = Boolean(
    info?.operator_name ||
    info?.address ||
    info?.support_email ||
    info?.privacy_email ||
    info?.phone,
  )

  return (
    <section className="mt-12 border-t border-gray-200 pt-8" aria-labelledby="official-contact">
      <h2 id="official-contact" className="text-xl font-bold text-gray-900">
        {t('publicInfo.contact.title')}
      </h2>
      <p className="mt-2 text-sm leading-6 text-gray-600">
        {t('app.name')}
      </p>
      {!hasContactChannel && (
        <p className="mt-4 border-l-4 border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {t('publicInfo.contact.notConfigured')}
        </p>
      )}
      <dl className="mt-6 grid gap-x-8 gap-y-5 sm:grid-cols-2">
        {fields.map(({ key, label, icon: Icon, href }) => {
          const value = info?.[key]
          if (!value) return null
          return (
            <div key={key} className="flex gap-3">
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
              <div>
                <dt className="text-xs font-semibold uppercase text-gray-500">{label}</dt>
                <dd className="mt-1 break-words text-sm text-gray-800">
                  {href ? <a href={href(value)} className="text-primary hover:underline">{value}</a> : value}
                </dd>
              </div>
            </div>
          )
        })}
      </dl>
      {info?.response_time && (
        <p className="mt-6 text-sm leading-6 text-gray-600">{info.response_time}</p>
      )}
    </section>
  )
}

export function PublicInfoPage({ type }) {
  const { i18n, t } = useTranslation()
  const language = i18n.resolvedLanguage === 'en' ? 'en' : 'vi'
  const content = PUBLIC_PAGE_CONTENT[language][type]
  const { siteInfo } = useSiteInfo(language)

  const effectiveDate = useMemo(() => {
    if (!siteInfo.effective_date) return t('publicInfo.notSpecified')
    const parsed = new Date(`${siteInfo.effective_date}T00:00:00`)
    if (Number.isNaN(parsed.getTime())) return siteInfo.effective_date
    return parsed.toLocaleDateString(language === 'en' ? 'en-US' : 'vi-VN', {
      day: '2-digit',
      month: 'long',
      year: 'numeric',
    })
  }, [language, siteInfo.effective_date, t])

  useEffect(() => {
    document.title = `${content.title} | ${t('app.name')}`
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [content.title, t])

  const related = useMemo(
    () => RELATED_PAGES.filter(page => page.type !== type),
    [type],
  )

  return (
    <div className="min-h-screen bg-white">
      <PublicPageHeader />
      <main>
        <div className="border-b border-gray-200 bg-gray-50">
          <div className="content-container-md py-10 sm:py-14">
            <Link to="/" className="text-sm font-medium text-primary hover:underline">
              {t('publicInfo.backHome')}
            </Link>
            <p className="mt-6 text-sm font-semibold uppercase text-primary">{content.eyebrow}</p>
            <h1 className="mt-2 break-words text-2xl font-bold text-gray-950 sm:text-4xl">{content.title}</h1>
            <p className="mt-4 max-w-3xl break-words text-base leading-7 text-gray-600">{content.summary}</p>
            <p className="mt-5 text-sm text-gray-500">
              {t('publicInfo.effectiveDate', {
                date: effectiveDate,
              })}
            </p>
          </div>
        </div>

        <div className="content-container-md grid gap-10 py-10 lg:grid-cols-[190px_minmax(0,1fr)] lg:py-14">
          <aside>
            <nav className="lg:sticky lg:top-6" aria-label={t('publicInfo.onThisPage')}>
              <p className="text-xs font-bold uppercase text-gray-500">{t('publicInfo.onThisPage')}</p>
              <ol className="mt-3 space-y-2 border-l border-gray-200 pl-4">
                {content.sections.map(section => (
                  <li key={section.id}>
                    <a href={`#${section.id}`} className="text-sm leading-5 text-gray-600 hover:text-primary">
                      {section.title}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </aside>

          <article className="min-w-0">
            {type === 'support' && <SupportRequestForm language={language} />}
            {type === 'deletion' && <AccountDeletionRequestForm language={language} />}

            <div className={`space-y-10 ${type === 'support' || type === 'deletion' ? 'mt-12 border-t border-gray-200 pt-10' : ''}`}>
              {content.sections.map(section => (
                <section key={section.id} id={section.id} className="scroll-mt-6">
                  <h2 className="text-xl font-bold text-gray-950">{section.title}</h2>
                  {section.paragraphs?.map((paragraph, index) => (
                    <p key={index} className="mt-3 text-[15px] leading-7 text-gray-700">{paragraph}</p>
                  ))}
                  {section.bullets && (
                    <ul className="mt-4 space-y-2 pl-5 text-[15px] leading-7 text-gray-700">
                      {section.bullets.map((bullet, index) => (
                        <li key={index} className="list-disc pl-1">{bullet}</li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </div>

            <ContactDetails info={siteInfo} />

            <section className="mt-12 border-t border-gray-200 pt-8">
              <h2 className="text-lg font-bold text-gray-900">{t('publicInfo.relatedTitle')}</h2>
              <div className="mt-4 flex flex-wrap gap-x-5 gap-y-3">
                {related.map(page => (
                  <Link key={page.path} to={page.path} className="text-sm font-medium text-primary hover:underline">
                    {t(`footer.links.${page.type}`)}
                  </Link>
                ))}
              </div>
            </section>
          </article>
        </div>
      </main>
    </div>
  )
}
