'use client';

import { createContext, createElement, useContext, Fragment } from 'react';
import type { ComponentPropsWithoutRef, CSSProperties, ElementType, ReactNode } from 'react';

import {
  computeTextSegments,
  cssToReactStyle,
  type EditableOverride,
} from '@/lib/editable-release';

/**
 * The stable editing contract for generated sites.
 *
 * - Every editable text block renders through `EditableText` with a durable
 *   `editId`.  The inspector records edits against `@<editId>`, which survives
 *   harmless DOM rearrangement.
 * - Publishing writes the released overrides into the artifact directory
 *   (`release.gen.json`); the artifact's server `page.tsx` feeds them to
 *   `EditableProvider`.  `EditableText` then renders the released content
 *   during server rendering, so the very first HTML byte already carries the
 *   latest published text.  There is no client-side patching on delivery.
 */

const EditableOverridesContext = createContext<Record<string, EditableOverride>>({});

export function EditableProvider({
  overrides,
  children,
}: {
  overrides: Record<string, EditableOverride>;
  children: ReactNode;
}) {
  return (
    <EditableOverridesContext.Provider value={overrides}>
      {children}
    </EditableOverridesContext.Provider>
  );
}

/**
 * Render an override's text+spans exactly like the inspector's own renderer
 * (inspector-render.ts): flat span list, merged overlapping styles, `\n` → <br>.
 */
function renderOverrideText(override: EditableOverride): ReactNode {
  const text = override.text ?? '';
  const segments = computeTextSegments(text, override.spans);
  return segments.map((seg, i) => {
    const lines = seg.text.split('\n');
    const content = lines.map((line, j) => (
      <Fragment key={j}>
        {j > 0 && <br />}
        {line}
      </Fragment>
    ));
    if (Object.keys(seg.style).length === 0) {
      return <Fragment key={i}>{content}</Fragment>;
    }
    return (
      <span key={i} data-dan-edit="1" style={cssToReactStyle(seg.style) as CSSProperties}>
        {content}
      </span>
    );
  });
}

/** React が特別扱いする属性へ素の HTML 属性名から橋渡しする。 */
const ATTR_NAME_MAP: Record<string, string> = {
  class: 'className',
  for: 'htmlFor',
};

function overrideProps(
  override: EditableOverride | undefined,
  baseStyle: CSSProperties | undefined,
): Record<string, unknown> {
  if (!override) return {};
  const props: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(override.extraAttrs)) {
    props[ATTR_NAME_MAP[name] || name] = value;
  }
  if (Object.keys(override.blockStyle).length > 0) {
    props.style = { ...baseStyle, ...cssToReactStyle(override.blockStyle) };
  }
  return props;
}

/**
 * It intentionally renders the native HTML tag without a wrapper, so a page's
 * layout and CSS remain completely under the generator's control.  The only
 * addition is a durable identity plus, when a published override exists for
 * that identity, the released text/style rendered in place of the source
 * children.
 */
export function EditableText<T extends ElementType = 'span'>({
  as,
  editId,
  children,
  ...props
}: { as?: T; editId: string; children?: ReactNode } & Omit<
  ComponentPropsWithoutRef<T>,
  'as' | 'children' | 'data-edit-id'
>) {
  const overrides = useContext(EditableOverridesContext);
  const override = overrides[editId];
  const Tag = (as || 'span') as ElementType;
  const { style, ...rest } = props as { style?: CSSProperties } & Record<string, unknown>;
  const content = override && override.text !== null ? renderOverrideText(override) : children;
  return createElement(
    Tag,
    {
      'data-edit-id': editId,
      style,
      ...rest,
      ...overrideProps(override, style),
    },
    content,
  );
}

/**
 * A link often contains an icon plus a label.  Mark only the label editable so
 * replacing its text can never remove the icon or break the destination.
 */
export function EditableLink({
  editId,
  children,
  ...props
}: ComponentPropsWithoutRef<'a'> & { editId: string; children: ReactNode }) {
  return (
    <a {...props}>
      <EditableText editId={editId}>{children}</EditableText>
    </a>
  );
}

/** Marks an image/video or other media element with a durable edit identity. */
export function editableMediaProps(editId: string): { 'data-edit-id': string } {
  return { 'data-edit-id': editId };
}
