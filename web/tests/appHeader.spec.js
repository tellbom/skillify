// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppHeader from '../src/layouts/AppHeader.vue'

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

function mountHeader(props = {}) {
  return mount(AppHeader, {
    props: {
      navItems,
      username: '196045',
      isAuthenticated: true,
      currentPath: '/skills',
      ...props,
    },
    global: {
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

describe('AppHeader', () => {
  it('renders the prototype brand, active dynamic navigation, and menu groups', () => {
    const wrapper = mountHeader()

    expect(wrapper.get('.brand-accent').text()).toBe('ify')
    expect(wrapper.get('[aria-current="page"]').text()).toBe('技能中心')
    expect(wrapper.get('.nav-group-menu').text()).toContain('规则管理')
  })

  it('derives the avatar from the username and emits logout', async () => {
    const wrapper = mountHeader()

    expect(wrapper.get('.user-avatar').text()).toBe('19')
    expect(wrapper.get('.username').text()).toBe('196045')

    await wrapper.get('.logout-button').trigger('click')
    expect(wrapper.emitted('logout')).toHaveLength(1)
  })

  it('uses a safe avatar fallback and hides auth controls while signed out', () => {
    const authenticated = mountHeader({ username: '', currentPath: '/missing' })
    const signedOut = mountHeader({ isAuthenticated: false })

    expect(authenticated.get('.user-avatar').text()).toBe('?')
    expect(authenticated.find('[aria-current="page"]').exists()).toBe(false)
    expect(signedOut.find('.auth-area').exists()).toBe(false)
  })
})
