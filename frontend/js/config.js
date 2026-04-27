/**
 * VoyageAI Frontend Configuration
 * Change USE_DEMO to false for live LLM responses.
 */
export const Config = {
  /** Set false to call live LLM waterfall (requires backend API keys). */
  USE_DEMO: false,

  /** Backend base URL — overridden by window.VOYAGE_API if set. */
  API_BASE: window?.VOYAGE_API || 'http://localhost:5000/api',

  /** GDS session window in seconds (must match backend Config). */
  GDS_SESSION_TIMEOUT: 600,
};
