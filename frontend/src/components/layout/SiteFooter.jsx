import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FiMail, FiMapPin, FiPhone } from 'react-icons/fi'
import { useSiteInfo } from '../../hooks/useSiteInfo'

const NAVIGATION_LINKS = [
  { key: 'home', url: '/' },
  { key: 'login', url: '/login' },
  { key: 'register', url: '/register' },
]

const LEGAL_LINKS = [
  { key: 'privacy', url: '/privacy-policy' },
  { key: 'terms', url: '/terms-of-service' },
  { key: 'deletion', url: '/data-deletion' },
]

const SUPPORT_LINKS = [
  { key: 'support', url: '/support' },
  { key: 'contact', url: '/contact' },
]

function FooterLink({ link }) {
  const className = 'text-sm text-gray-400 transition-colors hover:text-white'
  if (/^https?:\/\//i.test(link.url)) {
    return (
      <a href={link.url} target="_blank" rel="noreferrer" className={className}>
        {link.label}
      </a>
    )
  }
  return <Link to={link.url || '/'} className={className}>{link.label}</Link>
}

export function SiteFooter() {
  const { i18n, t } = useTranslation()
  const language = i18n.resolvedLanguage === 'en' ? 'en' : 'vi'
  const { siteInfo } = useSiteInfo(language)
  const withLabel = link => ({ ...link, label: t(`footer.links.${link.key}`) })
  const navigationLinks = NAVIGATION_LINKS.map(withLabel)
  const legalLinks = LEGAL_LINKS.map(withLabel)
  const supportLinks = SUPPORT_LINKS.map(withLabel)

  const contactItems = [
    siteInfo.address && { icon: FiMapPin, text: siteInfo.address },
    siteInfo.support_email && {
      icon: FiMail,
      text: siteInfo.support_email,
      href: `mailto:${siteInfo.support_email}`,
    },
    siteInfo.phone && {
      icon: FiPhone,
      text: siteInfo.phone,
      href: `tel:${siteInfo.phone.replace(/\s+/g, '')}`,
    },
  ].filter(Boolean)

  return (
    <footer className="bg-gray-950 text-gray-400">
      <div className="content-container py-10">
        <div className="grid gap-x-8 gap-y-10 border-b border-gray-800 pb-9 sm:grid-cols-2 lg:grid-cols-[1.45fr_0.8fr_1fr_1.1fr]">
          <div>
            <Link to="/" className="text-base font-semibold text-white">
              {siteInfo.service_name || t('app.name')}
            </Link>
            <p className="mt-2 max-w-xl text-sm leading-6 text-gray-500">
              {t('footer.description')}
            </p>
            {siteInfo.operator_name && (
              <p className="mt-3 text-sm text-gray-400">
                {t('footer.operatedBy', { name: siteInfo.operator_name })}
              </p>
            )}
          </div>

          <div>
            <h2 className="text-sm font-semibold text-white">{t('footer.navigationTitle')}</h2>
            <nav className="mt-4 flex flex-col items-start gap-3" aria-label={t('footer.navigationTitle')}>
              {navigationLinks.map(link => (
                <FooterLink key={`${link.url}-${link.label}`} link={link} />
              ))}
            </nav>
          </div>

          <div>
            <h2 className="text-sm font-semibold text-white">{t('footer.legalTitle')}</h2>
            <nav className="mt-4 flex flex-col items-start gap-3" aria-label={t('footer.legalTitle')}>
              {legalLinks.map(link => (
                <FooterLink key={`${link.url}-${link.label}`} link={link} />
              ))}
            </nav>
          </div>

          <div>
            <h2 className="text-sm font-semibold text-white">{t('footer.supportTitle')}</h2>
            <nav className="mt-4 flex flex-col items-start gap-3" aria-label={t('footer.supportTitle')}>
              {supportLinks.map(link => (
                <FooterLink key={`${link.url}-${link.label}`} link={link} />
              ))}
            </nav>

            {contactItems.length > 0 && (
              <div className="mt-5 space-y-3 border-t border-gray-800 pt-4">
                {contactItems.map(({ icon: Icon, text, href }) => (
                  <div key={text} className="flex items-start gap-2 text-sm leading-5">
                    <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    {href ? (
                      <a href={href} className="break-all hover:text-white">{text}</a>
                    ) : (
                      <span>{text}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="pt-7">
          <p className="text-sm text-gray-500">
            {t('footer.defaultCopyright', {
              year: new Date().getFullYear(),
              name: siteInfo.service_name || t('app.name'),
            })}
          </p>
        </div>
      </div>
    </footer>
  )
}
