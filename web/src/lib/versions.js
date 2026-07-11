// Pure helpers for the C-1 version-center UI (SkillDetailView.vue's version timeline + diff
// panel). Kept separate from the component so the sorting/grouping logic is unit-testable
// without mounting Vue (see web/tests/dynamicRoutes.spec.js for the pattern this follows).

/**
 * Sort VersionInfo[] (from GET /skills/{ns}/{name}/versions) newest-first for timeline display.
 * Falls back to string comparison if publishedAt is missing/unparseable, so a malformed date
 * never throws — it just sorts to one end.
 * @param {Array<{version: string, publishedAt: string, yanked: boolean, releaseNotes: string|null}>} versions
 */
export function sortVersionsDesc(versions) {
  return [...(versions || [])].sort((a, b) => {
    const ta = Date.parse(a?.publishedAt)
    const tb = Date.parse(b?.publishedAt)
    if (Number.isNaN(ta) || Number.isNaN(tb)) return (b?.version || '').localeCompare(a?.version || '')
    return tb - ta
  })
}

/**
 * Group a VersionDiff ({added, removed, modified}: string[] file paths) into display rows,
 * sorted alphabetically within each group so the UI is deterministic regardless of backend
 * ordering. Returns [] for an empty/missing group rather than undefined.
 * @param {{added?: string[], removed?: string[], modified?: string[]}} diff
 */
export function groupDiff(diff) {
  return {
    added: [...(diff?.added || [])].sort(),
    removed: [...(diff?.removed || [])].sort(),
    modified: [...(diff?.modified || [])].sort(),
  }
}

/** True when a VersionDiff has no changes in any of the three groups. */
export function isDiffEmpty(diff) {
  return !diff?.added?.length && !diff?.removed?.length && !diff?.modified?.length
}
