import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AIDetectionVisuals, { DetectorComparison } from './AIDetectionVisuals'

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

// R61 (I2) — the multi-detector comparison table: per-detector score/band chips
// reusing the band palette, a per-sentence agreement view, and checkbox-export.
describe('DetectorComparison — per-detector chips + agreement (R61)', () => {
  const results = {
    desklib: { label: 'Desklib', band: 'high', overall_score: 0.92 },
    superannotate: { label: 'SuperAnnotate', band: 'low', overall_score: 0.08 },
  }
  const agreement = [
    { text: 'A sentence both detectors flagged.', flagged_by: ['desklib', 'superannotate'] },
    { text: 'A sentence only one flagged.', flagged_by: ['desklib'] },
  ]

  it('renders a chip per detector with its own band label + score (no synthetic ensemble row)', () => {
    render(<DetectorComparison results={results} order={['desklib', 'superannotate']} selection={['desklib', 'superannotate']} />)
    // Both detectors are listed by label.
    expect(screen.getByText('Desklib')).toBeInTheDocument()
    expect(screen.getByText('SuperAnnotate')).toBeInTheDocument()
    // Each detector's own band word + percent is shown.
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Low')).toBeInTheDocument()
    expect(screen.getByText('92')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('shows per-sentence agreement counts (how many detectors flagged each)', () => {
    render(<DetectorComparison results={results} order={['desklib', 'superannotate']} selection={['desklib', 'superannotate']} agreement={agreement} />)
    const rows = screen.getAllByTestId('agreement-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('2/2')).toBeInTheDocument() // both flagged
    expect(within(rows[1]).getByText('1/2')).toBeInTheDocument() // one flagged
  })

  it('an abstaining detector shows a dash, never a fabricated score', () => {
    const withAbstain = { ...results, mage: { label: 'MAGE', band: 'inconclusive' } }
    render(<DetectorComparison results={withAbstain} order={['desklib', 'superannotate', 'mage']} selection={[]} />)
    expect(screen.getByText('MAGE')).toBeInTheDocument()
    expect(screen.getByText('Inconclusive')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('does not render with fewer than 2 detectors (single-detector path unchanged)', () => {
    const { container } = render(<DetectorComparison results={{ desklib: results.desklib }} order={['desklib']} selection={['desklib']} />)
    expect(container.firstChild).toBeNull()
  })

  it('"Export selected" fires with exactly the checked detector keys', () => {
    const onExport = vi.fn()
    render(
      <DetectorComparison
        results={results}
        order={['desklib', 'superannotate']}
        selection={['desklib']}   // only desklib checked
        onExport={onExport}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Export selected/i }))
    expect(onExport).toHaveBeenCalledWith(['desklib'])
  })

  it('the export checkbox toggles call onToggle for that detector', () => {
    const onToggle = vi.fn()
    render(
      <DetectorComparison
        results={results}
        order={['desklib', 'superannotate']}
        selection={['desklib', 'superannotate']}
        onToggle={onToggle}
        onExport={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByTestId('export-check-superannotate'))
    expect(onToggle).toHaveBeenCalledWith('superannotate')
  })
})

// The single-detector visuals render exactly as before when no comparison prop
// is passed — backward compatibility.
describe('AIDetectionVisuals — single-detector path unchanged (R61 backward compat)', () => {
  it('renders no comparison table without the comparison prop', () => {
    render(<AIDetectionVisuals detection={detection} />)
    expect(screen.queryByTestId('detector-comparison')).toBeNull()
  })

  it('renders the comparison table only when ≥2 detectors are passed', () => {
    render(
      <AIDetectionVisuals
        detection={detection}
        comparison={{
          results: { desklib: { label: 'Desklib', band: 'high', overall_score: 0.9 }, mage: { label: 'MAGE', band: 'low', overall_score: 0.1 } },
          order: ['desklib', 'mage'],
          selection: ['desklib', 'mage'],
        }}
      />,
    )
    expect(screen.getByTestId('detector-comparison')).toBeInTheDocument()
  })
})
