export function googleScholarProfileUrl(...profiles) {
  for (const profile of profiles) {
    for (const value of [profile?.google_scholar_url, profile?.scholar_url, profile?.homepage]) {
      if (typeof value !== 'string') continue
      try {
        const url = new URL(value)
        if (url.protocol === 'https:' && url.hostname === 'scholar.google.com' &&
            url.pathname === '/citations' && url.searchParams.get('user')) return url.href
      } catch { /* Not a profile URL. */ }
    }
  }
  return null
}
