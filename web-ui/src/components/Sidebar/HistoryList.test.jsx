import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import HistoryList from './HistoryList'

vi.mock('../../stores/useHistoryStore', () => {
  const state = {
    history: [
      { id: 1, batch_id: 'batch-1', paper_title: 'Batch paper' },
      { id: 2, paper_title: 'Standalone paper' },
    ],
    selectedCheckId: 2,
    isLoading: false,
    error: null,
    fetchHistory: vi.fn(),
  }
  return { useHistoryStore: selector => selector ? selector(state) : state }
})
vi.mock('./HistoryItem', () => ({
  default: ({ item }) => <div>{item.paper_title}</div>,
}))
vi.mock('./BatchGroup', () => ({
  default: ({ isCollapsed, onToggle, items }) => (
    <div>
      <button type="button" onClick={onToggle}>Toggle batch</button>
      {!isCollapsed && items.map(item => <div key={item.id}>{item.paper_title}</div>)}
    </div>
  ),
}))

describe('HistoryList', () => {
  it('omits the master toggle while preserving individual batch toggles', () => {
    render(<HistoryList />)
    expect(screen.queryByRole('button', { name: /collapse all|expand all/i })).toBeNull()
    expect(screen.getByText('Batch paper')).toBeInTheDocument()
    expect(screen.getByText('Standalone paper')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Toggle batch' }))
    expect(screen.queryByText('Batch paper')).toBeNull()
    expect(screen.getByText('Standalone paper')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Toggle batch' }))
    expect(screen.getByText('Batch paper')).toBeInTheDocument()
  })
})
