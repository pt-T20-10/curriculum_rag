const LEGACY_STORAGE_KEY = 'landing_page_config_v1'
const STORAGE_KEY_PREFIX = 'landing_page_config_v2'
export const LANDING_CONFIG_UPDATED_EVENT = 'landing-config-updated'

const sharedAssets = {
  bg_image_url:
    'https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?w=1920&q=80',
  partner_logos: [
    {
      name: 'OpenAI',
      url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4d/OpenAI_Logo.svg/320px-OpenAI_Logo.svg.png',
    },
    {
      name: 'LangChain',
      url: 'https://python.langchain.com/img/brand/wordmark.png',
    },
    {
      name: 'ChromaDB',
      url: 'https://avatars.githubusercontent.com/u/107664498?s=200&v=4',
    },
    {
      name: 'Typst',
      url: 'https://avatars.githubusercontent.com/u/97634504?s=200&v=4',
    },
  ],
}

export const DEFAULT_CONFIGS = {
  vi: {
    hero: {
      headline: 'Tạo Giáo Trình AI Hoàn Chỉnh',
      subheadline:
        'Nhập một chủ đề — nhận lại giáo trình học thuật đầy đủ với chương, mục, hình minh họa DALL·E và xuất PDF chuyên nghiệp. Hoàn toàn tự động.',
      cta_primary_label: 'Bắt đầu miễn phí',
      cta_primary_url: '/register',
      cta_secondary_label: 'Đăng nhập',
      cta_secondary_url: '/login',
      bg_type: 'gradient',
      bg_image_url: sharedAssets.bg_image_url,
    },

    features: [
      {
        icon: '🤖',
        title: 'Tự Động Hoàn Toàn',
        description:
          'Từ một chủ đề, hệ thống tự lập kế hoạch, thu thập tài liệu song ngữ, viết nội dung học thuật và xuất PDF — không cần can thiệp thủ công.',
      },
      {
        icon: '📚',
        title: 'Có Căn Cứ Nguồn',
        description:
          'Mỗi chương được hỗ trợ bởi nội dung thực từ web Việt–Anh qua ChromaDB. Pipeline CRAG đảm bảo nội dung không hallucinate.',
      },
      {
        icon: '📄',
        title: 'Xuất Bản Chuyên Nghiệp',
        description:
          'Xuất PDF với công thức toán Typst, hình minh họa AI, mục lục tự động, và Word có đánh số trang — sẵn sàng in ấn ngay.',
      },
    ],

    stats: [
      { value: '500+', label: 'Giáo trình đã tạo' },
      { value: 'Việt & Anh', label: 'Nguồn song ngữ' },
      { value: '98%', label: 'Tỷ lệ hoàn thành' },
      { value: '< 30 phút', label: 'Thời gian trung bình' },
    ],

    testimonials: [
      {
        avatar: '',
        name: 'Nguyễn Văn An',
        role: 'Giảng viên Đại học',
        quote:
          'Hệ thống giúp tôi tạo giáo trình 200 trang chỉ trong 25 phút. Chất lượng nội dung và định dạng PDF vượt mong đợi.',
      },
      {
        avatar: '',
        name: 'Trần Thị Bình',
        role: 'Nhà nghiên cứu độc lập',
        quote:
          'Pipeline CRAG đảm bảo mọi nội dung đều có nguồn gốc rõ ràng. Tôi tin tưởng dùng nó cho tài liệu nghiên cứu của mình.',
      },
    ],

    partner_logos: sharedAssets.partner_logos,

    cta_banner: {
      headline: 'Sẵn sàng tạo giáo trình đầu tiên của bạn?',
      button_label: 'Đăng ký miễn phí',
      button_url: '/register',
      bg_color: '#4F46E5',
    },

  },

  en: {
    hero: {
      headline: 'Create Complete AI Textbooks',
      subheadline:
        'Enter a topic and receive a full academic textbook with chapters, sections, AI illustrations, and professional PDF export. Fully automated.',
      cta_primary_label: 'Start free',
      cta_primary_url: '/register',
      cta_secondary_label: 'Log in',
      cta_secondary_url: '/login',
      bg_type: 'gradient',
      bg_image_url: sharedAssets.bg_image_url,
    },

    features: [
      {
        icon: '🤖',
        title: 'Fully Automated',
        description:
          'From one topic, the system plans, gathers bilingual sources, writes academic content, and exports PDF without manual intervention.',
      },
      {
        icon: '📚',
        title: 'Source-Grounded',
        description:
          'Each chapter is supported by real Vietnamese and English web content through ChromaDB. The CRAG pipeline helps reduce hallucination.',
      },
      {
        icon: '📄',
        title: 'Professional Publishing',
        description:
          'Export PDFs with Typst math, AI illustrations, automatic tables of contents, and Word files with page numbering.',
      },
    ],

    stats: [
      { value: '500+', label: 'Textbooks created' },
      { value: 'VI & EN', label: 'Bilingual sources' },
      { value: '98%', label: 'Completion rate' },
      { value: '< 30 min', label: 'Average time' },
    ],

    testimonials: [
      {
        avatar: '',
        name: 'Nguyen Van An',
        role: 'University Lecturer',
        quote:
          'The system helped me create a 200-page textbook in just 25 minutes. The content quality and PDF formatting exceeded expectations.',
      },
      {
        avatar: '',
        name: 'Tran Thi Binh',
        role: 'Independent Researcher',
        quote:
          'The CRAG pipeline keeps content grounded in clear sources. I trust it for my research materials.',
      },
    ],

    partner_logos: sharedAssets.partner_logos,

    cta_banner: {
      headline: 'Ready to create your first textbook?',
      button_label: 'Register free',
      button_url: '/register',
      bg_color: '#4F46E5',
    },

  },
}

export const DEFAULT_CONFIG = DEFAULT_CONFIGS.vi

function storageKey(language) {
  return `${STORAGE_KEY_PREFIX}_${language}`
}

function getDefaultConfig(language) {
  return DEFAULT_CONFIGS[language] || DEFAULT_CONFIGS.en
}

/** Deep merge: override top-level keys from stored, keep default shape. */
function mergeConfig(language, stored) {
  const defaults = getDefaultConfig(language)
  const result = {}

  for (const key of Object.keys(defaults)) {
    if (stored?.[key] != null) {
      result[key] = stored[key]
    } else {
      result[key] = defaults[key]
    }
  }

  return result
}

function migrateLegacyVietnameseConfig() {
  const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
  if (!legacy) return null

  try {
    const parsed = JSON.parse(legacy)
    localStorage.setItem(storageKey('vi'), JSON.stringify(parsed))
    return parsed
  } catch {
    return null
  }
}

export function loadConfig(language = 'en') {
  const normalizedLanguage = DEFAULT_CONFIGS[language] ? language : 'en'

  try {
    const raw = localStorage.getItem(storageKey(normalizedLanguage))

    if (!raw && normalizedLanguage === 'vi') {
      const migrated = migrateLegacyVietnameseConfig()
      if (migrated) return mergeConfig(normalizedLanguage, migrated)
    }

    if (!raw) return getDefaultConfig(normalizedLanguage)
    const stored = JSON.parse(raw)
    return mergeConfig(normalizedLanguage, stored)
  } catch {
    return getDefaultConfig(normalizedLanguage)
  }
}

export function loadLegacySiteInfo(language = 'en') {
  const normalizedLanguage = DEFAULT_CONFIGS[language] ? language : 'en'
  try {
    const raw = localStorage.getItem(storageKey(normalizedLanguage))
      || (normalizedLanguage === 'vi' ? localStorage.getItem(LEGACY_STORAGE_KEY) : null)
    if (!raw) return null
    return JSON.parse(raw)?.site_info || null
  } catch {
    return null
  }
}

export function saveConfig(language = 'en', config) {
  const normalizedLanguage = DEFAULT_CONFIGS[language] ? language : 'en'
  localStorage.setItem(storageKey(normalizedLanguage), JSON.stringify(config))
  window.dispatchEvent(
    new CustomEvent(LANDING_CONFIG_UPDATED_EVENT, {
      detail: { language: normalizedLanguage },
    }),
  )
}
