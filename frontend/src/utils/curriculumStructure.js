export function createDefaultStructure(t, structureDepth = 'level1') {
  const subsection = {
    title: t('textbook.structure.defaultSubsection', { chapter: 1, number: 1 }),
  }
  if (structureDepth === 'level2') {
    subsection.children = [
      { title: t('textbook.structure.defaultChildSubsection', { chapter: 1, section: 1, number: 1 }) },
    ]
  }
  return {
    structure_depth: structureDepth,
    chapters: [
      {
        title: t('textbook.structure.defaultChapter', { number: 1 }),
        subsections: [subsection],
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
      ;(subsection.children || []).forEach((child, childIdx) => {
        const childTitle = String(child.title || '').trim()
        if (childTitle) {
          lines.push(`#### ${chapterIdx + 1}.${subsectionIdx + 1}.${childIdx + 1} ${childTitle}`)
        }
      })
    })
  })
  return lines.join('\n')
}

export function normalizeStructureForApi(structure, targetPages = null) {
  const structureDepth = inferStructureDepth(structure)
  const normalized = {
    structure_depth: structureDepth,
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
        children: (subsection.children || []).map(child => ({
          title: String(child.title || '').trim(),
          target_pages: child.target_pages === '' || child.target_pages === undefined
            ? null
            : parseInt(child.target_pages, 10),
        })),
      })),
    })),
  }
  if (targetPages !== null && targetPages !== undefined && targetPages !== '') {
    normalized.target_pages = parseInt(targetPages, 10)
  }
  return normalized
}

export function inferStructureDepth(structure) {
  const hasChildren = (structure?.chapters || []).some(chapter => (
    (chapter.subsections || []).some(subsection => (
      (subsection.children || []).some(child => String(child.title || '').trim())
    ))
  ))
  if (hasChildren) return 'level2'
  return 'level1'
}

export function getMissingChildSections(structure) {
  if (inferStructureDepth(structure) !== 'level2') return []
  const missing = []
  ;(structure?.chapters || []).forEach((chapter, chapterIdx) => {
    ;(chapter.subsections || []).forEach((subsection, subIdx) => {
      const children = (subsection.children || []).filter(child => String(child.title || '').trim())
      if (!children.length) {
        missing.push({
          chapter: chapterIdx + 1,
          section: subIdx + 1,
          label: `${chapterIdx + 1}.${subIdx + 1}`,
          title: String(subsection.title || '').trim(),
        })
      }
    })
  })
  return missing
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

function isGeneratedChildSubsectionTitle(title, chapterIdx, subIdx, childIdx, t) {
  const normalized = normalizeTitleForValidation(title)
  const expected = normalizeTitleForValidation(
    t('textbook.structure.defaultChildSubsection', {
      chapter: chapterIdx + 1,
      section: subIdx + 1,
      number: childIdx + 1,
    })
  )
  return (
    normalized === expected ||
    /^tiểu mục\s+\d+\.\d+\.\d+\s+mới$/i.test(normalized) ||
    /^new\s+subsection\s+\d+\.\d+\.\d+$/i.test(normalized)
  )
}

export function validateStructure(structure, t) {
  const structureDepth = structure?.structure_depth || 'level1'
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
      if (structureDepth === 'level2') {
        const children = subsections[subIdx].children || []
        if (!children.length) {
          return t('textbook.structure.errors.emptyChildSection', {
            chapter: chapterIdx + 1,
            section: subIdx + 1,
          })
        }
        for (let childIdx = 0; childIdx < children.length; childIdx += 1) {
          if (!String(children[childIdx].title || '').trim()) {
            return t('textbook.structure.errors.blankChildSubsection', {
              chapter: chapterIdx + 1,
              section: subIdx + 1,
              number: childIdx + 1,
            })
          }
          if (isGeneratedChildSubsectionTitle(children[childIdx].title, chapterIdx, subIdx, childIdx, t)) {
            return t('textbook.structure.errors.defaultChildSubsection', {
              chapter: chapterIdx + 1,
              section: subIdx + 1,
              number: childIdx + 1,
            })
          }
        }
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

    ;(chapter.subsections || []).forEach((subsection, subIdx) => {
      const subsectionPages = parseOptionalPage(subsection?.target_pages)
      if (!subsectionPages) return
      const childTotal = (subsection.children || []).reduce((sum, child) => {
        const pages = parseOptionalPage(child?.target_pages)
        return sum + (pages || 0)
      }, 0)
      if (childTotal > subsectionPages) {
        issues.push(t('textbook.structure.errors.childPagesExceedSubsection', {
          subsection: `${chapterIdx + 1}.${subIdx + 1}`,
          allocated: childTotal,
          target: subsectionPages,
        }))
      }
    })
  })
  return issues
}

export function countLeafSubsections(chapters) {
  return (chapters || []).reduce((total, chapter) => (
    total + (chapter.subsections || []).reduce((chapterTotal, subsection) => {
      const children = subsection.children || []
      return chapterTotal + (children.length > 0 ? children.length : 1)
    }, 0)
  ), 0)
}
