import { test, expect } from '@playwright/test'

if (process.env.PW_CHANNEL) test.use({ channel: process.env.PW_CHANNEL })

const title = 'Export acceptance paper'
const formats = [
  { name: /Markdown \(/, extension: 'md' },
  { name: /Plain Text \(/, extension: 'txt' },
  { name: /BibTeX \(/, extension: 'bib' },
  { name: /RIS \(/, extension: 'ris' },
  { name: /JSONL \(/, extension: 'jsonl' },
  { name: /CSV \(/, extension: 'csv' },
]

function references(legacy) {
  const refs = Array.from({ length: 35 }, (_, i) => ({
    index: i + 1, title: `Clean citation ${i + 1}`, authors: ['Cited Author'], year: 2025,
    status: 'verified', errors: [], warnings: [], suggestions: [], authoritative_urls: [],
  }))
  for (const index of [11, 13]) {
    refs[index].title = index === 11 ? 'Copyright-protected generation' : 'StruQ'
    refs[index].status = 'warning'
    refs[index].warnings = [{
      warning_type: 'year', ref_year_correct: 2024,
      warning_details: 'Year mismatch:\n cited: 2025\n actual: 2024',
    }]
  }
  refs[22].title = 'Securing AI agents'
  refs[22].status = 'error'
  refs[22].authors = ['Correct Author', 'Second Author']
  refs[22].errors = [{
    error_type: 'author', ref_authors_correct: 'Correct Author, Second Author',
    error_details: 'Author 2 mismatch:\n cited: Wrong Author\n actual: Correct Author, Second Author',
  }]
  refs[1].warnings = [{ warning_type: 'venue', warning_details: 'Venue review needed' }]
  refs[1].authoritative_urls = [{ type: 'doi', url: 'https://doi.org/10.1234/enrichment' }]
  if (!legacy) {
    for (const ref of refs) {
      ref.original_reference = {
        title: ref.title, authors: ref.index === 23 ? ['Cited Author', 'Wrong Author'] : ref.authors,
        year: ref.year,
      }
    }
  }
  return refs
}

async function loadCheck(page, refs) {
  const check = {
    id: 999, paper_title: title, paper_source: 'acceptance.pdf', source_type: 'file',
    timestamp: '2026-10-11T12:00:00Z', status: 'completed', total_refs: refs.length,
    processed_refs: refs.length, refs_verified: refs.length - 3, refs_with_errors: 1,
    refs_with_warnings_only: 2, errors_count: 1, warnings_count: 3, results: refs,
  }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (status, data) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(data),
    })
    if (path === '/api/auth/providers') return json(200, { providers: [] })
    if (path === '/api/auth/me') return json(401, {})
    if (path === '/api/health') return json(200, { status: 'healthy' })
    if (path === '/api/llm-configs') return json(200, [])
    if (path === '/api/settings/semantic-scholar') return json(200, { enabled: false })
    if (path === '/api/history') return json(200, [check])
    if (path === '/api/history/999') return json(200, check)
    if (path === '/api/check/999/authors') return json(200, { available: false, authors: [] })
    return json(404, { detail: 'No fixture for this endpoint' })
  })
  await page.goto('/')
  await page.locator('aside.sidebar-desktop').getByText(title, { exact: true }).click()
  await expect(page.getByTitle('Export results')).toBeVisible()
}

async function openMenu(page, mode, sort = 'citation') {
  await page.getByTitle('Export results').click()
  await page.locator('select').filter({ has: page.locator('option[value="corrections-only"]') })
    .selectOption(mode)
  await page.locator('select').filter({ has: page.locator('option[value="citation"]') }).selectOption(sort)
}

async function downloadFile(page, format, mode, sort) {
  await openMenu(page, mode, sort)
  const pending = page.waitForEvent('download')
  await page.getByRole('button', { name: format.name }).click()
  const download = await pending
  expect(await download.failure()).toBeNull()
  const stream = await download.createReadStream()
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  return { filename: download.suggestedFilename(), content: Buffer.concat(chunks).toString('utf8') }
}

for (const legacy of [false, true]) {
  for (const mode of ['original', 'corrected', 'corrections-only', 'diff']) {
    test(`${legacy ? 'legacy' : 'snapshot'} check: actual downloads in ${mode} mode`, async ({ page }) => {
      await loadCheck(page, references(legacy))
      for (const format of formats) {
        const { filename, content } = await downloadFile(page, format, mode)
        expect(content.trim().length).toBeGreaterThan(0)
        expect(content).not.toContain('undefined')
        expect(content).not.toContain('[object Object]')
        expect(content).toContain('Copyright-protected generation')
        expect(content).toContain('StruQ')
        expect(content).toContain('Securing AI agents')
        if (mode === 'corrections-only') {
          expect(filename).toContain(`-corrections-only.${format.extension}`)
          expect(content).toContain('Correct Author')
          expect(content).toContain('2024')
          expect(content).not.toContain('Clean citation')
          expect(content).not.toContain('Wrong Author')
          expect(content).not.toContain('Year mismatch')
          expect(content).not.toContain('Venue review needed')
          if (format.extension === 'bib') expect(content.match(/^@/gm)).toHaveLength(3)
          if (format.extension === 'ris') expect(content.match(/^TY {2}-/gm)).toHaveLength(3)
          if (['md', 'txt'].includes(format.extension)) {
            expect(content.match(/Copyright-protected generation|StruQ|Securing AI agents/g)).toHaveLength(3)
          }
          if (format.extension === 'csv') expect(content.trim().split('\n')).toHaveLength(4)
          if (format.extension === 'jsonl') expect(content.trim().split('\n').map(JSON.parse)).toHaveLength(3)
        } else if (mode === 'diff') {
          expect(filename).toMatch(/-diff\.(md|csv)$/)
          expect(content).toContain('2024')
          expect(content).toContain('Wrong Author')
          expect(content).toContain('No verified correction available; review manually.')
          expect(content).not.toContain('Clean citation 1')
        } else {
          expect(filename).toMatch(new RegExp(`\\.${format.extension}$`))
          expect(content).toContain('Clean citation 1')
          expect(content).toContain('Clean citation 35')
          if (format.extension === 'bib') expect(content.match(/^@/gm)).toHaveLength(35)
          if (format.extension === 'ris') expect(content.match(/^TY {2}-/gm)).toHaveLength(35)
          if (format.extension === 'jsonl') expect(content.trim().split('\n').map(JSON.parse)).toHaveLength(35)
          if (mode === 'corrected') {
            expect(content).toContain('Correct Author')
            expect(content).toContain('2024')
          } else if (!legacy) {
            expect(content).toContain('Wrong Author')
          }
        }
      }
    })
  }
}

test('corrections-only displays an empty state without triggering any download', async ({ page }) => {
  await loadCheck(page, [{ title: 'No fixes needed', status: 'verified', errors: [], warnings: [] }])
  const downloads = []
  page.on('download', download => downloads.push(download))
  for (const format of formats) {
    await openMenu(page, 'corrections-only')
    await page.getByRole('button', { name: format.name }).click()
    await expect(page.getByRole('status')).toHaveText('No verified corrections are available to export.')
  }
  expect(downloads).toHaveLength(0)
})

test('sorting changes citation order while a visible status filter does not drop fixes', async ({ page }) => {
  const refs = references(true)
  refs[11].authors = ['A. Adams']
  refs[13].authors = ['Z. Zulu']
  refs[22].year = 2023
  await loadCheck(page, refs)
  await page.getByTitle(/references? with (an error|errors)/i).first().click()
  await expect(page.getByTitle(/clear all active filters/i)).toBeVisible()
  const format = formats.find(format => format.extension === 'jsonl')
  const titles = ['Copyright-protected generation', 'StruQ', 'Securing AI agents']
  for (const sort of ['citation', 'alphabetical', 'year-desc', 'year-asc']) {
    const { content } = await downloadFile(page, format, 'corrections-only', sort)
    const entries = content.split('\n').map(JSON.parse)
    expect(entries).toHaveLength(3)
    expect(entries.map(entry => entry.title).sort()).toEqual([
      'Copyright-protected generation', 'Securing AI agents', 'StruQ',
    ])
    const expected = sort === 'alphabetical' ? [titles[0], titles[2], titles[1]]
      : sort === 'year-asc' ? [titles[2], titles[0], titles[1]] : titles
    expect(entries.map(entry => entry.title)).toEqual(expected)
    expect(entries.find(entry => entry.title === 'Securing AI agents').authors)
      .toEqual(['Correct Author', 'Second Author'])
  }
})

test('original and corrected downloads sort by their own citation values', async ({ page }) => {
  await loadCheck(page, [
    {
      index: 1, title: 'Needs fixes', authors: ['Z. Zulu'], year: 2026, status: 'error',
      original_reference: { title: 'Needs fixes', authors: ['A. Adams'], year: 2025 },
      errors: [{
        error_type: 'year', ref_year_correct: 2020, ref_authors_correct: ['Z. Zulu'],
      }], warnings: [],
    },
    {
      index: 2, title: 'Middle citation', authors: ['M. Miller'], year: 2022,
      status: 'verified', errors: [], warnings: [],
    },
  ])
  const format = formats.find(format => format.extension === 'bib')
  for (const mode of ['original', 'corrected']) {
    for (const sort of ['alphabetical', 'year-desc']) {
      const { content } = await downloadFile(page, format, mode, sort)
      const titles = [...content.matchAll(/title = \{([^}]+)\}/g)].map(match => match[1])
      expect(titles).toEqual(mode === 'original'
        ? ['Needs fixes', 'Middle citation'] : ['Middle citation', 'Needs fixes'])
      if (mode === 'original') {
        expect(content).toContain('A. Adams')
        expect(content).toContain('2025')
        expect(content).not.toContain('Z. Zulu')
        expect(content).not.toContain('2020')
      } else {
        expect(content).toContain('Z. Zulu')
        expect(content).toContain('2020')
        expect(content).not.toContain('A. Adams')
        expect(content).not.toContain('2026')
      }
    }
  }
})
