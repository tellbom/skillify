// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppFooter from '../src/layouts/AppFooter.vue'

const RouterLinkStub = {
  props: ['to'],
  template: '<a :href="to"><slot /></a>',
}

const navItems = [
  { name: 'skills', title: '技能中心', path: '/skills', children: [] },
  {
    name: 'auth',
    title: '权限管理',
    path: '/auth',
    children: [
      { name: 'auth-rule', title: '规则管理', path: '/auth/rule', children: [] },
    ],
  },
]

describe('AppFooter', () => {
  it('renders authorized leaf routes as quick links', () => {
    const wrapper = mount(AppFooter, {
      props: { navItems },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })

    const links = wrapper.findAll('.footer-nav-link')
    expect(links).toHaveLength(2)
    expect(links.map((link) => link.text())).toEqual(['技能中心', '规则管理'])
  })

  it('shows complete internal footer information with inert resource actions', () => {
    const wrapper = mount(AppFooter, {
      props: { navItems },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })

    expect(wrapper.text()).toContain('使用文档')
    expect(wrapper.text()).toContain('问题反馈')
    expect(wrapper.text()).toContain('暂未开放')
    expect(wrapper.findAll('.placeholder-link')).toHaveLength(2)
    expect(wrapper.findAll('.placeholder-link').every((node) => node.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('仅供内部使用')
    expect(wrapper.text()).toContain(`© ${new Date().getFullYear()} Skillify`)
  })
})
