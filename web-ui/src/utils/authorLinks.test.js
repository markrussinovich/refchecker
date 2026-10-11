import { expect, it } from 'vitest'
import { googleScholarProfileUrl } from './authorLinks'

it('accepts real profile URLs but not search links or unrelated hostnames', () => {
  expect(googleScholarProfileUrl({ homepage: 'https://scholar.google.com/citations?user=KnownId' }))
    .toBe('https://scholar.google.com/citations?user=KnownId')
  for (const homepage of [
    'https://scholar.google.com/scholar?q=Author',
    'https://scholar.google.com/citations',
    'https://scholar.google.com.evil.example/citations?user=KnownId',
    'javascript:alert(1)',
  ]) expect(googleScholarProfileUrl({ homepage })).toBeNull()
})
