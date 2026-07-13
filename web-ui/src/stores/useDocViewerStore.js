import { create } from 'zustand'

/**
 * Cross-component bridge for "open the native document and highlight this
 * passage". A ReferenceCard (deep in the references list) can request that the
 * StatusSection preview overlay open and locate+highlight a citation context in
 * the real PDF — reusing the same PyMuPDF locate machinery as the AI-flagged
 * passage highlights. `seq` makes repeated requests for the same text re-fire.
 */
export const useDocViewerStore = create((set) => ({
  citation: null, // { text, label, seq }
  requestCitation: (payload) =>
    set((s) => ({ citation: { ...payload, seq: (s.citation?.seq || 0) + 1 } })),
  clearCitation: () => set({ citation: null }),
}))
