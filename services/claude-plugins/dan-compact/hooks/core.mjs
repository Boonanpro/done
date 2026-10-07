// dan-compact: the part of the plugin that has no engine in it.
//
// Everything the hook needs from outside (environment, files, HTTP, log,
// clock) comes in through `deps`, so `node --test` can drive it with a fake
// Jev, a fake ledger file and a fixed clock; `dan-compact.mjs` wires the
// same functions to Claude Code's `$`.
//
// The library does the compaction (tool calls and tool results only; user
// and assistant text is never touched). This file adds what Dan needs on
// top of upstream's hooks/fast-jev.ts: configuration from environment
// variables, a monthly yen cap with a ledger, cost accounting from the
// tokens actually sent to Jev, and a guaranteed fallback to Claude Code's
// built-in summary on every failure.

import { compact, reductionRatio } from '../node_modules/fast-jev-compaction/dist/compact.js';
import {
  buildJevRequest,
  DEFAULT_MODEL,
  parseJevResponse,
} from '../node_modules/fast-jev-compaction/dist/request.js';
import { estimateTokens } from '../node_modules/fast-jev-compaction/dist/state.js';

/**
 * Defaults. `jpyPerMillionTokens`: TypeSafe lists Jev at $42 per billion
 * input tokens (typesafe.ai, read 2026-10-07) = $0.042 per million, the same
 * figure app/services/jev_browser_budget.py uses; at 150 JPY/USD that is
 * 6.3 yen per million input tokens. Output tokens are a few hundred per
 * request and are ignored.
 */
export const DEFAULTS = Object.freeze({
  keepThreshold: 0.3,
  preserveRecentMessages: 6,
  // 0 = the turn.complete trigger is off. Dan runs Claude Code headless (-p),
  // where `$.session.compact()` is "not available in a headless (-p / SDK)
  // session yet" (Claude Code 2.1.289, measured 2026-10-07); the engine's own
  // auto trigger still dispatches `session.compact` to this plugin. Set
  // DAN_COMPACT_AT_PERCENT for an interactive session.
  compactAtPercent: 0,
  minReductionRatio: 0.25,
  monthlyCapJpy: 100,
  jpyPerMillionTokens: 6.3,
  model: DEFAULT_MODEL,
  maxStateTokens: 25_000,
  maxRequestTokens: 30_000,
  truncateHeadChars: 300,
});

export const LEDGER_RELATIVE_PATH = ['.dan', 'workspace', 'memory', '.compact_jev_ledger.json'];

/** Names of the environment variables the plugin reads (the register module reads each by literal). */
export const ENV_NAMES = Object.freeze([
  'TYPESAFE_API_KEY',
  'TYPESAFE_MODEL',
  'TYPESAFE_BASE_URL',
  'DAN_COMPACT_KEEP_THRESHOLD',
  'DAN_COMPACT_MONTHLY_CAP_JPY',
  'DAN_COMPACT_LEDGER_PATH',
  'DAN_COMPACT_AT_PERCENT',
  'DAN_COMPACT_MIN_REDUCTION',
  'DAN_COMPACT_PRESERVE_RECENT',
  'DAN_COMPACT_JPY_PER_MTOKEN',
  'USERPROFILE',
  'HOME',
]);

export function parseNumber(raw, fallback, { min = -Infinity, max = Infinity } = {}) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

function nonEmpty(raw) {
  return typeof raw === 'string' && raw.trim().length > 0 ? raw.trim() : undefined;
}

function homeDir(env) {
  return nonEmpty(env.USERPROFILE) ?? nonEmpty(env.HOME);
}

function joinPath(base, parts) {
  const sep = base.includes('\\') && !base.includes('/') ? '\\' : '/';
  const trimmed = base.replace(/[\\/]+$/, '');
  return [trimmed, ...parts].join(sep);
}

/** Reads the configuration from a plain `{ NAME: value }` object. The key is in `apiKey` and must never be logged. */
export function readConfig(env) {
  const home = homeDir(env);
  const ledgerPath =
    nonEmpty(env.DAN_COMPACT_LEDGER_PATH) ?? (home ? joinPath(home, LEDGER_RELATIVE_PATH) : undefined);
  return {
    apiKey: nonEmpty(env.TYPESAFE_API_KEY),
    model: nonEmpty(env.TYPESAFE_MODEL) ?? DEFAULTS.model,
    baseUrl: nonEmpty(env.TYPESAFE_BASE_URL),
    keepThreshold: parseNumber(env.DAN_COMPACT_KEEP_THRESHOLD, DEFAULTS.keepThreshold, { min: 0, max: 1 }),
    monthlyCapJpy: parseNumber(env.DAN_COMPACT_MONTHLY_CAP_JPY, DEFAULTS.monthlyCapJpy, { min: 0 }),
    compactAtPercent: parseNumber(env.DAN_COMPACT_AT_PERCENT, DEFAULTS.compactAtPercent, { min: 0, max: 100 }),
    minReductionRatio: parseNumber(env.DAN_COMPACT_MIN_REDUCTION, DEFAULTS.minReductionRatio, { min: 0, max: 1 }),
    preserveRecentMessages: Math.floor(
      parseNumber(env.DAN_COMPACT_PRESERVE_RECENT, DEFAULTS.preserveRecentMessages, { min: 0 }),
    ),
    jpyPerMillionTokens: parseNumber(env.DAN_COMPACT_JPY_PER_MTOKEN, DEFAULTS.jpyPerMillionTokens, { min: 0 }),
    maxStateTokens: DEFAULTS.maxStateTokens,
    maxRequestTokens: DEFAULTS.maxRequestTokens,
    truncateHeadChars: DEFAULTS.truncateHeadChars,
    ledgerPath,
  };
}

export function monthKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

export function emptyLedger(month) {
  return { month, yen: 0, runs: 0, last: null };
}

/** A ledger as stored, reset when it is from another month or unreadable. */
export function normalizeLedger(raw, month) {
  if (!raw || typeof raw !== 'object' || raw.month !== month) return emptyLedger(month);
  const yen = Number(raw.yen);
  const runs = Number(raw.runs);
  return {
    month,
    yen: Number.isFinite(yen) && yen >= 0 ? yen : 0,
    runs: Number.isFinite(runs) && runs >= 0 ? Math.floor(runs) : 0,
    last: raw.last && typeof raw.last === 'object' ? raw.last : null,
  };
}

export async function loadLedger(fs, path, month) {
  if (!path) return emptyLedger(month);
  try {
    if (!(await fs.exists(path))) return emptyLedger(month);
    return normalizeLedger(JSON.parse(await fs.read(path)), month);
  } catch {
    return emptyLedger(month);
  }
}

export async function saveLedger(fs, path, ledger) {
  if (!path) return false;
  try {
    await fs.write(path, JSON.stringify(ledger, null, 1) + '\n');
    return true;
  } catch {
    return false;
  }
}

export function yenFor(tokens, jpyPerMillionTokens) {
  return (tokens / 1_000_000) * jpyPerMillionTokens;
}

function round(value, digits) {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

/**
 * A `JevAsker` over `fetchFn` that counts what each request cost: the input
 * tokens Jev reports (`usage.input_tokens`), or the library's estimate of the
 * request body when the response carries no usage.
 */
export function meteredAsker(fetchFn, config) {
  const spent = { requests: 0, tokens: 0, chars: 0, reported: 0 };
  return {
    spent,
    async ask(state, questions) {
      const request = buildJevRequest(
        { apiKey: config.apiKey, model: config.model, baseUrl: config.baseUrl },
        state,
        questions,
      );
      const estimated = estimateTokens(request.body);
      spent.requests += 1;
      spent.chars += request.body.length;
      spent.tokens += estimated;
      const response = await fetchFn(request.url, {
        method: request.method,
        headers: request.headers,
        body: request.body,
      });
      const parsed = parseJevResponse(response.status, response.ok, response.text);
      const reported = parsed?.usage?.input_tokens;
      if (typeof reported === 'number' && Number.isFinite(reported) && reported > 0) {
        spent.tokens += reported - estimated;
        spent.reported += 1;
      }
      return parsed;
    },
  };
}

/**
 * Maps the library's output back onto the engine's session messages (same
 * as upstream hooks/fast-jev.ts): an untouched message, tool use or tool
 * result is the engine's own object, `handle` included; a rebuilt one has
 * no handle, so the engine takes its content as built.
 */
export function toSessionMessages(input, output) {
  const messages = new Map();
  const uses = new Map();
  const results = new Map();
  for (const message of input) {
    messages.set(message, message);
    for (const tool of message.toolUses ?? []) uses.set(tool, tool);
    for (const result of message.toolResults ?? []) results.set(result, result);
  }
  return output.map((message) => {
    const own = messages.get(message);
    if (own) return own;
    const rebuilt = {
      role: message.role,
      text: message.text,
      toolUses: message.toolUses.map((tool) => uses.get(tool) ?? toolUseSummary(tool)),
    };
    if (message.toolResults && message.toolResults.length > 0) {
      rebuilt.toolResults = message.toolResults.map(
        (result) => results.get(result) ?? toolResultSummary(result),
      );
    }
    return rebuilt;
  });
}

function toolUseSummary(tool) {
  const summary = { tool_use_id: tool.tool_use_id, tool: tool.tool, input: tool.input };
  if (tool.text !== undefined) summary.text = tool.text;
  if (tool.isError) summary.isError = true;
  return summary;
}

function toolResultSummary(result) {
  return { tool_use_id: result.tool_use_id, text: result.text, isError: result.isError ?? false };
}

const ENGINE_NOTE_PREFIXES = ['<system-reminder', '<local-command', '<command-', '<task-notification'];

/**
 * How many messages the turn in progress spans: from the last plain user
 * prompt (text, no tool results, not an engine-injected note) to the end,
 * inclusive; 0 when there is none. The engine's auto compaction runs in the
 * middle of a turn (measured 2026-10-07: a Read result the assistant had not
 * yet reported was dropped and the answer was guessed), so nothing from the
 * current turn is offered to Jev.
 */
export function currentTurnLength(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (!m || m.role !== 'user') continue;
    if ((m.toolResults?.length ?? 0) > 0) continue;
    const text = (m.text ?? '').trim();
    if (!text) continue;
    if (ENGINE_NOTE_PREFIXES.some((p) => text.startsWith(p))) continue;
    return messages.length - i;
  }
  return 0;
}

/** Replaces the key wherever it could appear and bounds the text. */
export function sanitize(text, apiKey, maxChars = 240) {
  let out = String(text ?? '');
  if (apiKey) out = out.split(apiKey).join('***');
  out = out.replace(/\s+/g, ' ').trim();
  return out.length > maxChars ? `${out.slice(0, maxChars)}...` : out;
}

/** The one log line (and `ledger.last`) for an outcome. */
export function summaryLine(outcome) {
  const o = outcome;
  const cost = `jev requests=${o.requests ?? 0} tokens=${o.tokens ?? 0} yen=${round(o.yen ?? 0, 4)} month_yen=${round(o.monthYen ?? 0, 4)}/${o.capJpy ?? '?'}`;
  if (o.outcome === 'compacted') {
    return (
      `dan-compact: Jev で短縮: 呼び出し ${o.callsDropped} 件を捨てた・結果 ${o.resultsDropped} 件を切り詰めた・` +
      `${o.kept} 件残した (pinned ${o.pinned}); ${o.charsBefore}字→${o.charsAfter}字 (${Math.round((o.ratio ?? 0) * 100)}%減); ` +
      `messages ${o.messagesBefore}→${o.messagesAfter}; threshold=${o.keepThreshold}; ${cost}; ${o.ms ?? 0}ms`
    );
  }
  return `dan-compact: 組み込み要約に戻す (${o.reason}); ${cost}`;
}

const NO_MESSAGES = Object.freeze([]);

/**
 * One `session.compact` run. `deps`: `{ env, fs, fetch, log, now }` where
 * `env` is a plain object of the variables, `fs` has `read/write/exists`,
 * `fetch(url, init)` resolves `{ status, ok, text }`, `log(text)` writes one
 * line and `now()` is a Date. Resolves `{ messages }` when Jev's pruning
 * replaces the summary, otherwise whatever `next(event)` (the built-in
 * summary) resolves. Never throws past itself; never logs the key.
 */
export async function compactWithJev(deps, event, next) {
  const config = readConfig(deps.env ?? {});
  const now = (deps.now ?? (() => new Date()))();
  const month = monthKey(now);
  const ledger = await loadLedger(deps.fs, config.ledgerPath, month);
  const messages = event?.messages ?? NO_MESSAGES;
  // Never offer the turn in progress to Jev (see currentTurnLength).
  const preserveRecent = Math.max(config.preserveRecentMessages, currentTurnLength(messages));
  const base = {
    at: now.toISOString(),
    trigger: event?.trigger,
    agentId: event?.agentId,
    keepThreshold: config.keepThreshold,
    preserveRecent,
    capJpy: config.monthlyCapJpy,
    messagesBefore: messages.length,
  };

  const finish = async (outcome, spent) => {
    const tokens = spent?.tokens ?? 0;
    const yen = yenFor(tokens, config.jpyPerMillionTokens);
    if (spent && spent.requests > 0) {
      ledger.yen = round(ledger.yen + yen, 6);
      ledger.runs += 1;
    }
    const record = {
      ...base,
      ...outcome,
      requests: spent?.requests ?? 0,
      tokens,
      chars: spent?.chars ?? 0,
      yen: round(yen, 6),
      monthYen: ledger.yen,
    };
    ledger.last = record;
    const saved = await saveLedger(deps.fs, config.ledgerPath, ledger);
    const line = summaryLine(record) + (saved ? '' : ' (ledger not saved)');
    try {
      deps.log?.(sanitize(line, config.apiKey, 1000));
    } catch {
      /* logging must never break compaction */
    }
    return record;
  };

  if (!config.apiKey) {
    await finish({ outcome: 'fallback', reason: 'no TYPESAFE_API_KEY' });
    return next(event);
  }
  if (ledger.yen >= config.monthlyCapJpy) {
    await finish({
      outcome: 'fallback',
      reason: `monthly cap reached (${round(ledger.yen, 4)} >= ${config.monthlyCapJpy} yen, ${month})`,
    });
    return next(event);
  }

  const asker = meteredAsker(deps.fetch, config);
  let result;
  try {
    result = await compact(messages, asker, {
      keepThreshold: config.keepThreshold,
      preserveRecentMessages: preserveRecent,
      maxStateTokens: config.maxStateTokens,
      maxRequestTokens: config.maxRequestTokens,
      truncateHeadChars: config.truncateHeadChars,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await finish({ outcome: 'fallback', reason: `jev error: ${sanitize(message, config.apiKey)}` }, asker.spent);
    return next(event);
  }

  const ratio = reductionRatio(result);
  const stats = result.stats;
  const detail = {
    charsBefore: stats.charsBefore,
    charsAfter: stats.charsAfter,
    messagesAfter: stats.messagesAfter,
    calls: stats.calls,
    kept: stats.kept,
    resultsDropped: stats.resultsDropped,
    callsDropped: stats.callsDropped,
    pinned: stats.pinned,
    stateTokens: stats.stateTokens,
    stateStage: stats.stateStage,
    ratio: round(ratio, 4),
    ms: stats.ms,
  };
  if (ratio < config.minReductionRatio) {
    await finish(
      {
        outcome: 'fallback',
        reason: `reduction ${Math.round(ratio * 100)}% below minimum ${Math.round(config.minReductionRatio * 100)}%`,
        ...detail,
      },
      asker.spent,
    );
    return next(event);
  }

  let mapped;
  try {
    mapped = toSessionMessages(messages, result.messages);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await finish({ outcome: 'fallback', reason: `mapping error: ${sanitize(message, config.apiKey)}`, ...detail }, asker.spent);
    return next(event);
  }
  await finish({ outcome: 'compacted', ...detail }, asker.spent);
  return { messages: mapped };
}

/**
 * The `turn.complete` side: asks the engine to compact once the context
 * reaches `compactAtPercent` (0 disables). `state` lives in the register
 * module: `{ compacting, lastTokens }`. A second attempt at the same token
 * count is skipped (the previous compaction did not take, so asking again
 * would only spend Jev requests).
 */
export async function maybeCompactAtTurnEnd(deps, session, state, event, next) {
  const config = readConfig(deps.env ?? {});
  if (config.compactAtPercent <= 0 || state.compacting) return next(event);
  try {
    const usage = await session.usage();
    const percent = usage?.context?.percent ?? 0;
    const tokens = usage?.context?.tokens;
    if (percent < config.compactAtPercent) return next(event);
    if (tokens !== undefined && tokens === state.lastTokens) return next(event);
    state.compacting = true;
    state.lastTokens = tokens;
    deps.log?.(`dan-compact: context ${percent}% >= ${config.compactAtPercent}% -> compaction requested`);
    await session.compact();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    deps.log?.(`dan-compact: auto-compact skipped (${sanitize(message, config.apiKey)})`);
  } finally {
    state.compacting = false;
  }
  return next(event);
}
