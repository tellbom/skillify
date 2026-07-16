// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CodeMapView from '../src/views/CodeMapView.vue'

const fixture = {
  schemaVersion: 1,
  repositoryHash: 'abc123fixture',
  nodes: [
    {
      id: 'repo', kind: 'repository', name: '.', evidence: null, attributes: {},
    },
    {
      id: 'api', kind: 'api_endpoint', name: 'POST /skills',
      evidence: { path: 'src/api.py', line: 41, endLine: 44 }, attributes: {},
    },
  ],
  edges: [
    {
      id: 'route', kind: 'routes_to', source: 'repo', target: 'api',
      confidence: 0.9, sourceLabel: 'fixture-parser',
      evidence: { path: 'src/api.py', line: 41, endLine: 41 },
    },
  ],
}

describe('CodeMapView', () => {
  it('renders fixed graph nodes, relations, and evidence positions read-only', async () => {
    const wrapper = mount(CodeMapView, { props: { codeMap: fixture } })

    expect(wrapper.text()).toContain('abc123fixture')
    expect(wrapper.text()).toContain('POST /skills')
    await wrapper.findAll('.node-row')[1].trigger('click')
    expect(wrapper.get('[data-testid="evidence-rail"]').text()).toContain('src/api.py:41-44')
    expect(wrapper.get('[data-testid="evidence-rail"]').text()).toContain('routes_to')
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.find('input').exists()).toBe(false)
  })
})
