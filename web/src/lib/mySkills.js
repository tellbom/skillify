// Pure helpers for the C-2 "my skills" workspace (MySkillsView.vue). Kept separate from the
// component so the lookup/formatting logic is unit-testable without mounting Vue (see
// web/src/lib/versions.js for the pattern this follows).

/**
 * Look up a skill's install count from MyUsageStats.installsBySkill, which is keyed by
 * "namespace/name" strings. Returns 0 when usage data hasn't loaded yet or the skill has no
 * recorded installs, so callers never have to null-check.
 * @param {{installsBySkill?: Record<string, number>}} usage
 * @param {{namespace: string, name: string}} skill
 */
export function installCountFor(usage, skill) {
  const key = `${skill.namespace}/${skill.name}`
  return usage?.installsBySkill?.[key] ?? 0
}

/**
 * Build the query params for the "retry upload" deep link into UploadView, carrying just
 * enough context (namespace/name/version) for the hint text — the user still has to re-select
 * the zip file themselves, this is not an implicit resume (per Task 4's design decision).
 * @param {{namespace: string, name: string, version: string}} job
 */
export function retryQueryFor(job) {
  return { retryNamespace: job.namespace, retryName: job.name, retryVersion: job.version }
}
