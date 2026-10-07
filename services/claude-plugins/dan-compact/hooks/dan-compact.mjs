// dan-compact: Claude Code function-hook module. Wires the engine's `$` to
// the engine-free logic in core.mjs. Loaded per session with
// `claude --plugin-dir services/claude-plugins/dan-compact` and
// CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 (Dan's cli_runner adds both when the
// TypeSafe key is available; see app/agent/cli_runner.py).

import { compactWithJev, maybeCompactAtTurnEnd } from './core.mjs';

/** Every variable the plugin reads, each by literal (what `claude plugin validate` lists). */
async function readEnv($) {
  return {
    TYPESAFE_API_KEY: await $.env.get('TYPESAFE_API_KEY'),
    TYPESAFE_MODEL: await $.env.get('TYPESAFE_MODEL'),
    TYPESAFE_BASE_URL: await $.env.get('TYPESAFE_BASE_URL'),
    DAN_COMPACT_KEEP_THRESHOLD: await $.env.get('DAN_COMPACT_KEEP_THRESHOLD'),
    DAN_COMPACT_MONTHLY_CAP_JPY: await $.env.get('DAN_COMPACT_MONTHLY_CAP_JPY'),
    DAN_COMPACT_LEDGER_PATH: await $.env.get('DAN_COMPACT_LEDGER_PATH'),
    DAN_COMPACT_AT_PERCENT: await $.env.get('DAN_COMPACT_AT_PERCENT'),
    DAN_COMPACT_MIN_REDUCTION: await $.env.get('DAN_COMPACT_MIN_REDUCTION'),
    DAN_COMPACT_PRESERVE_RECENT: await $.env.get('DAN_COMPACT_PRESERVE_RECENT'),
    DAN_COMPACT_JPY_PER_MTOKEN: await $.env.get('DAN_COMPACT_JPY_PER_MTOKEN'),
    USERPROFILE: await $.env.get('USERPROFILE'),
    HOME: await $.env.get('HOME'),
  };
}

function depsFor($, env) {
  return {
    env,
    fs: {
      read: (path) => $.fs.read(path),
      write: (path, text) => $.fs.write(path, text),
      exists: (path) => $.fs.exists(path),
    },
    fetch: async (url, init) => {
      const response = await $.http.fetch(url, init);
      return { status: response.status, ok: response.ok, text: response.text };
    },
    log: (text) => $.ui.log(text),
    now: () => new Date(),
  };
}

/** The two session calls the turn-end hook makes, each spelled at its call site. */
function sessionFor($) {
  return {
    usage: () => $.session.usage(),
    compact: () => $.session.compact(),
  };
}

export const register = (on) => {
  const state = { compacting: false, lastTokens: undefined };

  on('session.compact', async ($, e, next) => {
    let deps;
    try {
      deps = depsFor($, await readEnv($));
    } catch (error) {
      $.ui.log(`dan-compact: 組み込み要約に戻す (setup error: ${error instanceof Error ? error.message : String(error)})`);
      return next(e);
    }
    return compactWithJev(deps, e, next);
  });

  on('turn.complete', async ($, e, next) => {
    let deps;
    try {
      deps = depsFor($, await readEnv($));
    } catch {
      return next(e);
    }
    return maybeCompactAtTurnEnd(deps, sessionFor($), state, e, next);
  });
};
