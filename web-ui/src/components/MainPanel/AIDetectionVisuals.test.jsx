import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AIDetectionVisuals from './AIDetectionVisuals'

// R03 (O4) — every AI sentence in the page-by-page and top-sentence lists must
// carry a working per-sentence "view in document" button that routes through
// the pdf.js stack via the onViewSentence callback.

const detection = {
  probability_distribution: { AI: 0.6, Mixed: 0.2, Human: 0.2 },
  overall_score: 0.6,
  per_page_scores: [
    {
      page: 1,
      score: 0.8,
      band: 'high',
      sentences: [
        { text: 'Page one flagged sentence.', band: 'high', score: 0.9 },
        { text: 'Page one second sentence.', band: 'medium', score: 0.5 },
      ],
    },
  ],
  top_ai_sentences: [
    { text: 'Top AI sentence one.', score: 0.95 },
    { text: 'Top AI sentence two.', score: 0.88 },
  ],
  top_human_sentences: [
    { text: 'Top human sentence.', score: 0.05 },
  ],
}

describe('AIDetectionVisuals per-sentence "view in document" button (R03)', () => {
  it('renders a per-sentence button in the expanded page-by-page list and calls onViewSentence', () => {
    const onViewSentence = vi.fn()
    render(
      <AIDetectionVisuals
        detection={detection}
        onViewSentence={onViewSentence}
        canViewSentence={() => true}
      />,
    )

    // Expand the page row to reveal its per-sentence list.
    fireEvent.click(screen.getByText('Page 1'))

    const sentence = screen.getByText('Page one flagged sentence.')
    const row = sentence.closest('div')
    const button = within(row).getByRole('button', { name: /view this sentence in the document/i })
    fireEvent.click(button)

    expect(onViewSentence).toHaveBeenCalledTimes(1)
    expect(onViewSentence).toHaveBeenCalledWith('Page one flagged sentence.')
  })

  it('renders a per-sentence button for every sentence in the top-AI list', () => {
    const onViewSentence = vi.fn()
    render(
      <AIDetectionVisuals
        detection={detection}
        onViewSentence={onViewSentence}
        canViewSentence={() => true}
      />,
    )

    // Open the collapsible "Top AI / Human sentences" section (off by default).
    fireEvent.click(screen.getByText(/Top AI \/ Human sentences/i))

    const aiSentence = screen.getByText('Top AI sentence one.')
    const li = aiSentence.closest('li')
    const button = within(li).getByRole('button', { name: /view this sentence in the document/i })
    fireEvent.click(button)

    expect(onViewSentence).toHaveBeenCalledWith('Top AI sentence one.')

    // Every top-AI sentence carries its own button (one per sentence).
    const buttons = screen.getAllByRole('button', { name: /view this sentence in the document/i })
    expect(buttons.length).toBeGreaterThanOrEqual(2)
  })

  it('hides the button for sentences that cannot be located (no dead buttons)', () => {
    const onViewSentence = vi.fn()
    // Only the first page sentence is locatable.
    const canViewSentence = (text) => text === 'Page one flagged sentence.'
    render(
      <AIDetectionVisuals
        detection={detection}
        onViewSentence={onViewSentence}
        canViewSentence={canViewSentence}
      />,
    )

    fireEvent.click(screen.getByText('Page 1'))

    const locatable = screen.getByText('Page one flagged sentence.').closest('div')
    expect(within(locatable).queryByRole('button', { name: /view this sentence in the document/i })).not.toBeNull()

    const unlocatable = screen.getByText('Page one second sentence.').closest('div')
    expect(within(unlocatable).queryByRole('button', { name: /view this sentence in the document/i })).toBeNull()
  })

  it('renders no per-sentence buttons when onViewSentence is not provided', () => {
    render(<AIDetectionVisuals detection={detection} />)
    fireEvent.click(screen.getByText('Page 1'))
    expect(screen.queryAllByRole('button', { name: /view this sentence in the document/i })).toHaveLength(0)
  })
})
