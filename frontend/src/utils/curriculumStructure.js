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
    }
  }
  return ''
}
