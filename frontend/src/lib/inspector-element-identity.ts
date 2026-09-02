/**
 * Stable identities for inspector targets.
 *
 * A saved edit must identify the same element in the editor iframe and on the
 * public delivery host.  Counting children from `body` cannot do that: Next,
 * analytics and preview chrome legitimately add their own nodes.  New edits
 * therefore use either the authored `data-edit-id` or an automatically derived
 * identity rooted at the artifact's own `<main>`, never a document position.
 */

const AUTHORED_ATTRIBUTE = 'data-edit-id';
const GENERATED_ATTRIBUTE = 'data-dan-edit-id';
const AUTO_PREFIX = 'auto:';

function isRuntimeNode(el: Element): boolean {
  const tag = el.tagName.toLowerCase();
  return tag === 'script' || tag === 'style' || tag === 'link' || tag === 'meta'
    || el.hasAttribute('data-dan-preview-ui');
}

function rootFor(el: Element): Element {
  return el.closest('main') || el.ownerDocument.body;
}

function siblingOrdinal(el: Element): number {
  const parent = el.parentElement;
  if (!parent) return 0;
  const tag = el.tagName.toLowerCase();
  return Array.from(parent.children)
    .filter((child) => !isRuntimeNode(child) && child.tagName.toLowerCase() === tag)
    .indexOf(el);
}

/** The deterministic generated ID. This function does not mutate the DOM. */
export function generatedElementId(el: Element): string {
  const root = rootFor(el);
  const parts: string[] = [];
  let current: Element | null = el;
  while (current) {
    parts.unshift(`${current.tagName.toLowerCase()}:${siblingOrdinal(current)}`);
    if (current === root) break;
    current = current.parentElement;
  }
  return `${AUTO_PREFIX}${parts.join('/')}`;
}

function authoredIdFor(el: Element): string | null {
  let current: Element | null = el;
  while (current && current !== el.ownerDocument.body) {
    const id = current.getAttribute(AUTHORED_ATTRIBUTE) || current.getAttribute(GENERATED_ATTRIBUTE);
    if (id) return id;
    current = current.parentElement;
  }
  return null;
}

/**
 * Return the one durable key used for all new writes.  For old artifact code
 * without authored markers we attach a deterministic marker on first editing;
 * the same identity can be recomputed on the public document without relying
 * on that attribute having been rendered there.
 */
export function durableElementKey(el: Element): string {
  const authored = authoredIdFor(el);
  if (authored) return `@${authored}`;
  const id = generatedElementId(el);
  el.setAttribute(GENERATED_ATTRIBUTE, id);
  return `@${id}`;
}

function selectorEscape(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`);
}

/** Resolve a durable key in any representation of the same artifact. */
export function findDurableElement(doc: Document, key: string): Element | null {
  if (!key.startsWith('@')) return null;
  const id = key.slice(1);
  try {
    const direct = doc.querySelector(
      `[${AUTHORED_ATTRIBUTE}="${selectorEscape(id)}"], [${GENERATED_ATTRIBUTE}="${selectorEscape(id)}"]`,
    );
    if (direct) return direct;
  } catch {
    return null;
  }
  if (!id.startsWith(AUTO_PREFIX)) return null;
  // Existing artifacts did not render data-dan-edit-id. Recompute it from
  // their artifact-local structure rather than inventing a second address.
  // The auto identity is rooted at the artifact's <main>, or at <body> when the
  // page has no <main> (the key itself records which: `auto:main:…` / `auto:body:…`).
  // Searching only inside <main> for a body-rooted key can never match.
  const scope = id.startsWith(`${AUTO_PREFIX}main:`) ? 'main *' : 'body *';
  for (const candidate of Array.from(doc.querySelectorAll(scope))) {
    if (!isRuntimeNode(candidate) && generatedElementId(candidate) === id) return candidate;
  }
  return null;
}

/**
 * Compatibility resolver for records created before durable IDs existed.
 * It first follows the old route exactly, then ignores infrastructure nodes at
 * a broken level.  This is read-only compatibility; no new save may emit it.
 */
export function findLegacyElement(doc: Document, key: string): Element | null {
  const parts = key.split('>');
  let current: Element | null = doc.body;
  for (const part of parts) {
    const match = part.match(/^(.+?)\[(\d+)\]$/);
    if (!match || !current) return null;
    const [, rawTag, rawIndex] = match;
    const tag = rawTag.toLowerCase();
    const index = Number(rawIndex);
    const exact: Element | undefined = current.children[index];
    if (exact && exact.tagName.toLowerCase() === tag) {
      current = exact;
      continue;
    }
    const matching: Element[] = Array.from(current.children)
      .filter((child) => !isRuntimeNode(child) && child.tagName.toLowerCase() === tag);
    // A unique same-tag child is unambiguous even when application chrome has
    // changed the old absolute child index (the regression seen in Moonbox).
    if (matching.length === 1) {
      current = matching[0];
      continue;
    }
    return null;
  }
  return current;
}
