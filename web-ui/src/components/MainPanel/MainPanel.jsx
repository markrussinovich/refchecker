import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import InputSection from './InputSection'
import StatusSection from './StatusSection'
import StatsSection from './StatsSection'
import ReferenceList from './ReferenceList'
import CorrectionsView from './CorrectionsView'
import OnboardingBanner from './OnboardingBanner'
import FieldGuide from './FieldGuide'
import GlobalDropZone from './GlobalDropZone'
import SeenReferencesView from './SeenReferencesView'
import BatchSummaryView from './BatchSummaryView'
import GraphView from './GraphView'
import SimilarPapersPanel from './SimilarPapersPanel'
import ExploreGraphView from './ExploreGraphView'
import AIDetectionPanel from './AIDetectionPanel'
import HealthBadge from './HealthBadge'
import RetractionCheck from './RetractionCheck'
import GapFinder from './GapFinder'
import CitationIntegrity from './CitationIntegrity'
import ArticleAssistant from './ArticleAssistant'
import ActionPanelGrid from './ActionPanelGrid'
import LLMUsageBadge from './LLMUsageBadge'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useStyleStore } from '../../stores/useStyleStore'
import { useShallow } from 'zustand/react/shallow'
import { applyStatusFilter } from '../../utils/referenceStatus'
import { filterIssuesForStyle } from '../../utils/formatters'

/**
 * Main panel containing input, status, stats, and references
 * All checks are treated as peers - no special handling for "current" vs "history"
 */
export default function MainPanel() {
  const mainRef = useRef(null)
  const contentRef = useRef(null)
  const [showScrollTop, setShowScrollTop] = useState(false)
  const [resultsTab, setResultsTab] = useState('references') // references | corrections | graph
  const [globalView, setGlobalView] = useState(null) // 'seen' | null — overrides the per-check views when set
  const [showExplore, setShowExplore] = useState(false) // ResearchRabbit-style fullscreen Explore graph overlay (#68)

  // When a citation highlight in the document links back to its reference,
  // make sure the References tab is showing so the target card can flash.
  useEffect(() => {
    const onFocus = () => { setGlobalView(null); setResultsTab('references') }
    window.addEventListener('refchecker:focus-reference', onFocus)
    return () => window.removeEventListener('refchecker:focus-reference', onFocus)
  }, [])
  
  const {
    status: checkStoreStatus,
    references: checkStoreRefs,
    stats: checkStoreStats,
    aiDetection: checkStoreAiDetection,
    currentCheckId,
    clearStatusFilter,
    statusFilter,
  } = useCheckStore(useShallow(s => ({
    status: s.status,
    references: s.references,
    stats: s.stats,
    aiDetection: s.aiDetection,
    currentCheckId: s.currentCheckId,
    clearStatusFilter: s.clearStatusFilter,
    statusFilter: s.statusFilter,
  })))
  const { selectedCheck, selectedCheckId, isLoadingDetail, selectedBatchId, backToBatch } = useHistoryStore()
  // Subscribe so the tab badges re-evaluate the style-aware corrections
  // count whenever the user flips the citation style dropdown.
  const activeStyle = useStyleStore(s => s.format)

  // Track scroll position to show/hide scroll-to-top button
  useEffect(() => {
    const mainElement = mainRef.current
    if (!mainElement) return

    const handleScroll = () => {
      setShowScrollTop(mainElement.scrollTop > 300)
    }

    mainElement.addEventListener('scroll', handleScroll, { passive: true })
    return () => mainElement.removeEventListener('scroll', handleScroll)
  }, [])


  // Scroll to top handler
  const scrollToTop = useCallback(() => {
    mainRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  // Determine what to display:
  // - selectedCheckId === -1: "New refcheck" placeholder -> show input form
  // - selectedCheckId is set: show that check's data from selectedCheck
  // - No selection but check running: show input (shouldn't happen normally)
  const isNewRefcheckSelected = selectedCheckId === -1
  const isViewingCheck = selectedCheckId !== null && selectedCheckId !== -1
  // v0.7.45: batch summary view takes over the main panel when a batch
  // row is selected from the sidebar. Per-paper drill-in keeps the
  // standard check view but adds a "← Back to batch" link at the top.
  const isViewingBatch = selectedBatchId != null && selectedCheckId == null

  // Clear status filter when switching views
  useEffect(() => {
    clearStatusFilter()
  }, [selectedCheckId, clearStatusFilter])

  // Show input when "New refcheck" is selected OR no check and idle
  const showInput = isNewRefcheckSelected || (!isViewingCheck && checkStoreStatus === 'idle')
  
  // Show content when viewing any check
  const showContent = isViewingCheck

  // Unified data source - all checks treated equally
  // Source from selectedCheck for ANY selected check (current or not)
  // Fall back to checkStore only if selectedCheck isn't loaded yet for current check
  const isCurrentCheck = selectedCheckId === currentCheckId
  const hasSelectedCheckData = selectedCheck && selectedCheck.id === selectedCheckId
  
  // Determine status
  const displayStatus = hasSelectedCheckData 
    ? selectedCheck.status 
    : (isCurrentCheck ? checkStoreStatus : 'idle')
  
  const isInProgress = displayStatus === 'in_progress' || displayStatus === 'checking'
  const isComplete = displayStatus === 'completed' || displayStatus === 'cancelled'
  // Get paper title and source for export
  const displayPaperTitle = hasSelectedCheckData 
    ? (selectedCheck.custom_label || selectedCheck.paper_title)
    : null
  const displayPaperSource = hasSelectedCheckData 
    ? selectedCheck.paper_source 
    : null
  // Build unified references list FIRST (needed by buildStats)
  // For current check, prefer live checkStore data; for other checks, use selectedCheck
  const displayRefs = useMemo(() => {
    // Current check: use live WebSocket data from checkStore
    if (isCurrentCheck && checkStoreRefs && checkStoreRefs.length > 0) {
      return checkStoreRefs
    }
    
    // Other checks or current check without live data: use selectedCheck
    // Remap to 0-based indices since backend may send 1-based indices
    if (hasSelectedCheckData && selectedCheck.results) {
      return selectedCheck.results.map((ref, idx) => ({
        ...ref,
        index: idx  // Override with 0-based index
      }))
    }
    
    return []
  }, [isCurrentCheck, checkStoreRefs, hasSelectedCheckData, selectedCheck])

  // Build unified stats
  // For current check, prefer live checkStore stats; for other checks, compute from selectedCheck
  const displayStats = useMemo(() => {
    // Current check: use live WebSocket data from checkStore
    if (isCurrentCheck && checkStoreStats && checkStoreStats.total_refs > 0) {
      return checkStoreStats
    }
    
    if (hasSelectedCheckData) {
      const totalRefs = selectedCheck.total_refs || 0
      // For cancelled checks, processed_refs may be 0 but we have results - use results length
      const resultsCount = displayRefs?.filter(r => 
        r.status && !['pending', 'checking'].includes(r.status.toLowerCase())
      ).length || 0
      const processedRefs = selectedCheck.processed_refs ?? (isInProgress ? resultsCount : totalRefs)
      const errorsCount = selectedCheck.errors_count || 0
      const warningsCount = selectedCheck.warnings_count || 0
      const suggestionsCount = selectedCheck.suggestions_count || 0
      const unverifiedCount = selectedCheck.unverified_count || 0
      const hallucinationCount = selectedCheck.hallucination_count 
        ?? displayRefs?.filter(r => r.status === 'hallucination' || r.hallucination_assessment?.verdict === 'LIKELY').length 
        ?? 0
      
      // Use stored refs_verified if available, otherwise calculate
      const verifiedCount = selectedCheck.refs_verified ?? selectedCheck.verified_count ?? 
        Math.max(0, (isInProgress ? processedRefs : totalRefs) - errorsCount - warningsCount - unverifiedCount)
      
      // Use stored paper-level counts if available, otherwise compute from results
      let refsWithErrors = selectedCheck.refs_with_errors
      let refsWithWarningsOnly = selectedCheck.refs_with_warnings_only
      
      // If not stored, compute from results
      if (refsWithErrors === undefined && displayRefs?.length > 0) {
        refsWithErrors = displayRefs.filter(r => 
          r.errors?.some(e => e.error_type !== 'unverified')
        ).length
      }
      if (refsWithWarningsOnly === undefined && displayRefs?.length > 0) {
        refsWithWarningsOnly = displayRefs.filter(r => 
          r.warnings?.length > 0 && !r.errors?.some(e => e.error_type !== 'unverified')
        ).length
      }
      
      return {
        total_refs: totalRefs,
        processed_refs: processedRefs,
        verified_count: verifiedCount,
        refs_verified: verifiedCount,
        errors_count: errorsCount,
        warnings_count: warningsCount,
        suggestions_count: suggestionsCount,
        unverified_count: unverifiedCount,
        hallucination_count: hallucinationCount,
        refs_with_errors: refsWithErrors ?? 0,
        refs_with_warnings_only: refsWithWarningsOnly ?? 0,
        progress_percent: totalRefs > 0 ? (processedRefs / totalRefs) * 100 : 0,
      }
    }
    
    // Fallback to checkStore 
    if (checkStoreStats) {
      return checkStoreStats
    }
    
    // Default empty stats
    return {
      total_refs: 0,
      processed_refs: 0,
      verified_count: 0,
      refs_verified: 0,
      errors_count: 0,
      warnings_count: 0,
      suggestions_count: 0,
      unverified_count: 0,
      hallucination_count: 0,
      refs_with_errors: 0,
      refs_with_warnings_only: 0,
      progress_percent: 0,
    }
  }, [isCurrentCheck, checkStoreStats, hasSelectedCheckData, selectedCheck, displayRefs, isInProgress])

  // Document-level AI-generated-text detection: live result for the current
  // check, else the persisted result on a selected historical check.
  const displayAiDetection = useMemo(() => {
    if (isCurrentCheck && checkStoreAiDetection) return checkStoreAiDetection
    if (hasSelectedCheckData && selectedCheck.ai_detection) return selectedCheck.ai_detection
    return null
  }, [isCurrentCheck, checkStoreAiDetection, hasSelectedCheckData, selectedCheck])

  return (
    <main 
      ref={mainRef}
      className="flex-1 relative"
      style={{ backgroundColor: 'var(--color-bg-primary)', overflowY: 'scroll' }}
    >
      {/* Window-wide drag/drop overlay — handles both HTML5 drops AND
          Tauri's 'Open With → RefChecker' file-open events. */}
      <GlobalDropZone />

      <div ref={contentRef} className="max-w-4xl mx-auto p-4 space-y-4 lg:p-6 lg:space-y-6">
        {/* Global view toggle — switches the whole panel between the
            check view and the Seen References library. */}
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setGlobalView(null)}
            className="px-2 py-1 rounded border"
            style={{
              borderColor: 'var(--color-border)',
              color: globalView == null ? 'var(--color-accent, #3b82f6)' : 'var(--color-text-secondary)',
              backgroundColor: globalView == null ? 'var(--color-bg-secondary)' : 'transparent',
              fontWeight: globalView == null ? 600 : 400,
            }}
            type="button"
          >Current check</button>
          <button
            onClick={() => setGlobalView('seen')}
            className="px-2 py-1 rounded border"
            style={{
              borderColor: 'var(--color-border)',
              color: globalView === 'seen' ? 'var(--color-accent, #3b82f6)' : 'var(--color-text-secondary)',
              backgroundColor: globalView === 'seen' ? 'var(--color-bg-secondary)' : 'transparent',
              fontWeight: globalView === 'seen' ? 600 : 400,
            }}
            type="button"
            title="Every reference RefChecker has ever verified, across all checks"
          >Seen References (library)</button>
        </div>

        {globalView === 'seen' ? (
          <SeenReferencesView />
        ) : isViewingBatch ? (
          <BatchSummaryView />
        ) : (
        <>
        {/* Back-to-batch link — shown when the user drilled into a
            specific paper from a batch summary. v0.7.45. */}
        {selectedBatchId && isViewingCheck && (
          <button
            onClick={backToBatch}
            className="mb-2 text-xs px-2 py-1 rounded inline-flex items-center gap-1"
            style={{
              color: 'var(--color-accent, #3b82f6)',
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
            type="button"
            title="Return to the batch summary"
          >
            ← Back to batch
          </button>
        )}
        {/* First-launch guidance — only renders when something's missing */}
        {showInput && (
          <OnboardingBanner
            onOpenSettings={(section) => useSettingsStore.getState().openSettings(section)}
          />
        )}
        {showInput && <FieldGuide />}

        {/* Input Section */}
        {showInput && <InputSection />}

        {/* Status Section */}
        {showContent && (
          <StatusSection />
        )}

        {/* Stats Section — minimal health chip sits in its header row */}
        {showContent && (
          <StatsSection
            stats={displayStats}
            isComplete={isComplete}
            references={displayRefs}
            paperTitle={displayPaperTitle}
            paperSource={displayPaperSource}
            aiBand={displayAiDetection?.band}
            aiScore={displayAiDetection?.overall_score}
            videoKey={`statvid-${selectedCheckId}`}
            healthBadge={
              <>
                <HealthBadge references={displayRefs} />
                <LLMUsageBadge checkId={selectedCheckId} isComplete={isComplete} />
              </>
            }
          />
        )}

        {/* On-demand article tools in a 2×2 button grid — each pill keeps its
            cell and never shifts; clicking one opens its details full-width in
            the shared region directly below the grid (ActionPanelGrid owns the
            accordion). Capped at 760px so the pills don't stretch edge-to-edge. */}
        {showContent && isComplete && (
          <ActionPanelGrid>
            {/*
             * Per-article remount keys (#bug: cross-article result bleed).
             * In a batch, these on-demand panels keep their fetched results
             * in local state. Without a key tied to the selected article,
             * React reuses the same instance when switching articles, so
             * article A's Retraction / Gap-finder / Citation-numbering
             * results leak onto article B. Keying each on `selectedCheckId`
             * forces a fresh mount per article — every article gets its own
             * clean state and never inherits a sibling's results.
             */}
            <RetractionCheck
              key={`ret-${selectedCheckId}`}
              checkId={(selectedCheckId && selectedCheckId > 0) ? selectedCheckId : currentCheckId}
              references={displayRefs}
            />
            <GapFinder
              key={`gap-${selectedCheckId}`}
              checkId={(selectedCheckId && selectedCheckId > 0) ? selectedCheckId : currentCheckId}
              references={displayRefs}
            />
            <CitationIntegrity
              key={`cite-${selectedCheckId}`}
              checkId={(selectedCheckId && selectedCheckId > 0) ? selectedCheckId : currentCheckId}
            />
            <ArticleAssistant
              key={`assist-${selectedCheckId}`}
              checkId={(selectedCheckId && selectedCheckId > 0) ? selectedCheckId : currentCheckId}
            />
          </ActionPanelGrid>
        )}

        {/* Document-level AI-generated-text detection (opt-in) */}
        {showContent && displayAiDetection && (
          <AIDetectionPanel
            key={`ai-${selectedCheckId}`}
            detection={displayAiDetection}
            checkId={(selectedCheckId && selectedCheckId > 0) ? selectedCheckId : currentCheckId}
          />
        )}

        {/* References / Corrections tabs */}
        {showContent && (
          <div>
            <div
              className="flex items-center gap-1 mb-3 border-b"
              style={{ borderColor: 'var(--color-border)' }}
              role="tablist"
              aria-label="Results view"
            >
              {(() => {
                // Reflect the active Summary-chip filter in the tab pill
                // counts, not just in the in-page header. The corrections
                // count must apply the SAME style filter the Summary chips
                // and Corrections view apply — otherwise a ref whose only
                // issue is a style-suppressed venue mismatch (e.g.
                // "AJNR Am J Neuroradiol") shows as "Corrections 1" while
                // the page itself reads "No corrections needed", which
                // confuses the user.
                const refsForCount = (statusFilter || []).length
                  ? applyStatusFilter(displayRefs, statusFilter, isComplete)
                  : (displayRefs || [])
                const correctionsCount = (refsForCount || []).filter(r => {
                  const filteredErrors = filterIssuesForStyle(r.errors, r, activeStyle)
                  const filteredWarnings = filterIssuesForStyle(r.warnings, r, activeStyle)
                  return (
                    (filteredErrors || []).length ||
                    (filteredWarnings || []).length ||
                    r.status === 'unverified' ||
                    r.status === 'hallucinated'
                  )
                }).length
                return [
                  ['references', 'References', refsForCount.length],
                  ['corrections', 'Corrections', correctionsCount],
                  ['graph', 'Graph', refsForCount.length],
                  ['similar', 'Similar Papers', null],
                ]
              })().map(([key, label, count]) => {
                const active = resultsTab === key
                return (
                  <button
                    key={key}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setResultsTab(key)}
                    className="px-3 py-1.5 text-sm font-medium transition-colors"
                    style={{
                      color: active ? 'var(--color-accent, #3b82f6)' : 'var(--color-text-secondary)',
                      borderBottom: active ? '2px solid var(--color-accent, #3b82f6)' : '2px solid transparent',
                      marginBottom: '-1px',
                    }}
                    type="button"
                  >
                    {label}
                    {count != null && (
                      <span
                        className="ml-1.5 text-xs px-1.5 py-0.5 rounded-full"
                        style={{
                          backgroundColor: active ? 'var(--color-accent-muted, rgba(59,130,246,0.15))' : 'var(--color-bg-tertiary)',
                          color: active ? 'var(--color-accent, #3b82f6)' : 'var(--color-text-secondary)',
                        }}
                      >
                        {count}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
            {/*
             * Tabs render with display:none rather than unmount/remount,
             * so internal component state survives a tab switch. Graph
             * was the primary motivator — `expandedNodes` and the loaded
             * S2 co-citation `serverGraph` used to reset whenever the
             * user clicked away to References and back, throwing away
             * the 2nd-degree expansion they'd just run. Now every tab's
             * state is preserved as long as the parent stays mounted.
             *
             * Cost: each tab continues running its effects in the
             * background (e.g. the force-graph simulation, if any). The
             * libs in use (react-force-graph-2d, the similar-papers
             * fetch) are cheap enough that this is a net win for UX.
             */}
            <div style={{ display: resultsTab === 'references' ? 'block' : 'none' }}>
              <ReferenceList
                references={displayRefs}
                isLoading={isLoadingDetail}
                isCheckComplete={isComplete}
              />
            </div>
            <div style={{ display: resultsTab === 'corrections' ? 'block' : 'none' }}>
              <CorrectionsView
                references={displayRefs}
                isCheckComplete={isComplete}
              />
            </div>
            <div style={{ display: resultsTab === 'graph' ? 'block' : 'none' }}>
              <GraphView references={displayRefs} paperTitle={displayPaperTitle} />
            </div>
            <div style={{ display: resultsTab === 'similar' ? 'block' : 'none' }}>
              {/* ResearchRabbit-style Explore graph entry (#68): opens a
                  fullscreen overlay graphing the similar / cites&refs
                  neighbourhood of this check's references, by year. */}
              <div className="flex justify-end mb-2">
                <button
                  type="button"
                  onClick={() => setShowExplore(true)}
                  className="text-xs px-2.5 py-1 rounded inline-flex items-center gap-1"
                  style={{
                    color: 'var(--color-accent, #3b82f6)',
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                  }}
                  title="Open a fullscreen graph of similar / cited papers, positioned by year"
                >
                  Explore graph →
                </button>
              </div>
              <SimilarPapersPanel
                key={`similar-${selectedCheckId}`}
                references={displayRefs}
                paperTitle={displayPaperTitle}
                paperSource={displayPaperSource}
                checkId={(selectedCheckId && selectedCheckId > 0) ? selectedCheckId : currentCheckId}
                onCheckPaper={(source) => {
                  // Switch UI to "New refcheck" so the input panel is visible,
                  // then dispatch the URL to InputSection which auto-submits.
                  useHistoryStore.getState().selectCheck?.(-1)
                  const url = String(source || '').match(/^https?:\/\//)
                    ? source
                    : `https://arxiv.org/abs/${source}`
                  window.dispatchEvent(new CustomEvent('refchecker:check-url', { detail: { url } }))
                }}
              />
            </div>
          </div>
        )}
        </>
        )}
      </div>

      {/* ResearchRabbit-style Explore graph overlay (#68) — graphs the
          similar / cites&refs neighbourhood of the current check's
          references, positioned + coloured by year. Real data only. */}
      {showExplore && (
        <ExploreGraphView
          references={displayRefs}
          paperTitle={displayPaperTitle}
          paperSource={displayPaperSource}
          onClose={() => setShowExplore(false)}
        />
      )}

      {/* Scroll to top button — pinned to the viewport's bottom-right corner,
          but STACKED ABOVE the round debug "</>" toggle (DebugPanel.jsx, which
          sits at bottom-4 right-4 ≈ 40px tall). We share that button's right
          edge and push our bottom up past its height + a gap so the two never
          overlap. Higher z so it floats above panels. */}
      {showScrollTop && (
        <button
          onClick={scrollToTop}
          className="fixed z-50 p-2 rounded-full shadow-lg transition-all duration-200 hover:scale-110 opacity-60 hover:opacity-100"
          style={{
            backgroundColor: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
            // Align with the debug button's right edge (right-4 = 1rem) and
            // stack above it: debug bottom (1rem) + its height (~2.5rem) +
            // a 0.75rem gap ≈ 4.25rem, rounded to 4.5rem for clearance.
            right: '1rem',
            bottom: '4.5rem',
          }}
          title="Scroll to top"
          aria-label="Scroll to top"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
          </svg>
        </button>
      )}
    </main>
  )
}
