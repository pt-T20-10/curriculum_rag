function toPositiveInt(value) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0
}

export function getSubsectionProgress({
  curriculumData,
  currentChapter,
  currentSubsection,
  totalSubsections,
}) {
  const chapterNumber = toPositiveInt(currentChapter)
  const subsectionNumber = toPositiveInt(currentSubsection)
  const chapters = Array.isArray(curriculumData?.chapters) ? curriculumData.chapters : []
  const flattenChapter = (chapter) => {
    const leaves = []
    ;(chapter?.subsections || []).forEach((subsection, subIdx) => {
      const children = subsection?.children || []
      if (children.length > 0) {
        children.forEach((child, childIdx) => {
          leaves.push({
            number: `${subIdx + 1}.${childIdx + 1}`,
            title: child?.title || '',
          })
        })
      } else {
        leaves.push({
          number: `${subIdx + 1}`,
          title: subsection?.title || '',
        })
      }
    })
    return leaves
  }
  const chapterLeaves = chapters.map(ch => flattenChapter(ch))
  const subsectionCounts = chapterLeaves.map(leaves => leaves.length)
  const derivedTotal = subsectionCounts.reduce((sum, count) => sum + count, 0)
  const hasControlledLeaves = chapters.some(chapter => (
    (chapter?.subsections || []).some(subsection => (subsection?.children || []).length > 0)
  ))
  const total = hasControlledLeaves
    ? derivedTotal
    : (toPositiveInt(totalSubsections) || derivedTotal)
  const chapterIndex = chapterNumber > 0 ? chapterNumber - 1 : -1
  const previousSubsections = chapterIndex > 0
    ? subsectionCounts.slice(0, chapterIndex).reduce((sum, count) => sum + count, 0)
    : 0
  const currentChapterTotal = chapterIndex >= 0 ? (subsectionCounts[chapterIndex] || 0) : 0
  const currentLeaf = chapterIndex >= 0 && subsectionNumber > 0
    ? chapterLeaves[chapterIndex]?.[subsectionNumber - 1]
    : null
  const displaySubsectionNumber = currentLeaf
    ? `${chapterNumber}.${currentLeaf.number}`
    : (chapterNumber && subsectionNumber ? `${chapterNumber}.${subsectionNumber}` : '')
  const displaySubsectionLocalNumber = currentLeaf
    ? currentLeaf.number
    : (subsectionNumber ? `${subsectionNumber}` : '')
  const currentGlobalSubsection = subsectionNumber > 0
    ? previousSubsections + subsectionNumber
    : previousSubsections
  const completedSubsections = subsectionNumber > 0
    ? previousSubsections + subsectionNumber - 1
    : previousSubsections

  return {
    chapterNumber,
    subsectionNumber,
    displaySubsectionNumber,
    displaySubsectionLocalNumber,
    chapterIndex,
    currentChapterTotal,
    totalSubsections: total,
    currentGlobalSubsection: total ? Math.min(currentGlobalSubsection, total) : currentGlobalSubsection,
    completedSubsections: total ? Math.min(completedSubsections, total) : completedSubsections,
  }
}
