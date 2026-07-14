<script setup>
const props = defineProps({
  modelValue: { type: Object, required: true },
})
const emit = defineEmits(['update:modelValue'])

const textareas = [
  { key: 'overview', label: '技能用途与适用场景', placeholder: '说明这个技能解决什么问题，以及 Agent 应在什么情况下使用它。', rows: 4 },
  { key: 'inputs', label: '输入要求', placeholder: '说明需要用户提供哪些文件、数据或参数；没有特殊要求可以留空。', rows: 3 },
  { key: 'steps', label: '操作步骤', placeholder: '按顺序写明 Agent 应如何执行，例如：\n1. 检查输入文件\n2. 处理数据\n3. 核对结果', rows: 7 },
  { key: 'outputs', label: '输出要求', placeholder: '说明最终要返回什么内容、文件或格式。', rows: 3 },
  { key: 'notes', label: '注意事项', placeholder: '填写限制条件、安全要求、禁止操作或异常处理方式。', rows: 4 },
  { key: 'examples', label: '使用示例', placeholder: '给出一个用户请求示例，以及期望的处理结果。', rows: 5 },
  { key: 'extra', label: '其他补充内容', placeholder: '上传或导入文件中无法自动归类的自定义章节会完整保留在这里。', rows: 7 },
]

function updateField(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <div class="skill-md-form">
    <div class="generated-note">
      <strong>无需编写 YAML</strong>
      <span>系统会自动生成 SKILL.md 的 name 与 description，内容来自上一步“基础信息”。</span>
    </div>

    <div class="field title-field">
      <label for="skill-md-title">技能标题</label>
      <input
        id="skill-md-title"
        data-skill-md-field="title"
        type="text"
        :value="modelValue.title"
        placeholder="例如：CSV 数据清理"
        @input="updateField('title', $event.target.value)"
      />
      <small>这是 SKILL.md 正文中的展示标题，不影响稳定的技能标识。</small>
    </div>

    <div
      v-for="field in textareas"
      :key="field.key"
      class="field"
      :class="{ 'wide-field': ['steps', 'examples', 'extra'].includes(field.key) }"
    >
      <label :for="`skill-md-${field.key}`">{{ field.label }}</label>
      <textarea
        :id="`skill-md-${field.key}`"
        :data-skill-md-field="field.key"
        :rows="field.rows"
        :value="modelValue[field.key]"
        :placeholder="field.placeholder"
        @input="updateField(field.key, $event.target.value)"
      />
      <small v-if="field.key === 'extra'">该区域允许 Markdown，仅用于无损保留原文件的自定义内容；普通用户可以留空。</small>
    </div>
  </div>
</template>

<style scoped>
.skill-md-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px 22px; color: #c9c9c9; }
.generated-note { display: flex; align-items: center; grid-column: 1 / -1; padding: 12px 14px; border: 1px solid rgb(128 203 196 / 22%); border-radius: 9px; color: #9fbbb8; background: rgb(128 203 196 / 5%); font-size: 12px; gap: 10px; }
.generated-note strong { flex: none; color: #80cbc4; font-size: 12.5px; }
.field { min-width: 0; }
.field.wide-field, .title-field { grid-column: 1 / -1; }
.field label { display: block; margin-bottom: 7px; color: #d0d0d0; font-size: 13px; font-weight: 550; }
.field input, .field textarea { box-sizing: border-box; width: 100%; border: 1px solid #2c2c2c; border-radius: 8px; padding: 10px 12px; color: #e5e5e5; background: #1c1c1c; font: inherit; font-size: 13px; line-height: 1.65; outline: none; transition: border-color 0.15s ease, box-shadow 0.15s ease; }
.field input { height: 42px; }
.field textarea { min-height: 90px; resize: vertical; }
.field input:focus, .field textarea:focus { border-color: rgb(128 203 196 / 48%); box-shadow: 0 0 0 2px rgb(128 203 196 / 7%); }
.field small { display: block; margin-top: 5px; color: #6e6e6e; font-size: 11.5px; line-height: 1.45; }
@media (max-width: 760px) {
  .skill-md-form { grid-template-columns: 1fr; }
  .field, .field.wide-field, .title-field { grid-column: 1; }
  .generated-note { align-items: flex-start; flex-direction: column; }
}
</style>
