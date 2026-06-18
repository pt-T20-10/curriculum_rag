export function translateProgressText(statusText, t) {
  if (!statusText) return ''

  const chapterMatch = statusText.match(/Chương\s+(\d+)\/(\d+)\s+-\s+Mục\s+(\d+)/i)
  if (chapterMatch) {
    return t('textbook.workflow.chapterProgress', {
      chapter: chapterMatch[1],
      total: chapterMatch[2],
      subsection: chapterMatch[3],
    })
  }

  const normalized = statusText.trim()
  const exactMap = {
    'Bước 1/3: Đang lập dàn ý...': 'textbook.workflow.statusPlanning',
    'Bước 1/3: Vui lòng xem xét và xác nhận cấu trúc': 'textbook.workflow.statusReviewing',
    'Bước 2/3: Đang thu thập dữ liệu...': 'textbook.workflow.statusCollecting',
    'Bước 3/3: Đang tạo nội dung...': 'textbook.workflow.statusGenerating',
    'Bước 3/3: Đang xuất bản...': 'textbook.workflow.statusPublishing',
    'Hoàn tất!': 'textbook.workflow.statusDone',
    'Đã dừng theo yêu cầu': 'textbook.workflow.statusStopped',
  }

  return exactMap[normalized] ? t(exactMap[normalized]) : statusText
}
