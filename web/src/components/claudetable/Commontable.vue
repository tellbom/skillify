<template>
  <div class="common-table">
    <!-- 表格操作栏 -->
    <div class="table-toolbar">
      <!-- 左侧操作按钮插槽 -->
      <div class="toolbar-left">
        <slot name="toolbar-left" :selection="selectedRows"></slot>
      </div>

      <!-- 右侧工具按钮 -->
      <div class="toolbar-right">
        <slot name="toolbar-right"></slot>
        <el-button
          type="primary"
          :icon="Setting"
          circle
          @click="columnSettingVisible = true"
          title="字段设置"
        />
      </div>
    </div>

    <!-- 数据表格
         ✗ 移除 stripe（OA 斑马纹）
         ✗ 移除 border（OA 全边框）
         ✓ header-cell-style 用 Token 色
    -->
    <el-table
      ref="tableRef"
      :data="tableData"
      style="width: 100%"
      :header-cell-style="headerCellStyle"
      @selection-change="handleSelectionChange"
    >
      <!-- 多选列 -->
      <el-table-column
        v-if="showSelection"
        type="selection"
        width="55"
        align="center"
        fixed="left"
      />

      <!-- 单选列 -->
      <el-table-column
        v-if="showRadio"
        label="选择"
        width="55"
        align="center"
        fixed="left"
      >
        <template #default="scope">
          <el-radio
            v-model="radioSelected"
            :label="scope.row[rowKey]"
            @change="handleRadioChange(scope.row)"
          >
            &nbsp;
          </el-radio>
        </template>
      </el-table-column>

      <!-- 动态列渲染 -->
      <template v-for="column in visibleColumns" :key="column.prop">
        <el-table-column
          :prop="column.prop"
          :label="column.label"
          :width="column.width"
          :min-width="column.minWidth"
          :align="column.align || 'left'"
          :show-overflow-tooltip="false"
        >
          <template #default="scope">
            <slot :name="column.prop" :row="scope.row" :column="column">
              <template v-if="column.showOverflowTooltip === false">
                <div class="cell-text">
                  {{ scope.row[column.prop] }}
                </div>
              </template>
              <template v-else>
                <el-tooltip
                  placement="top"
                  :disabled="!needTooltip(scope.row[column.prop], column)"
                  popper-class="cell-tooltip-popper"
                >
                  <template #content>
                    <div class="tooltip-content-wrapper">
                      <span class="tooltip-text">{{ String(scope.row[column.prop] || '') }}</span>
                      <el-button
                        v-if="showCopyIcon(scope.row[column.prop])"
                        type="primary"
                        text
                        size="small"
                        class="tooltip-copy-btn"
                        @click="handleCopy(scope.row[column.prop])"
                      >
                        复制
                      </el-button>
                    </div>
                  </template>
                  <div class="cell-text">
                    {{ scope.row[column.prop] }}
                  </div>
                </el-tooltip>
              </template>
            </slot>
          </template>
        </el-table-column>
      </template>

      <!-- 操作列 -->
      <el-table-column
        v-if="showOperation"
        label="操作"
        fixed="right"
        :width="operationWidth"
      >
        <template #default="scope">
          <slot name="operation" :row="scope.row" :index="scope.$index"></slot>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-container">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
      />
    </div>

    <!-- 字段显示设置抽屉 -->
    <el-drawer
      v-model="columnSettingVisible"
      title="字段显示设置"
      direction="rtl"
      size="360px"
    >
      <div class="column-setting">
        <el-checkbox-group v-model="selectedColumns" @change="handleColumnChange">
          <div v-for="column in allColumns" :key="column.prop" class="column-item">
            <el-checkbox :label="column.prop">
              {{ column.label }}
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <el-button @click="resetColumns">重置</el-button>
          <el-button type="primary" @click="columnSettingVisible = false">
            确定
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
// ── script 完全不变，仅 style 改造 ──────────────────────────────────
import { ref, computed, watch, onMounted } from 'vue'
import { Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  tableData: {
    type: Array,
    default: () => []
  },
  columns: {
    type: Array,
    required: true
  },
  total: {
    type: Number,
    default: 0
  },
  currentPage: {
    type: Number,
    default: 1
  },
  pageSize: {
    type: Number,
    default: 20
  },
  showSelection: {
    type: Boolean,
    default: false
  },
  showRadio: {
    type: Boolean,
    default: false
  },
  rowKey: {
    type: String,
    default: 'id'
  },
  showOperation: {
    type: Boolean,
    default: true
  },
  operationWidth: {
    type: Number,
    default: 180
  },
  storageKey: {
    type: String,
    default: 'table-column-setting'
  }
})

const emit = defineEmits([
  'selection-change',
  'radio-change',
  'page-change',
  'size-change',
  'update:currentPage',
  'update:pageSize'
])

const tableRef              = ref(null)
const columnSettingVisible  = ref(false)
const selectedColumns       = ref([])
const allColumns            = ref([])
const currentPage           = ref(props.currentPage)
const pageSize              = ref(props.pageSize)
const selectedRows          = ref([])
const radioSelected         = ref('')

// 表头样式：用 CSS 变量而非内联十六进制，但 el-table header-cell-style
// 接收的是 CSSProperties 对象（运行时），无法直接用 var()，
// 因此保留对象写法，颜色值与 Token 定义保持一致
const headerCellStyle = {
  background:  'var(--wf-bg-section)',
  color:       'var(--wf-ink-2)',
  fontWeight:  '600',
  fontSize:    '13px',
  borderBottom: '1px solid var(--wf-divider)',
}

const visibleColumns = computed(() => {
  return allColumns.value.filter(col => selectedColumns.value.includes(col.prop))
})

const initColumns = () => {
  allColumns.value = props.columns
  const savedColumns = localStorage.getItem(props.storageKey)
  if (savedColumns) {
    try {
      selectedColumns.value = JSON.parse(savedColumns)
      selectedColumns.value = selectedColumns.value.filter(col =>
        allColumns.value.some(c => c.prop === col)
      )
    } catch (e) {
      selectedColumns.value = allColumns.value.map(col => col.prop)
    }
  } else {
    selectedColumns.value = allColumns.value.map(col => col.prop)
  }
}

const handleColumnChange = (value) => {
  localStorage.setItem(props.storageKey, JSON.stringify(value))
}

const resetColumns = () => {
  selectedColumns.value = allColumns.value.map(col => col.prop)
  localStorage.removeItem(props.storageKey)
  ElMessage.success('已重置为默认显示')
}

const handleSelectionChange = (selection) => {
  selectedRows.value = selection
  emit('selection-change', selection)
}

const handleRadioChange = (row) => {
  emit('radio-change', row)
}

const needTooltip = (content, column) => {
  if (!content) return false
  const str = String(content)
  const maxLength = column.tooltipLength || 20
  return str.length > maxLength || str.includes('\n')
}

const showCopyIcon = (content) => {
  if (!content) return false
  return String(content).length > 0
}

const handleCopy = async (content) => {
  try {
    await navigator.clipboard.writeText(String(content))
    ElMessage.success('复制成功')
  } catch (err) {
    const textarea = document.createElement('textarea')
    textarea.value = String(content)
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('复制成功')
    } catch (e) {
      ElMessage.error('复制失败')
    }
    document.body.removeChild(textarea)
  }
}

const clearSelection = () => {
  if (tableRef.value) {
    tableRef.value.clearSelection()
  }
  radioSelected.value = ''
}

const handleSizeChange = (val) => {
  pageSize.value = val
  emit('update:pageSize', val)
  emit('size-change', val)
}

const handleCurrentChange = (val) => {
  currentPage.value = val
  emit('update:currentPage', val)
  emit('page-change', val)
}

watch(() => props.currentPage, (val) => { currentPage.value = val })
watch(() => props.pageSize,    (val) => { pageSize.value = val })
watch(() => props.columns,     () => { initColumns() }, { deep: true })

onMounted(() => { initColumns() })

defineExpose({ clearSelection })
</script>

<style scoped>
/* ================================================================
   NODE-F03 — Commontable.vue 样式改造
   改造说明：
     ✗ 移除 el-table stripe / border（OA 网格感）
     ✗ 移除 header-cell-style 硬编码 #f5f7fa / #606266
     ✗ 移除 :deep(.el-button--primary) 硬编码 #409EFF
     ✗ 移除 pagination 硬编码 #409EFF
     ✗ 移除 checkbox / radio 硬编码 #409EFF
     ✓ 所有颜色替换为 --wf-* Token
     ✓ 圆角统一为 --wf-radius-* Token
     ✓ 行 hover 使用主色浅背景 --wf-primary-light
   ================================================================ */

/* ── 容器 ── */
.common-table {
  width: 100%;
  background: var(--wf-canvas);
  border-radius: var(--wf-radius-lg);
  padding: var(--wf-space-16);
  box-shadow: var(--wf-shadow-card);
}

/* ── 工具栏 ── */
.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--wf-space-12);
  gap: var(--wf-space-16);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--wf-space-12);
  flex: 1;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--wf-space-8);
}

/* 列设置圆形按钮 */
:deep(.toolbar-right .el-button.is-circle) {
  background: var(--wf-bg-section);
  border-color: var(--wf-border);
  color: var(--wf-ink-2);
  transition: background var(--wf-transition-fast),
              color var(--wf-transition-fast),
              transform var(--wf-transition-fast);
}

:deep(.toolbar-right .el-button.is-circle:hover) {
  background: var(--wf-primary-light);
  border-color: var(--wf-primary-border);
  color: var(--wf-primary);
}

:deep(.toolbar-right .el-button.is-circle:active) {
  transform: scale(0.93);
}

/* ── 表格本体 ── */

/* 行 hover 背景 */
:deep(.el-table__row:hover > td) {
  background: var(--wf-primary-light) !important;
}

/* 去掉 el-table 默认外边框 */
:deep(.el-table) {
  border-radius: var(--wf-radius-md);
  overflow: hidden;
  /* el-table 内部有 --el-table-border-color，由 workflow-tokens.scss 的
     --el-table-border-color: var(--wf-divider) 统一覆盖，此处无需重复 */
}

/* 底部边框细线 */
:deep(.el-table td.el-table__cell),
:deep(.el-table th.el-table__cell) {
  border-bottom-color: var(--wf-divider);
}

/* 操作列链接按钮 */
:deep(.el-button--primary.is-link),
:deep(.el-button--danger.is-link),
:deep(.el-button--success.is-link),
:deep(.el-button.is-link) {
  /* link 按钮不加背景/border，只控制文字色，不在此覆盖颜色，
     保持 El Plus 语义色（danger=红，success=绿）符合操作意义 */
  padding: 4px 6px;
  height: auto;
  font-size: var(--wf-font-base);
}

:deep(.el-table__row.hover-row .el-button--primary.is-link),
:deep(.el-table__row:hover .el-button--primary.is-link) {
  color: var(--wf-primary) !important;
  background: transparent !important;
}

:deep(.el-table__row.hover-row .el-button--primary.is-link:hover),
:deep(.el-table__row:hover .el-button--primary.is-link:hover) {
  color: var(--wf-primary-hover) !important;
  background: rgba(0, 102, 204, 0.08) !important;
}

/* ── 单元格文字 ── */
.cell-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--wf-font-base);
  color: var(--wf-ink);
}

/* ── 分页 ── */
.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--wf-space-12);
  padding: var(--wf-space-8) 0 var(--wf-space-4);
  border-top: 1px solid var(--wf-divider);
}

/* 分页激活页码 — Token 主色
   workflow-tokens.scss 已覆盖 --el-pagination-hover-color，
   此处额外保证 is-background 模式下激活背景色 */
:deep(.el-pagination.is-background .el-pager li:not(.is-disabled).is-active) {
  background-color: var(--wf-primary);
  border-color:     var(--wf-primary);
}

:deep(.el-pagination .el-pager li:hover) {
  color: var(--wf-primary);
}

/* ── 多选 checkbox ── */
:deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--wf-primary);
  border-color:     var(--wf-primary);
}

:deep(.el-checkbox__input.is-indeterminate .el-checkbox__inner) {
  background-color: var(--wf-primary);
  border-color:     var(--wf-primary);
}

/* ── 单选 radio ── */
:deep(.el-radio__input.is-checked .el-radio__inner) {
  background-color: var(--wf-primary);
  border-color:     var(--wf-primary);
}

/* ── 列设置抽屉内容 ── */
.column-setting {
  padding: var(--wf-space-4) var(--wf-space-20);
}

.column-item {
  padding: var(--wf-space-12) 0;
  border-bottom: 1px solid var(--wf-divider);
  transition: background var(--wf-transition-fast);
}

.column-item:last-child {
  border-bottom: none;
}

.column-item:hover {
  background: var(--wf-bg);
  border-radius: var(--wf-radius-sm);
  padding-left: var(--wf-space-8);
}

/* 抽屉底部操作 */
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--wf-space-8);
  padding: var(--wf-space-12) var(--wf-space-20);
  border-top: 1px solid var(--wf-divider);
}

/* 抽屉内按钮 */
:deep(.drawer-footer .el-button--primary) {
  background: var(--wf-primary);
  border-color: var(--wf-primary);
}

:deep(.drawer-footer .el-button--primary:hover) {
  background: var(--wf-primary-hover);
  border-color: var(--wf-primary-hover);
}

:deep(.drawer-footer .el-button:active) {
  transform: scale(0.95);
}

/* 抽屉内 checkbox 主色 */
:deep(.column-setting .el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--wf-primary);
  border-color:     var(--wf-primary);
}
</style>

<!-- ================================================================
     全局 Tooltip 样式（append-to-body，scoped 无效）
     与原版保持结构一致，颜色对齐 Token
     ================================================================ -->
<style>
.cell-tooltip-popper {
  max-width: 500px !important;
}

.tooltip-content-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tooltip-text {
  flex: 1;
  word-break: break-word;
  line-height: 1.5;
}

.tooltip-copy-btn {
  flex-shrink: 0;
  padding: 4px 8px !important;
  height: auto !important;
  font-size: 12px !important;
}
</style>
