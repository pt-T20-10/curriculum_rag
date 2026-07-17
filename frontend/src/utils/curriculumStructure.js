export function createDefaultStructure(t) {
  return {
    chapters: [
      {
        title: t('textbook.structure.defaultChapter', { number: 1 }),
        subsections: [
          { title: t('textbook.structure.defaultSubsection', { chapter: 1, number: 1 }) },
        ],
      },
    ],
  }
}

export function serializeStructureToMarkdown(structure) {
  const lines = []
  ;(structure?.chapters || []).forEach((chapter, chapterIdx) => {
    const chapterTitle = String(chapter.title || '').trim()
    if (!chapterTitle) return
    lines.push(`## ${chapterTitle}`)
    ;(chapter.subsections || []).forEach((subsection, subsectionIdx) => {
      const title = String(subsection.title || '').trim()
      if (title) {
        lines.push(`### ${chapterIdx + 1}.${subsectionIdx + 1} ${title}`)
      }
    })
  })
  return lines.join('\n')
}

export function normalizeStructureForApi(structure, targetPages = null) {
  const normalized = {
    chapters: (structure?.chapters || []).map(chapter => ({
      title: String(chapter.title || '').trim(),
      target_pages: chapter.target_pages === '' || chapter.target_pages === undefined
        ? null
        : parseInt(chapter.target_pages, 10),
      subsections: (chapter.subsections || []).map(subsection => ({
        title: String(subsection.title || '').trim(),
        target_pages: subsection.target_pages === '' || subsection.target_pages === undefined
          ? null
          : parseInt(subsection.target_pages, 10),
      })),
    })),
  }
  if (targetPages !== null && targetPages !== undefined && targetPages !== '') {
    normalized.target_pages = parseInt(targetPages, 10)
  }
  return normalized
}

function normalizeTitleForValidation(value) {
  return String(value || '')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase()
}

function isGeneratedChapterTitle(title, chapterIdx, t) {
  const normalized = normalizeTitleForValidation(title)
  const expected = normalizeTitleForValidation(
    t('textbook.structure.defaultChapter', { number: chapterIdx + 1 })
  )
  return (
    normalized === expected ||
    /^chương\s+\d+\s+mới$/i.test(normalized) ||
    /^new\s+chapter\s+\d+$/i.test(normalized)
  )
}

function isGeneratedSubsectionTitle(title, chapterIdx, subIdx, t) {
  const normalized = normalizeTitleForValidation(title)
  const expected = normalizeTitleForValidation(
    t('textbook.structure.defaultSubsection', {
      chapter: chapterIdx + 1,
      number: subIdx + 1,
    })
  )
  return (
    normalized === expected ||
    /^mục\s+\d+\.\d+\s+mới$/i.test(normalized) ||
    /^new\s+section\s+\d+\.\d+$/i.test(normalized)
  )
}

export function validateStructure(structure, t) {
  const chapters = structure?.chapters || []
  if (!chapters.length) {
    return t('textbook.structure.errors.empty')
  }
  for (let chapterIdx = 0; chapterIdx < chapters.length; chapterIdx += 1) {
    const chapter = chapters[chapterIdx]
    if (!String(chapter.title || '').trim()) {
      return t('textbook.structure.errors.blankChapter', { number: chapterIdx + 1 })
    }
    if (isGeneratedChapterTitle(chapter.title, chapterIdx, t)) {
      return t('textbook.structure.errors.defaultChapter', { number: chapterIdx + 1 })
    }
    const subsections = chapter.subsections || []
    if (!subsections.length) {
      return t('textbook.structure.errors.emptyChapter', { number: chapterIdx + 1 })
    }
    for (let subIdx = 0; subIdx < subsections.length; subIdx += 1) {
      if (!String(subsections[subIdx].title || '').trim()) {
        return t('textbook.structure.errors.blankSubsection', {
          chapter: chapterIdx + 1,
          number: subIdx + 1,
        })
      }
      if (isGeneratedSubsectionTitle(subsections[subIdx].title, chapterIdx, subIdx, t)) {
        return t('textbook.structure.errors.defaultSubsection', {
          chapter: chapterIdx + 1,
          number: subIdx + 1,
        })
      }
    }
  }
  return ''
}

function parseOptionalPage(value) {
  if (value === '' || value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function getChapterPageBudgetIssues(chapters, t) {
  const issues = []
  ;(chapters || []).forEach((chapter, chapterIdx) => {
    const chapterPages = parseOptionalPage(chapter?.target_pages)
    if (!chapterPages) return

    const subsectionTotal = (chapter.subsections || []).reduce((sum, subsection) => {
      const pages = parseOptionalPage(subsection?.target_pages)
      return sum + (pages || 0)
    }, 0)

    if (subsectionTotal > chapterPages) {
      issues.push(t('textbook.structure.errors.subsectionPagesExceedChapter', {
        chapter: chapterIdx + 1,
        allocated: subsectionTotal,
        target: chapterPages,
      }))
    }
  })
  return issues
}
