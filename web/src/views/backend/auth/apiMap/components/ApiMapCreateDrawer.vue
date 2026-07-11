<template>
    <el-drawer
        v-model="visible"
        :title="mode === 'create' ? '新增 API 映射' : '编辑 API 映射'"
        size="560px"
        direction="rtl"
        destroy-on-close
        class="apimap-form-drawer"
        :before-close="handleBeforeClose"
    >
        <div class="drawer-body">
            <div class="semantic-note">
                <i class="fa fa-info-circle note-icon" />
                <span>
                    API 映射定义运行时鉴权所需的
                    <code>HTTP route -> permissionCode/action</code>
                    关系。编辑态只允许调整权限码和动作；如需修改方法或路由，请删除后重新新增。
                </span>
            </div>

            <el-form ref="formRef" :model="formData" :rules="formRules" label-position="top" class="apimap-form" @submit.prevent>
                <el-form-item label="HTTP 方法" prop="httpMethod">
                    <el-radio-group v-model="formData.httpMethod" class="method-group" :disabled="mode === 'edit'">
                        <el-radio-button v-for="m in HTTP_METHODS" :key="m" :value="m">
                            {{ m }}
                        </el-radio-button>
                    </el-radio-group>
                    <div v-if="mode === 'edit'" class="field-hint">后端当前不支持修改 HTTP 方法。</div>
                </el-form-item>

                <el-form-item label="路由模板" prop="routePattern">
                    <el-input v-model="formData.routePattern" placeholder="/api/group/{groupCode}" clearable :disabled="mode === 'edit'">
                        <template #prepend>
                            <span class="input-prepend">路由</span>
                        </template>
                    </el-input>
                    <div class="field-hint">必须以 <code>/api/</code> 开头；路由参数使用 <code>{name}</code> 格式，不填写域名和 query string。</div>
                </el-form-item>

                <el-form-item label="权限码" prop="permissionCode">
                    <div class="perm-input-row">
                        <el-input v-model="formData.permissionCode" placeholder="menu:system.user" clearable class="perm-input" />
                        <el-popover placement="bottom-start" :width="400" trigger="click" :visible="treePickerVisible">
                            <template #reference>
                                <el-button size="small" @click="treePickerVisible = !treePickerVisible"> 从规则树选择 </el-button>
                            </template>
                            <div class="rule-tree-picker">
                                <el-input
                                    v-model="treeSearch"
                                    placeholder="搜索规则"
                                    size="small"
                                    clearable
                                    :prefix-icon="Search"
                                    class="picker-search"
                                />
                                <el-tree
                                    :data="filteredRuleTree"
                                    :props="{ label: 'title', children: 'children' }"
                                    node-key="ruleCode"
                                    highlight-current
                                    class="rule-tree"
                                    @node-click="handleTreeNodeClick"
                                >
                                    <template #default="{ node, data }">
                                        <span class="tree-node-row">
                                            <i :class="getNodeIcon(data.type)" class="node-icon" />
                                            <span class="node-title">{{ node.label }}</span>
                                            <code v-if="data.permissionCode" class="node-perm">
                                                {{ data.permissionCode }}
                                            </code>
                                        </span>
                                    </template>
                                </el-tree>
                            </div>
                        </el-popover>
                    </div>
                    <div class="field-hint">格式建议为 <code>{类型}:{scope}</code>，也可以直接输入来自 API 权限视图的权限码。</div>
                </el-form-item>

                <el-form-item label="Action" prop="action">
                    <el-select v-model="formData.action" placeholder="请选择操作语义" style="width: 100%">
                        <el-option v-for="opt in ACTION_OPTIONS" :key="opt.value" :label="`${opt.value} · ${opt.desc}`" :value="opt.value">
                            <span class="action-opt-label">{{ opt.value }}</span>
                            <span class="action-opt-desc">{{ opt.desc }}</span>
                        </el-option>
                    </el-select>
                </el-form-item>

                <div v-if="formData.httpMethod && formData.routePattern && formData.permissionCode" class="preview-block">
                    <div class="preview-title">鉴权预览</div>
                    <div class="preview-body">
                        <el-tag size="small" :type="getMethodTagType(formData.httpMethod)">
                            {{ formData.httpMethod }}
                        </el-tag>
                        <code class="preview-route">{{ formData.routePattern }}</code>
                        <span class="preview-arrow">→</span>
                        <code class="preview-perm">{{ formData.permissionCode }}</code>
                        <el-tag size="small" :type="getActionTagType(formData.action)">
                            {{ formData.action }}
                        </el-tag>
                    </div>
                </div>
            </el-form>
        </div>

        <template #footer>
            <div class="drawer-footer">
                <el-button @click="handleCancel">取消</el-button>
                <el-button type="primary" :loading="submitting" @click="handleSubmit">
                    {{ mode === 'create' ? '创建映射' : '保存修改' }}
                </el-button>
            </div>
        </template>
    </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
    createApiMap,
    updateApiMap,
    type ApiAction,
    type ApiMapCreateForm,
    type ApiMapRecordItem,
    type HttpMethod,
    type RuleTreeNode,
} from '/@/api/backend/rbac'

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'] as const
const ACTION_OPTIONS = [
    { value: 'read', desc: '读取 / 查询' },
    { value: 'create', desc: '新建资源' },
    { value: 'update', desc: '修改资源' },
    { value: 'delete', desc: '删除资源' },
    { value: 'execute', desc: '执行操作' },
    { value: 'access', desc: '进入 / 访问' },
] as const

interface Props {
    modelValue: boolean
    mode: 'create' | 'edit'
    model: ApiMapRecordItem | null
    ruleTree: RuleTreeNode[]
}

const props = withDefaults(defineProps<Props>(), {
    modelValue: false,
    mode: 'create',
    model: null,
    ruleTree: () => [],
})

const emit = defineEmits<{
    (e: 'update:modelValue', val: boolean): void
    (e: 'submit'): void
}>()

const visible = computed({
    get: () => props.modelValue,
    set: (val) => emit('update:modelValue', val),
})

interface FormData {
    httpMethod: HttpMethod
    routePattern: string
    permissionCode: string
    action: ApiAction
}

const formRef = ref()
const submitting = ref(false)
const treePickerVisible = ref(false)
const treeSearch = ref('')
const initialSnapshot = ref('')

const formData = reactive<FormData>({
    httpMethod: 'GET',
    routePattern: '',
    permissionCode: '',
    action: 'read',
})

const formRules = {
    httpMethod: [{ required: true, message: '请选择 HTTP 方法', trigger: 'change' }],
    routePattern: [
        { required: true, message: '请输入路由模板', trigger: 'blur' },
        {
            validator: (_: unknown, val: string, cb: (e?: Error) => void) => {
                if (!val.startsWith('/api/')) cb(new Error('路由模板必须以 /api/ 开头'))
                else if (val.includes('?')) cb(new Error('不要填写 query string'))
                else if (val.includes('http://') || val.includes('https://')) cb(new Error('不要填写域名'))
                else cb()
            },
            trigger: 'blur',
        },
    ],
    permissionCode: [
        { required: true, message: '请输入权限码', trigger: 'blur' },
        {
            validator: (_: unknown, val: string, cb: (e?: Error) => void) => {
                if (!val.includes(':')) cb(new Error('格式建议为 {类型}:{scope}，例如 menu:system.user'))
                else cb()
            },
            trigger: 'blur',
        },
    ],
    action: [{ required: true, message: '请选择 Action', trigger: 'change' }],
}

const filteredRuleTree = computed(() => {
    const keyword = treeSearch.value.trim()
    if (!keyword) return props.ruleTree
    return filterTree(props.ruleTree, keyword)
})

watch(
    () => [props.modelValue, props.mode, props.model],
    () => {
        if (!props.modelValue) return
        treeSearch.value = ''
        treePickerVisible.value = false

        if (props.mode === 'edit' && props.model) {
            formData.httpMethod = props.model.httpMethod
            formData.routePattern = props.model.routePattern
            formData.permissionCode = props.model.permissionCode
            formData.action = props.model.action
        } else {
            formData.httpMethod = 'GET'
            formData.routePattern = ''
            formData.permissionCode = ''
            formData.action = 'read'
        }
        initialSnapshot.value = getSnapshot()
    },
    { immediate: true }
)

function filterTree(nodes: RuleTreeNode[], keyword: string): RuleTreeNode[] {
    return nodes.reduce<RuleTreeNode[]>((acc, node) => {
        const children = filterTree(node.children ?? [], keyword)
        const match = [node.title, node.permissionCode, node.ruleCode].filter(Boolean).some((value) => String(value).includes(keyword))
        if (match || children.length) acc.push({ ...node, children })
        return acc
    }, [])
}

function handleTreeNodeClick(data: RuleTreeNode) {
    if (!data.permissionCode) return
    formData.permissionCode = data.permissionCode
    treePickerVisible.value = false
    treeSearch.value = ''
}

function getNodeIcon(type: string): string {
    return (
        {
            MenuDir: 'fa fa-folder-o',
            Menu: 'fa fa-file-o',
            Button: 'fa fa-hand-pointer-o',
        }[type] ?? 'fa fa-circle-o'
    )
}

async function handleSubmit() {
    try {
        await formRef.value?.validate()
    } catch {
        return
    }

    submitting.value = true
    try {
        if (props.mode === 'edit' && props.model) {
            await updateApiMap(props.model.id, {
                permissionCode: formData.permissionCode.trim(),
                action: formData.action,
            })
            ElMessage.success('API 映射已更新')
        } else {
            const payload: ApiMapCreateForm = {
                httpMethod: formData.httpMethod,
                routePattern: formData.routePattern.trim(),
                permissionCode: formData.permissionCode.trim(),
                action: formData.action,
            }
            await createApiMap(payload)
            ElMessage.success('API 映射创建成功')
        }

        emit('submit')
        visible.value = false
    } catch {
        // rbacClient 统一提示
    } finally {
        submitting.value = false
    }
}

function handleCancel() {
    visible.value = false
}

async function handleBeforeClose(done: () => void) {
    if (getSnapshot() === initialSnapshot.value) {
        done()
        return
    }

    try {
        await ElMessageBox.confirm('有未保存的内容，确定关闭？', '提示', {
            confirmButtonText: '关闭',
            cancelButtonText: '继续编辑',
            type: 'warning',
        })
        done()
    } catch {
        // 继续编辑
    }
}

function getSnapshot() {
    return JSON.stringify({
        httpMethod: formData.httpMethod,
        routePattern: formData.routePattern,
        permissionCode: formData.permissionCode,
        action: formData.action,
    })
}

function getActionTagType(action: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
    const map: Record<string, any> = {
        read: 'info',
        create: 'success',
        update: 'primary',
        delete: 'danger',
        execute: 'warning',
        access: 'info',
    }
    return map[action] ?? 'info'
}

function getMethodTagType(method: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
    const map: Record<string, any> = {
        GET: 'success',
        POST: 'primary',
        PUT: 'warning',
        DELETE: 'danger',
        PATCH: 'info',
    }
    return map[method] ?? 'info'
}
</script>

<style scoped>
.apimap-form-drawer {
    font-family:
        'SF Pro Text',
        system-ui,
        -apple-system,
        sans-serif;
}

.drawer-body {
    padding: 0 20px 20px;
    height: 100%;
    overflow-y: auto;
}

.semantic-note {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 14px;
    background: #f0f6ff;
    border: 1px solid #cce0ff;
    border-radius: 8px;
    margin: 16px 0 20px;
    font-size: 13px;
    color: #1d4e8a;
    line-height: 1.6;
}

.note-icon {
    color: #0066cc;
    font-size: 15px;
    margin-top: 2px;
    flex-shrink: 0;
}

code,
.node-perm,
.preview-route,
.preview-perm {
    font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.semantic-note code,
.field-hint code {
    font-size: 11px;
    background: #ddeeff;
    padding: 1px 4px;
    border-radius: 3px;
}

.apimap-form {
    padding: 4px 0;
}

.method-group {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.field-hint {
    margin-top: 5px;
    font-size: 12px;
    color: #86868b;
    line-height: 1.5;
}

.perm-input-row {
    display: flex;
    gap: 8px;
    width: 100%;
}

.perm-input {
    flex: 1;
}

.rule-tree-picker {
    padding: 4px 0;
}

.picker-search {
    margin-bottom: 8px;
}

.rule-tree {
    max-height: 280px;
    overflow-y: auto;
}

.tree-node-row {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    min-width: 0;
}

.node-icon {
    font-size: 12px;
    color: #86868b;
    flex-shrink: 0;
}

.node-title {
    font-size: 13px;
    color: #1d1d1f;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.node-perm {
    font-size: 10px;
    color: #0066cc;
    background: #f0f6ff;
    padding: 1px 4px;
    border-radius: 3px;
    flex-shrink: 0;
    max-width: 150px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.action-opt-label {
    font-family: 'SF Mono', Menlo, Consolas, monospace;
    font-size: 12px;
    font-weight: 600;
    color: #1d1d1f;
    margin-right: 10px;
}

.action-opt-desc {
    font-size: 12px;
    color: #86868b;
}

.preview-block {
    margin-top: 20px;
    padding: 14px 16px;
    background: #f5f5f7;
    border-radius: 8px;
    border: 1px solid #e5e5e5;
}

.preview-title {
    font-size: 12px;
    font-weight: 600;
    color: #86868b;
    margin-bottom: 10px;
}

.preview-body {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.preview-route,
.preview-perm {
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid #e0e0e0;
    background: #fff;
}

.preview-perm {
    color: #0066cc;
    background: #f0f6ff;
    border-color: #cce0ff;
}

.preview-arrow {
    color: #86868b;
    font-size: 14px;
}

.drawer-footer {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    padding: 16px 20px;
    border-top: 1px solid #e5e7eb;
}

:deep(.el-form-item__label) {
    font-size: 13px;
    font-weight: 600;
    color: #1d1d1f;
    margin-bottom: 6px;
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-select .el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 2px rgba(0, 102, 204, 0.2) !important;
}

:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
    background-color: #0066cc;
    border-color: #0066cc;
    box-shadow: -1px 0 0 0 #0066cc;
}

:deep(.el-button--primary) {
    background-color: #0066cc;
    border-color: #0066cc;
}

:deep(.el-button--primary:hover) {
    background-color: #0071e3;
    border-color: #0071e3;
}
</style>
