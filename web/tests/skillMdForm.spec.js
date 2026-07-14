// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SkillMdForm from '../src/components/skillBuilds/SkillMdForm.vue'

const draft = {
  title: 'CSV Cleaner',
  overview: '清理表格数据。',
  inputs: 'CSV 文件',
  steps: '1. 读取文件',
  outputs: '清理后的 CSV',
  notes: '保留原文件',
  examples: '上传 orders.csv',
  extra: '## Custom\n\n保留内容',
  extraFrontmatter: 'allowed-tools: Read',
}

describe('SkillMdForm', () => {
  it('renders eight user-facing structured fields', () => {
    const wrapper = mount(SkillMdForm, { props: { modelValue: draft } })

    expect(wrapper.findAll('[data-skill-md-field]')).toHaveLength(8)
    expect(wrapper.text()).toContain('技能用途与适用场景')
    expect(wrapper.text()).toContain('操作步骤')
    expect(wrapper.text()).toContain('其他补充内容')
    expect(wrapper.text()).toContain('系统会自动生成')
  })

  it('emits an immutable complete draft when a field changes', async () => {
    const wrapper = mount(SkillMdForm, { props: { modelValue: draft } })

    await wrapper.get('[data-skill-md-field="steps"]').setValue('1. 检查\n2. 清理')

    const next = wrapper.emitted('update:modelValue')[0][0]
    expect(next.steps).toBe('1. 检查\n2. 清理')
    expect(next.title).toBe('CSV Cleaner')
    expect(next.extraFrontmatter).toBe('allowed-tools: Read')
    expect(next).not.toBe(draft)
  })
})
