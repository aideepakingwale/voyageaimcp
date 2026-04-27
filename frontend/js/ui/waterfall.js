/**
 * Waterfall & MCP chip animations.
 * Shows which LLM provider is being tried and which MCP servers are active.
 */
import { $$, $ } from '../utils/dom.js';

/** Reset all provider chips to idle state. */
export function resetProviderChips() {
  $$('.pc').forEach(c => { c.className = 'pc idle'; });
}

/**
 * Highlight a specific provider chip.
 * state: 'trying' | 'ok' | 'fail'
 */
export function highlightProvider(name, state) {
  resetProviderChips();
  const chip = $(`.pc[data-p="${name}"]`);
  if (chip) chip.className = `pc ${state}`;
}

/**
 * Apply waterfall status from API health check.
 * Updates tooltip and styling per provider.
 */
export function applyWaterfallStatus(status, activeProvider = null) {
  for (const [name, info] of Object.entries(status || {})) {
    const chip = $(`.pc[data-p="${name}"]`);
    if (!chip) continue;

    chip.className = `pc ${name === activeProvider ? 'ok' : info.available ? 'idle' : 'fail'}`;
    chip.title     = [
      `${name}: ${info.available ? '✓ available' : '✗ not configured'}`,
      `${info.success_rate ?? 0}% success`,
      `avg ${info.avg_latency_ms ?? 0}ms`,
      info.total_cost_usd > 0 ? `$${info.total_cost_usd.toFixed(4)}` : 'FREE',
    ].join(' · ');
  }
}

/** Start MCP loading animation (called before API request). */
export function startMcpAnimation() {
  $$('.mcp-chip').forEach((c, i) => {
    setTimeout(() => c.classList.add('loading'), i * 55);
  });
}

/** Settle MCP chips to active state (called after response). */
export function settleMcpChips() {
  $$('.mcp-chip').forEach(c => {
    c.classList.remove('loading');
    c.classList.add('active');
  });
}
