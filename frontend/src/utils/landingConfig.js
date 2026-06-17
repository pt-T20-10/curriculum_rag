const STORAGE_KEY = 'landing_page_config_v1'

export const DEFAULT_CONFIG = {
  hero: {
    headline: 'Tạo Giáo Trình AI Hoàn Chỉnh',
    subheadline:
      'Nhập một chủ đề — nhận lại giáo trình học thuật đầy đủ với chương, mục, hình minh họa DALL·E và xuất PDF chuyên nghiệp. Hoàn toàn tự động.',
    cta_primary_label: 'Bắt đầu miễn phí',
    cta_primary_url: '/register',
    cta_secondary_label: 'Đăng nhập',
    cta_secondary_url: '/login',
    bg_type: 'gradient', // 'gradient' | 'image'
    bg_image_url:
      'https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?w=1920&q=80',
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

  cta_banner: {
    headline: 'Sẵn sàng tạo giáo trình đầu tiên của bạn?',
    button_label: 'Đăng ký miễn phí',
    button_url: '/register',
    bg_color: '#4F46E5',
  },

  footer: {
    copyright: `© ${new Date().getFullYear()} AI Textbook Generator. All rights reserved.`,
    links: [
      { label: 'Trang chủ', url: '/' },
      { label: 'Đăng nhập', url: '/login' },
      { label: 'Đăng ký', url: '/register' },
    ],
  },
}

/** Deep merge: override top-level keys from stored, keep DEFAULT_CONFIG shape */
function mergeConfig(stored) {
  const result = {}
  for (const key of Object.keys(DEFAULT_CONFIG)) {
    // Use stored value only when it is a real non-null/non-undefined value
    // (JSON.parse can produce null for keys that were explicitly set to null)
    if (stored[key] != null) {
      result[key] = stored[key]
    } else {
      result[key] = DEFAULT_CONFIG[key]
    }
  }
  return result
}

export function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_CONFIG
    const stored = JSON.parse(raw)
    return mergeConfig(stored)
  } catch {
    return DEFAULT_CONFIG
  }
}

export function saveConfig(config) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}
