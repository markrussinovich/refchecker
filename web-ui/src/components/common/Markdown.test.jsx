import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Markdown, { safeHref } from './Markdown'

describe('Markdown renderer', () => {
  it('renders **bold** as <strong>, not literal asterisks', () => {
    const { container } = render(<Markdown text="introduces **Visual ChatGPT**, a system" />)
    const strong = container.querySelector('strong')
    expect(strong).not.toBeNull()
    expect(strong.textContent).toBe('Visual ChatGPT')
    expect(container.textContent).not.toContain('**')
  })

  it('renders *italic* and `code`', () => {
    const { container } = render(<Markdown text={'this is *emphasis* and `inline_code` here'} />)
    expect(container.querySelector('em')?.textContent).toBe('emphasis')
    expect(container.querySelector('code')?.textContent).toBe('inline_code')
  })

  it('renders a bullet list with * markers as <ul><li>', () => {
    const md = '* **System Architecture:** integrates ChatGPT\n* **The Prompt Manager:** central component'
    const { container } = render(<Markdown text={md} />)
    const items = container.querySelectorAll('ul li')
    expect(items.length).toBe(2)
    expect(items[0].querySelector('strong')?.textContent).toBe('System Architecture:')
    expect(container.textContent).not.toContain('* **')
  })

  it('renders numbered lists as <ol><li>', () => {
    const { container } = render(<Markdown text={'1. first\n2. second'} />)
    expect(container.querySelectorAll('ol li').length).toBe(2)
  })

  it('renders headings', () => {
    render(<Markdown text={'# Key aspects\nbody text'} />)
    expect(screen.getByText('Key aspects')).toBeInTheDocument()
  })

  it('renders fenced code blocks verbatim', () => {
    const { container } = render(<Markdown text={'```\nconst x = **not bold**\n```'} />)
    const pre = container.querySelector('pre code')
    expect(pre?.textContent).toContain('const x = **not bold**')
  })

  it('renders safe links and neutralizes unsafe ones', () => {
    const { container } = render(<Markdown text={'see [site](https://example.com) and [bad](javascript:alert(1))'} />)
    const a = container.querySelector('a')
    expect(a?.getAttribute('href')).toBe('https://example.com')
    expect(a?.getAttribute('rel')).toContain('noopener')
    // The unsafe link is rendered as plain text, not an anchor.
    expect(container.querySelectorAll('a').length).toBe(1)
    expect(container.textContent).toContain('[bad](javascript:alert(1))')
  })

  it('safeHref allows http/https/mailto/relative and rejects others', () => {
    expect(safeHref('https://a.com')).toBe('https://a.com')
    expect(safeHref('mailto:a@b.com')).toBe('mailto:a@b.com')
    expect(safeHref('/local')).toBe('/local')
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('data:text/html,<script>')).toBeNull()
  })
})
