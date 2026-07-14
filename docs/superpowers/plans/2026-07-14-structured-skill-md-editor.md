# Structured SKILL.md Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefill build authors from RBAC and replace raw SKILL.md YAML/Markdown editing with a lossless structured form shared by guided, native zip, and external Agent Skill builds.

**Architecture:** Pure helpers in `skillBuilds.js` parse and compose the file without changing the backend API. A focused `SkillMdForm.vue` edits the structured draft, while `BuildWorkspace.vue` owns server synchronization and `UploadView.vue` supplies the RBAC author when guided creation begins.

**Tech Stack:** Vue 3 Composition API, Pinia, Vitest, Vue Test Utils, existing Skill Build REST API.

## Global Constraints

- Preserve the existing Build API request shape: `{ manifest, skillMd }`.
- Preserve unknown Markdown sections and additional YAML frontmatter keys.
- Never overwrite a non-empty imported author.
- Do not expose raw YAML to the normal user flow.
- Keep all three source types on the shared `BuildWorkspace` path.

---

### Task 1: Pure author and SKILL.md transformations

**Files:**
- Modify: `web/src/lib/skillBuilds.js`
- Test: `web/tests/skillBuilds.spec.js`

**Interfaces:**
- Produces: `manifestDraftFrom(manifest, defaultAuthor)`.
- Produces: `emptySkillMdDraft()`, `parseSkillMd(skillMd, manifest)`, and `composeSkillMd(fields, manifest)`.

- [ ] **Step 1: Add failing tests**

Add assertions proving that `manifestDraftFrom({}, '196045')` defaults the author, a non-empty string/object author is retained, known English/Chinese headings map into structured fields, unknown headings remain in `extra`, and composition emits quoted `name`/`description` plus retained extra frontmatter.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `npm test -- --run tests/skillBuilds.spec.js`

Expected: imports for the new helper functions fail because they do not exist.

- [ ] **Step 3: Implement the transformations**

Use the following public draft shape:

```js
{
  title: '', overview: '', inputs: '', steps: '', outputs: '',
  notes: '', examples: '', extra: '', extraFrontmatter: ''
}
```

Strip only the outer frontmatter delimiters, retain top-level keys other than `name` and `description`, recognize common bilingual `##` aliases, and serialize manifest scalars through `JSON.stringify(String(value || ''))` so the result remains valid YAML.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `npm test -- --run tests/skillBuilds.spec.js`

Expected: all `skillBuilds.spec.js` tests pass.

### Task 2: Structured editor component

**Files:**
- Create: `web/src/components/skillBuilds/SkillMdForm.vue`
- Create: `web/tests/skillMdForm.spec.js`

**Interfaces:**
- Consumes: `modelValue` with the Task 1 draft shape.
- Produces: `update:modelValue` with one immutable object per field edit.

- [ ] **Step 1: Add a failing component test**

Mount the component with populated fields, assert the eight user-facing fields render, edit “操作步骤”, and assert the emitted draft keeps other fields while updating `steps`.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `npm test -- --run tests/skillMdForm.spec.js`

Expected: module resolution fails because `SkillMdForm.vue` does not exist.

- [ ] **Step 3: Implement the component**

Render a normal text input for `title` and textareas for `overview`, `inputs`, `steps`, `outputs`, `notes`, `examples`, and `extra`. Explain that name/description YAML is generated from “基础信息”; label `extra` as a lossless area for imported custom chapters. Keep `extraFrontmatter` internal and unchanged in every emitted object.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `npm test -- --run tests/skillMdForm.spec.js`

Expected: component tests pass.

### Task 3: Shared workspace and three entry paths

**Files:**
- Modify: `web/src/views/UploadView.vue`
- Modify: `web/src/components/skillBuilds/BuildWorkspace.vue`
- Test: `web/tests/skillBuilds.spec.js`

**Interfaces:**
- Consumes: `useAuthStore().rbacInfo?.username`.
- Consumes: Task 1 parse/compose helpers and Task 2 `SkillMdForm`.
- Preserves: `patchSkillBuild(buildId, { expectedRevision, manifest, skillMd })`.

- [ ] **Step 1: Add failing author and round-trip assertions**

Test that guided initial data uses an RBAC username, imported author values remain untouched, and parse/compose output is a complete string accepted by the existing PATCH API assembly test.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `npm test -- --run tests/skillBuilds.spec.js tests/skillMdForm.spec.js`

Expected: the new integration expectation fails before the views consume the helpers.

- [ ] **Step 3: Connect the shared workflow**

In `UploadView.vue`, initialize `const auth = useAuthStore()` and call `createGuidedBuild({ author: auth.rbacInfo?.username || '' }, '')`. In `BuildWorkspace.vue`, parse every server `skillMd` in `applyBuild`, default only blank authors via `manifestDraftFrom`, render `SkillMdForm` at step 3, compose before PATCH, and retain the existing native-zip initial step 6 behavior.

- [ ] **Step 4: Verify all frontend checks**

Run: `npm test`

Run: `npm run type-check`

Run: `npm run build`

Expected: every command exits with code 0; guided/external builds start at step 1, native zip starts at step 6 and can navigate back to the populated structured editor.
