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
  const subsectionCounts = chapters.map(ch => (
    Array.isArray(ch?.subsections) ? ch.subsections.length : 0
  ))
  const derivedTotal = subsectionCounts.reduce((sum, count) => sum + count, 0)
  const total = toPositiveInt(totalSubsections) || derivedTotal
  const chapterIndex = chapterNumber > 0 ? chapterNumber - 1 : -1
  const previousSubsections = chapterIndex > 0
    ? subsectionCounts.slice(0, chapterIndex).reduce((sum, count) => sum + count, 0)
    : 0
  const currentChapterTotal = chapterIndex >= 0 ? (subsectionCounts[chapterIndex] || 0) : 0
  const currentGlobalSubsection = subsectionNumber > 0
    ? previousSubsections + subsectionNumber
    : previousSubsections
  const completedSubsections = subsectionNumber > 0
    ? previousSubsections + subsectionNumber - 1
    : previousSubsections

  return {
    chapterNumber,
    subsectionNumber,
    chapterIndex,
    currentChapterTotal,
    totalSubsections: total,
    currentGlobalSubsection: total ? Math.min(currentGlobalSubsection, total) : currentGlobalSubsection,
    completedSubsections: total ? Math.min(completedSubsections, total) : completedSubsections,
  }
}
