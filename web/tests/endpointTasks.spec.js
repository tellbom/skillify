// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EndpointTasksView from '../src/views/EndpointTasksView.vue'
import { dispatchEndpointTask, getEndpointTasks, getMyEndpoints } from '../src/lib/api.js'

vi.mock('../src/lib/api.js', () => ({
  getMyEndpoints: vi.fn(),
  getEndpointTasks: vi.fn(),
  dispatchEndpointTask: vi.fn(),
}))

const endpoint = {
  endpointId: 'endpoint-1', label: 'Developer laptop', online: true,
  workspaceAliases: ['billing'], lastSeenAt: '2026-07-16T10:00:00Z',
}

describe('EndpointTasksView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMyEndpoints.mockResolvedValue([endpoint])
    getEndpointTasks.mockResolvedValue([{
      taskId: 'task-old', endpointId: 'endpoint-1', workflowId: 'evidence-review',
      state: 'failed', events: [{
        eventType: 'task.failed', occurredAt: '2026-07-16T10:02:00Z',
        failureReason: 'TEST_FAILED', artifacts: [],
      }],
    }])
  })

  it('renders fixed workflow controls and verifiable timeline without prompt or shell fields', async () => {
    const wrapper = mount(EndpointTasksView)
    await flushPromises()

    expect(wrapper.get('[data-testid="workflow-select"]').findAll('option')).toHaveLength(5)
    expect(wrapper.text()).toContain('TEST_FAILED')
    expect(wrapper.find('[name="prompt"]').exists()).toBe(false)
    expect(wrapper.find('[name="shell"]').exists()).toBe(false)
  })

  it('dispatches only the selected fixed form payload', async () => {
    dispatchEndpointTask.mockResolvedValue({
      taskId: 'task-new', workflowId: 'evidence-bugfix', state: 'awaiting_confirmation', events: [],
    })
    const wrapper = mount(EndpointTasksView)
    await flushPromises()
    await wrapper.get('[data-testid="workflow-input"]').setValue('BUG-42')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(dispatchEndpointTask).toHaveBeenCalledWith({
      endpointId: 'endpoint-1', workspaceAlias: 'billing',
      workflowId: 'evidence-bugfix', workflowVersion: '1.0.0',
      inputs: { issueReference: 'BUG-42' },
    })
    expect(wrapper.text()).toContain('task-new')
  })
})
