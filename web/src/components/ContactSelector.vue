<template>
    <div class="contact-selector">
        <!-- 搜索栏 -->
        <div class="search-bar">
            <el-input
                v-model="searchKeyword"
                placeholder="搜索部门或人员"
                clearable
                @input="handleSearch"
            >
                <template #prefix>
                    <i class="fa fa-search"></i>
                </template>
            </el-input>
        </div>

        <div class="content-wrapper">
            <!-- 左侧：组织架构树 -->
            <div class="org-tree-section">
                <div class="section-title">组织架构</div>
                <el-tree
                    ref="orgTreeRef"
                    :data="filteredOrgTree"
                    :props="treeProps"
                    node-key="id"
                    :default-expand-all="false"
                    :expand-on-click-node="false"
                    :show-checkbox="multiple"
                    :check-strictly="false"
                    :highlight-current="true"
                    @node-click="handleOrgClick"
                    @check="handleOrgCheck"
                >
                    <template #default="{ node, data }">
                        <span class="tree-node">
                            <i class="fa fa-sitemap node-icon"></i>
                            <span class="node-label">{{ node.label }}</span>
                            <span class="node-count">({{ getOrgUserCount(data.id) }})</span>
                        </span>
                    </template>
                </el-tree>
            </div>

            <!-- 右侧：人员列表 -->
            <div class="user-list-section">
                <div class="section-header">
                    <div class="section-title">
                        {{ currentOrgName || '全部人员' }}
                        <span class="total-count">共 {{ displayTotal }} 人</span>
                    </div>
                    <div class="actions">
                        <el-button
                            v-if="multiple && selectedUsers.length > 0"
                            text
                            type="primary"
                            @click="clearSelection"
                        >
                            清空已选 ({{ selectedUsers.length }})
                        </el-button>
                    </div>
                </div>

                <div class="user-list" v-loading="loading">
                    <div v-if="paginatedUsers.length === 0" class="empty-state">
                        <el-empty description="暂无人员" />
                    </div>

                    <div
                        v-for="user in paginatedUsers"
                        :key="user.id"
                        class="user-item"
                        :class="{ selected: isUserSelected(user.id) }"
                        @click="handleUserClick(user)"
                    >
                        <el-checkbox
                            v-if="multiple"
                            :model-value="isUserSelected(user.id)"
                            @change="(val) => handleUserCheckChange(val, user)"
                            @click.stop
                        />
                        <div class="user-avatar">
                            <i class="fa fa-user"></i>
                        </div>
                        <div class="user-info">
                            <div class="user-name">{{ user.name }}</div>
                            <div class="user-meta">
                                <span class="user-job">{{ user.position }}</span>
                                <span class="user-org">{{ getOrgNameById(user.orgId) }}</span>
                            </div>
                        </div>
                        <div class="user-contact">
                            <div class="user-phone">
                                <i class="fa fa-phone"></i>
                                {{ user.phone }}
                            </div>
                            <div class="user-code">工号: {{ user.workNo }}</div>
                        </div>
                    </div>
                </div>

                <!-- 分页 -->
                <div class="pagination-wrapper" v-if="displayTotal > 0">
                    <el-pagination
                        v-model:current-page="currentPage"
                        v-model:page-size="currentPageSize"
                        :page-sizes="[20, 50, 100, 200]"
                        :total="displayTotal"
                        layout="total, sizes, prev, pager, next, jumper"
                        small
                        @size-change="handleSizeChange"
                        @current-change="handlePageChange"
                    />
                </div>
            </div>
        </div>

        <!-- 底部操作栏 -->
        <div class="footer-actions" v-if="multiple">
            <div class="selected-info">
                已选择 {{ selectedUsers.length }} 人
            </div>
            <div class="action-buttons">
                <el-button @click="handleCancel">取消</el-button>
                <el-button type="primary" @click="handleConfirm">确定</el-button>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
// 注：orgList/userList 的默认调用方（AdminFormDrawer.vue）目前传入的是 mock 数据
// （mockOrgList/mockUserList），等真实通讯录/组织架构接口就绪后再替换，本组件自身
// 不内置任何 mock 数据、不依赖后端接口，属于纯展示型受控组件。
import { ref, computed, watch } from 'vue'

interface OrgItem {
    id: string
    pid: string | null
    name: string
}

interface UserItem {
    id: string
    name: string
    workNo: string
    phone: string
    position: string
    orgId: string
}

interface TreeNode {
    id: string
    label: string
    children?: TreeNode[]
}

interface UserWithOrg extends UserItem {
    orgName: string
}

interface FetchUsersParams {
    orgId?: string
    keyword?: string
    page: number
    pageSize: number
}

interface Props {
    orgList: OrgItem[]
    userList?: UserItem[]
    multiple?: boolean
    pageSize?: number
    fetchUsers?: (params: FetchUsersParams) => Promise<{ list: UserItem[]; total: number }>
    orgUserCountMap?: Map<string, number> | Record<string, number>
}

const props = withDefaults(defineProps<Props>(), {
    orgList:   () => [],
    userList:  () => [],
    multiple:  true,
    pageSize:  20,
})

interface Emits {
    (e: 'confirm', users: UserWithOrg[]): void
    (e: 'cancel'): void
}

const emit = defineEmits<Emits>()

const isRemote = computed(() => typeof props.fetchUsers === 'function')

const orgNameMap = computed<Map<string, string>>(() => {
    const m = new Map<string, string>()
    for (const o of props.orgList) m.set(o.id, o.name)
    return m
})

const orgChildrenMap = computed<Map<string, string[]>>(() => {
    const m = new Map<string, string[]>()
    for (const o of props.orgList) {
        const pid = o.pid ?? '__root__'
        if (!m.has(pid)) m.set(pid, [])
        m.get(pid)!.push(o.id)
    }
    return m
})

const getOrgNameById = (orgId: string): string =>
    orgNameMap.value.get(orgId) ?? ''

const getAllChildOrgIds = (orgId: string): string[] => {
    const result: string[] = [orgId]
    const children = orgChildrenMap.value.get(orgId)
    if (children) {
        for (const cid of children) result.push(...getAllChildOrgIds(cid))
    }
    return result
}

const internalOrgCountMap = computed<Map<string, number>>(() => {
    if (isRemote.value) return new Map<string, number>()
    const userOrgList = props.userList ?? []
    const m = new Map<string, number>()
    for (const o of props.orgList) {
        const childIds = new Set(getAllChildOrgIds(o.id))
        let count = 0
        for (const u of userOrgList) {
            if (childIds.has(u.orgId)) count++
        }
        m.set(o.id, count)
    }
    return m
})

const getOrgUserCount = (orgId: string): number => {
    if (props.orgUserCountMap) {
        const ext = props.orgUserCountMap
        if (ext instanceof Map) return ext.get(orgId) ?? 0
        return (ext as Record<string, number>)[orgId] ?? 0
    }
    return internalOrgCountMap.value.get(orgId) ?? 0
}

const orgTree = computed<TreeNode[]>(() => buildOrgTreeFast(null))

function buildOrgTreeFast(parentId: string | null): TreeNode[] {
    const key = parentId ?? '__root__'
    const childIds = orgChildrenMap.value.get(key) ?? []
    return childIds.map(id => ({
        id,
        label:    orgNameMap.value.get(id) ?? id,
        children: buildOrgTreeFast(id),
    }))
}

const filteredOrgTree = computed<TreeNode[]>(() => {
    if (!searchKeyword.value) return orgTree.value
    return filterTree(orgTree.value, searchKeyword.value)
})

const filterTree = (tree: TreeNode[], keyword: string): TreeNode[] => {
    const result: TreeNode[] = []
    const lowerKeyword = keyword.toLowerCase()
    for (const node of tree) {
        const match    = node.label.toLowerCase().includes(lowerKeyword)
        const children = node.children ? filterTree(node.children, keyword) : []
        if (match || children.length > 0) {
            result.push({ ...node, children: children.length > 0 ? children : node.children })
        }
    }
    return result
}

const currentOrgName = computed(() => {
    if (!currentOrgId.value) return ''
    return getOrgNameById(currentOrgId.value)
})

const loading          = ref(false)
const searchKeyword    = ref('')
const currentOrgId     = ref<string>('')
const currentPage      = ref(1)
const currentPageSize  = ref(props.pageSize)
const selectedUsers    = ref<UserWithOrg[]>([])
const selectedOrgIds   = ref<string[]>([])
const orgTreeRef       = ref()

const treeProps = { children: 'children', label: 'label' }

const remoteList  = ref<UserItem[]>([])
const remoteTotal = ref(0)

async function loadRemote() {
    if (!isRemote.value) return
    loading.value = true
    try {
        const res = await props.fetchUsers!({
            orgId:    currentOrgId.value || undefined,
            keyword:  searchKeyword.value || undefined,
            page:     currentPage.value,
            pageSize: currentPageSize.value,
        })
        remoteList.value  = res.list  ?? []
        remoteTotal.value = res.total ?? 0
    } catch {
        remoteList.value  = []
        remoteTotal.value = 0
    } finally {
        loading.value = false
    }
}

const filteredUsers = computed<UserItem[]>(() => {
    if (isRemote.value) return remoteList.value
    let users = props.userList ?? []
    if (currentOrgId.value) {
        const orgIdSet = new Set(getAllChildOrgIds(currentOrgId.value))
        users = users.filter(u => orgIdSet.has(u.orgId))
    }
    if (searchKeyword.value) {
        const kw = searchKeyword.value.toLowerCase()
        users = users.filter(u =>
            u.name.toLowerCase().includes(kw) ||
            u.workNo.toLowerCase().includes(kw) ||
            u.phone.includes(kw) ||
            u.position.toLowerCase().includes(kw)
        )
    }
    return users
})

const localPaginatedUsers = computed<UserItem[]>(() => {
    const start = (currentPage.value - 1) * currentPageSize.value
    return filteredUsers.value.slice(start, start + currentPageSize.value)
})

const paginatedUsers = computed<UserItem[]>(() =>
    isRemote.value ? remoteList.value : localPaginatedUsers.value
)

const displayTotal = computed<number>(() =>
    isRemote.value ? remoteTotal.value : filteredUsers.value.length
)

const selectedIdSet = computed<Set<string>>(() =>
    new Set(selectedUsers.value.map(u => u.id))
)

const isUserSelected = (userId: string): boolean =>
    selectedIdSet.value.has(userId)

let _searchTimer: ReturnType<typeof setTimeout> | null = null

const handleSearch = () => {
    if (_searchTimer) clearTimeout(_searchTimer)
    _searchTimer = setTimeout(() => {
        currentPage.value = 1
        if (isRemote.value) loadRemote()
    }, 300)
}

const handleOrgClick = (data: TreeNode) => {
    currentOrgId.value  = data.id
    currentPage.value   = 1
    searchKeyword.value = ''
    if (isRemote.value) loadRemote()
}

const handleOrgCheck = (data: TreeNode, checked: any) => {
    if (!props.multiple) return
    const checkedNodes = checked.checkedNodes as TreeNode[]
    selectedOrgIds.value = checkedNodes.map(n => n.id)
    const allOrgIds: string[] = []
    for (const orgId of selectedOrgIds.value) {
        allOrgIds.push(...getAllChildOrgIds(orgId))
    }
    const uniqueOrgIdSet = new Set([...new Set(allOrgIds)])
    if (!isRemote.value) {
        const orgUsers = (props.userList ?? [])
            .filter(u => uniqueOrgIdSet.has(u.orgId))
            .map(u => ({ ...u, orgName: getOrgNameById(u.orgId) }))
        const userMap = new Map<string, UserWithOrg>()
        for (const user of selectedUsers.value) userMap.set(user.id, user)
        for (const user of orgUsers)             userMap.set(user.id, user)
        selectedUsers.value = Array.from(userMap.values())
    }
}

const handleUserClick = (user: UserItem) => {
    if (!props.multiple) {
        emit('confirm', [{ ...user, orgName: getOrgNameById(user.orgId) }])
        return
    }
    const userWithOrg: UserWithOrg = { ...user, orgName: getOrgNameById(user.orgId) }
    if (isUserSelected(user.id)) {
        selectedUsers.value = selectedUsers.value.filter(u => u.id !== user.id)
    } else {
        selectedUsers.value.push(userWithOrg)
    }
}

const handleUserCheckChange = (checked: string | number | boolean, user: UserItem) => {
    const userWithOrg: UserWithOrg = { ...user, orgName: getOrgNameById(user.orgId) }
    if (checked === true) {
        if (!isUserSelected(user.id)) selectedUsers.value.push(userWithOrg)
    } else {
        selectedUsers.value = selectedUsers.value.filter(u => u.id !== user.id)
    }
}

const handleSizeChange = (size: number) => {
    currentPageSize.value = size
    currentPage.value     = 1
    if (isRemote.value) loadRemote()
}

const handlePageChange = (page: number) => {
    currentPage.value = page
    if (isRemote.value) loadRemote()
}

const clearSelection = () => {
    selectedUsers.value  = []
    selectedOrgIds.value = []
    if (orgTreeRef.value) orgTreeRef.value.setCheckedKeys([])
}

const handleConfirm = () => { emit('confirm', selectedUsers.value) }
const handleCancel  = () => { clearSelection(); emit('cancel') }

watch(searchKeyword, () => {})
watch(currentOrgId, () => { currentPage.value = 1 })
watch(isRemote, (val) => { if (val) loadRemote() }, { immediate: true })
</script>

<style scoped lang="scss">
.contact-selector {
    display: flex;
    flex-direction: column;
    height: 600px;
    background: var(--wf-canvas);
    border-radius: var(--wf-radius-lg);
    overflow: hidden;
}

/* ── 搜索栏 ── */
.search-bar {
    padding: var(--wf-space-16);
    border-bottom: 1px solid var(--wf-divider);

    .el-input {
        :deep(.el-input__wrapper) {
            border-radius: var(--wf-radius-sm);
            box-shadow: 0 0 0 1px var(--wf-border) inset;
            transition: box-shadow var(--wf-transition-fast);

            &:hover {
                box-shadow: 0 0 0 1px var(--wf-ink-disabled) inset;
            }

            &.is-focus {
                box-shadow: 0 0 0 1.5px var(--wf-primary) inset;
            }
        }
    }
}

/* ── 内容区 ── */
.content-wrapper {
    display: flex;
    flex: 1;
    overflow: hidden;
}

/* ── 左侧：组织树 ── */
.org-tree-section {
    width: 280px;
    border-right: 1px solid var(--wf-border);
    display: flex;
    flex-direction: column;
    background: var(--wf-bg);
}

.section-title {
    padding: 12px 16px;
    font-size: var(--wf-font-md);
    font-weight: var(--wf-font-weight-semibold);
    color: var(--wf-ink);
    border-bottom: 1px solid var(--wf-divider);
    background: var(--wf-canvas);
}

.org-tree-section .el-tree {
    flex: 1;
    overflow-y: auto;
    padding: var(--wf-space-8);
    background: transparent;

    :deep(.el-tree-node__content) {
        height: 36px;
        border-radius: var(--wf-radius-sm);
        margin-bottom: 2px;
        transition: background var(--wf-transition-fast);

        &:hover {
            background: rgba(0, 102, 204, 0.08);
        }
    }

    :deep(.el-tree-node.is-current > .el-tree-node__content) {
        background: rgba(0, 102, 204, 0.12);
        font-weight: var(--wf-font-weight-medium);
    }
}

.tree-node {
    display: flex;
    align-items: center;
    gap: var(--wf-space-8);
    flex: 1;
    font-size: var(--wf-font-md);
}

.node-icon  { color: var(--wf-primary); font-size: 14px; }
.node-label { flex: 1; color: var(--wf-ink); }
.node-count { font-size: var(--wf-font-sm); color: var(--wf-ink-3); }

/* ── 右侧：人员列表 ── */
.user-list-section {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--wf-divider);
    background: var(--wf-canvas);
}

.total-count {
    margin-left: var(--wf-space-8);
    font-size: var(--wf-font-base);
    color: var(--wf-ink-3);
    font-weight: var(--wf-font-weight-normal);
}

.actions {
    .el-button { font-size: var(--wf-font-base); }
}

/* ── 用户列表 ── */
.user-list {
    flex: 1;
    overflow-y: auto;
    padding: var(--wf-space-8);
}

.empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
}

.user-item {
    display: flex;
    align-items: center;
    gap: var(--wf-space-12);
    padding: var(--wf-space-12);
    border-radius: var(--wf-radius-sm);
    margin-bottom: var(--wf-space-4);
    cursor: pointer;
    border: 1px solid transparent;
    transition: background var(--wf-transition-fast),
                border-color var(--wf-transition-fast);

    &:hover {
        background: var(--wf-bg);
        border-color: var(--wf-border);
    }

    &.selected {
        background: var(--wf-primary-light);
        border-color: var(--wf-primary);
    }
}

.user-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--wf-primary) 0%, var(--wf-primary-hover) 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--wf-canvas);
    font-size: 18px;
    flex-shrink: 0;
}

.user-info {
    flex: 1;
    min-width: 0;
}

.user-name {
    font-size: var(--wf-font-lg);
    font-weight: var(--wf-font-weight-medium);
    color: var(--wf-ink);
    margin-bottom: var(--wf-space-4);
}

.user-meta {
    display: flex;
    gap: var(--wf-space-12);
    font-size: var(--wf-font-base);
    color: var(--wf-ink-3);
}

.user-job { color: var(--wf-primary); }

.user-contact {
    text-align: right;
    font-size: var(--wf-font-base);
    color: var(--wf-ink-3);
}

.user-phone {
    margin-bottom: var(--wf-space-4);
    i { margin-right: var(--wf-space-4); }
}

/* ── 分页 ── */
.pagination-wrapper {
    padding: 12px 16px;
    border-top: 1px solid var(--wf-divider);
    display: flex;
    justify-content: center;
    background: var(--wf-bg-card);
}

:deep(.el-pagination) {
    .btn-prev,
    .btn-next,
    .el-pager li {
        min-width: 32px;
        height: 32px;
        line-height: 32px;
    }
}

/* ── 底部操作栏 ── */
.footer-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-top: 1px solid var(--wf-divider);
    background: var(--wf-bg);
}

.selected-info {
    font-size: var(--wf-font-md);
    color: var(--wf-ink);
    font-weight: var(--wf-font-weight-medium);
}

.action-buttons {
    display: flex;
    gap: var(--wf-space-8);

    .el-button { min-width: 80px; }
}

/* ── 滚动条 ── */
.user-list::-webkit-scrollbar,
.org-tree-section .el-tree::-webkit-scrollbar {
    width: 5px;
}

.user-list::-webkit-scrollbar-thumb,
.org-tree-section .el-tree::-webkit-scrollbar-thumb {
    background: var(--wf-border);
    border-radius: 3px;

    &:hover { background: var(--wf-ink-disabled); }
}
</style>
