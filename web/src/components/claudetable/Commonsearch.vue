<template>
  <div class="common-search">
    <el-form
      ref="formRef"
      :model="searchForm"
      :inline="true"
      class="search-form"
      @submit.prevent="handleSearch"
    >
      <!-- 动态渲染搜索字段 -->
      <template v-for="field in visibleFields" :key="field.prop">
        <el-form-item :label="field.label" :prop="field.prop">
          <!-- 输入框 -->
          <el-input
            v-if="field.type === 'input'"
            v-model="searchForm[field.prop]"
            :placeholder="field.placeholder || `请输入${field.label}`"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '200px' }"
            @keyup.enter="handleSearch"
          >
            <template v-if="field.prepend" #prepend>{{ field.prepend }}</template>
            <template v-if="field.append" #append>{{ field.append }}</template>
          </el-input>

          <!-- 下拉选择 -->
          <el-select
            v-else-if="field.type === 'select'"
            v-model="searchForm[field.prop]"
            :placeholder="field.placeholder || `请选择${field.label}`"
            :clearable="field.clearable !== false"
            :multiple="field.multiple"
            :style="{ width: field.width || '200px' }"
          >
            <el-option
              v-for="option in field.options"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <!-- 日期选择 -->
          <el-date-picker
            v-else-if="field.type === 'date'"
            v-model="searchForm[field.prop]"
            type="date"
            :placeholder="field.placeholder || `请选择${field.label}`"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '200px' }"
            value-format="YYYY-MM-DD"
          />

          <!-- 日期范围选择 -->
          <el-date-picker
            v-else-if="field.type === 'daterange'"
            v-model="searchForm[field.prop]"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '240px' }"
            value-format="YYYY-MM-DD"
          />

          <!-- 日期时间选择 -->
          <el-date-picker
            v-else-if="field.type === 'datetime'"
            v-model="searchForm[field.prop]"
            type="datetime"
            :placeholder="field.placeholder || `请选择${field.label}`"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '220px' }"
            value-format="YYYY-MM-DD HH:mm:ss"
          />

          <!-- 日期时间范围选择 -->
          <el-date-picker
            v-else-if="field.type === 'datetimerange'"
            v-model="searchForm[field.prop]"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '360px' }"
            value-format="YYYY-MM-DD HH:mm:ss"
          />

          <!-- 数字输入 -->
          <el-input-number
            v-else-if="field.type === 'number'"
            v-model="searchForm[field.prop]"
            :placeholder="field.placeholder || `请输入${field.label}`"
            :style="{ width: field.width || '200px' }"
            :min="field.min"
            :max="field.max"
            :step="field.step || 1"
            :precision="field.precision"
          />

          <!-- 数字范围 -->
          <div v-else-if="field.type === 'numberrange'" class="number-range">
            <el-input-number
              v-model="searchForm[field.prop][0]"
              :placeholder="field.startPlaceholder || '最小值'"
              :style="{ width: field.width ? `calc(${field.width} / 2 - 12px)` : '94px' }"
              :min="field.min"
              :max="field.max"
              :step="field.step || 1"
              :precision="field.precision"
            />
            <span class="range-separator">-</span>
            <el-input-number
              v-model="searchForm[field.prop][1]"
              :placeholder="field.endPlaceholder || '最大值'"
              :style="{ width: field.width ? `calc(${field.width} / 2 - 12px)` : '94px' }"
              :min="field.min"
              :max="field.max"
              :step="field.step || 1"
              :precision="field.precision"
            />
          </div>

          <!-- 级联选择 -->
          <el-cascader
            v-else-if="field.type === 'cascader'"
            v-model="searchForm[field.prop]"
            :options="field.options"
            :placeholder="field.placeholder || `请选择${field.label}`"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '200px' }"
            :props="field.props"
          />

          <!-- 树形选择 -->
          <el-tree-select
            v-else-if="field.type === 'treeselect'"
            v-model="searchForm[field.prop]"
            :data="field.options"
            :placeholder="field.placeholder || `请选择${field.label}`"
            :clearable="field.clearable !== false"
            :style="{ width: field.width || '200px' }"
            :props="field.props"
          />

          <!-- 自定义插槽 -->
          <slot 
            v-else-if="field.type === 'slot'" 
            :name="field.prop" 
            :field="field"
            :form="searchForm"
          ></slot>
        </el-form-item>
      </template>

      <!-- 操作按钮 -->
      <el-form-item class="search-buttons">
        <el-button type="primary" :icon="Search" @click="handleSearch">
          搜索
        </el-button>
        <el-button :icon="Refresh" @click="handleReset">
          重置
        </el-button>
        <el-button
          v-if="collapsible && fields.length > collapseCount"
          type="text"
          :icon="isExpanded ? ArrowUp : ArrowDown"
          @click="toggleExpand"
          class="expand-btn"
        >
          {{ isExpanded ? '收起' : '展开' }}
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Search, Refresh, ArrowUp, ArrowDown } from '@element-plus/icons-vue'

// Props定义
const props = defineProps({
  // 搜索字段配置
  fields: {
    type: Array,
    required: true,
    default: () => []
  },
  // 是否可折叠
  collapsible: {
    type: Boolean,
    default: true
  },
  // 折叠时显示的字段数量
  collapseCount: {
    type: Number,
    default: 3
  },
  // 默认是否展开
  defaultExpanded: {
    type: Boolean,
    default: false
  },
  // 初始搜索值
  modelValue: {
    type: Object,
    default: () => ({})
  }
})

// Emits定义
const emit = defineEmits(['update:modelValue', 'search', 'reset'])

// 响应式数据
const formRef = ref(null)
const searchForm = ref({})
const isExpanded = ref(props.defaultExpanded)

// 初始化表单数据
const initFormData = () => {
  const formData = {}
  props.fields.forEach(field => {
    if (field.type === 'numberrange') {
      formData[field.prop] = props.modelValue[field.prop] || [null, null]
    } else if (field.type === 'daterange' || field.type === 'datetimerange') {
      formData[field.prop] = props.modelValue[field.prop] || []
    } else if (field.multiple) {
      formData[field.prop] = props.modelValue[field.prop] || []
    } else {
      formData[field.prop] = props.modelValue[field.prop] || (field.defaultValue !== undefined ? field.defaultValue : '')
    }
  })
  searchForm.value = formData
}

// 计算可见字段
const visibleFields = computed(() => {
  if (!props.collapsible || isExpanded.value || props.fields.length <= props.collapseCount) {
    return props.fields
  }
  return props.fields.slice(0, props.collapseCount)
})

// 切换展开/收起
const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
}

// 搜索
const handleSearch = () => {
  // 清理空值
  const cleanedForm = {}
  Object.keys(searchForm.value).forEach(key => {
    const value = searchForm.value[key]
    if (value !== '' && value !== null && value !== undefined) {
      // 处理数组类型
      if (Array.isArray(value)) {
        if (value.length > 0) {
          // 数字范围特殊处理
          if (props.fields.find(f => f.prop === key)?.type === 'numberrange') {
            if (value[0] !== null || value[1] !== null) {
              cleanedForm[key] = value
            }
          } else {
            cleanedForm[key] = value
          }
        }
      } else {
        cleanedForm[key] = value
      }
    }
  })
  
  emit('update:modelValue', cleanedForm)
  emit('search', cleanedForm)
}

// 重置
const handleReset = () => {
  if (formRef.value) {
    formRef.value.resetFields()
  }
  
  // 重置为默认值
  const resetData = {}
  props.fields.forEach(field => {
    if (field.type === 'numberrange') {
      resetData[field.prop] = [null, null]
    } else if (field.type === 'daterange' || field.type === 'datetimerange') {
      resetData[field.prop] = []
    } else if (field.multiple) {
      resetData[field.prop] = []
    } else {
      resetData[field.prop] = field.defaultValue !== undefined ? field.defaultValue : ''
    }
  })
  
  searchForm.value = resetData
  emit('update:modelValue', {})
  emit('reset')
}

// 监听fields变化重新初始化
watch(() => props.fields, () => {
  initFormData()
}, { deep: true, immediate: true })

// 监听外部modelValue变化
watch(() => props.modelValue, (newVal) => {
  if (newVal && Object.keys(newVal).length > 0) {
    Object.keys(newVal).forEach(key => {
      if (searchForm.value.hasOwnProperty(key)) {
        searchForm.value[key] = newVal[key]
      }
    })
  }
}, { deep: true })

// 暴露方法供父组件调用
defineExpose({
  handleSearch,
  handleReset,
  getFormData: () => searchForm.value
})
</script>

<style scoped>
.common-search {
  background: var(--wf-canvas);
  border-radius: var(--wf-radius-lg);
  padding: var(--wf-space-20) var(--wf-space-24);
  margin-bottom: var(--wf-space-16);
  box-shadow: var(--wf-shadow-card);
  transition: box-shadow var(--wf-transition-base);
}

.search-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
}

:deep(.el-form-item) {
  margin-right: var(--wf-space-16);
  margin-bottom: var(--wf-space-16);
}

:deep(.el-form-item__label) {
  font-weight: var(--wf-font-weight-medium);
  color: var(--wf-ink-2);
  font-size: var(--wf-font-md);
}

.search-buttons {
  display: flex;
  align-items: center;
  gap: var(--wf-space-8);
}

.expand-btn {
  margin-left: var(--wf-space-4);
  padding: var(--wf-space-8) var(--wf-space-12);
  font-size: var(--wf-font-base);
  color: var(--wf-ink-3);
  transition: color var(--wf-transition-fast);
}

.expand-btn:hover {
  color: var(--wf-primary);
}

.number-range {
  display: flex;
  align-items: center;
  gap: var(--wf-space-8);
}

.range-separator {
  color: var(--wf-ink-3);
  font-weight: var(--wf-font-weight-medium);
}

:deep(.el-input__wrapper) {
  border-radius: var(--wf-radius-sm);
  box-shadow: 0 0 0 1px var(--wf-border) inset;
  transition: box-shadow var(--wf-transition-fast);
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--wf-ink-disabled) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1.5px var(--wf-primary) inset;
}

:deep(.el-select .el-input__wrapper),
:deep(.el-date-editor),
:deep(.el-input-number) {
  border-radius: var(--wf-radius-sm);
}

:deep(.el-button) {
  border-radius: var(--wf-radius-sm);
  font-weight: var(--wf-font-weight-medium);
  padding: 9px 20px;
  transition:
    background var(--wf-transition-fast),
    color var(--wf-transition-fast),
    border-color var(--wf-transition-fast),
    transform var(--wf-transition-fast);
}

:deep(.el-button--primary) {
  background: var(--wf-primary);
  border-color: var(--wf-primary);
}

:deep(.el-button--primary:hover) {
  background: var(--wf-primary-hover);
  border-color: var(--wf-primary-hover);
}

:deep(.el-button--primary:active),
:deep(.el-button:not(.el-button--primary):active) {
  transform: scale(0.95);
}

:deep(.el-button:not(.el-button--primary):not(.el-button--text)) {
  background: var(--wf-bg-section);
  border: 1px solid var(--wf-border);
  color: var(--wf-ink-2);
}

:deep(.el-button:not(.el-button--primary):not(.el-button--text):hover) {
  background: var(--wf-primary-light);
  border-color: var(--wf-primary-border);
  color: var(--wf-primary);
}
</style>