# DebugPilot design system

Synchronized from the existing Textual stylesheet. This board records only values present in `src/debugpilot/tui/styles.tcss`; HTML-specific renderer choices are explicitly not project tokens.

## Colors (15 distinct values)

| Token / value | Usage in source | Source |
|---|---|---|
| `#080b0e` | Screen background | `src/debugpilot/tui/styles.tcss` |
| `#d6d9dc` | Screen foreground | `src/debugpilot/tui/styles.tcss` |
| `#171c20` | Button background | `src/debugpilot/tui/styles.tcss` |
| `#c8cdd1` | Button text | `src/debugpilot/tui/styles.tcss` |
| `#242c32` | Button hover background | `src/debugpilot/tui/styles.tcss` |
| `#30414c` | Button focus background | `src/debugpilot/tui/styles.tcss` |
| `#ffffff` | Focused button text | `src/debugpilot/tui/styles.tcss` |
| `#697279` | Disabled button text | `src/debugpilot/tui/styles.tcss` |
| `#101518` | Docker status background | `src/debugpilot/tui/styles.tcss` |
| `#9db5bf` | Docker status text | `src/debugpilot/tui/styles.tcss` |
| `#2b3439` | Section separators | `src/debugpilot/tui/styles.tcss` |
| `#a9c2cc` | Section / log labels | `src/debugpilot/tui/styles.tcss` |
| `#9ba5aa` | Secondary text | `src/debugpilot/tui/styles.tcss` |
| `#c5a66f` | Stopped section label | `src/debugpilot/tui/styles.tcss` |
| `#292316` | Inline Compose confirmation background | `src/debugpilot/tui/styles.tcss` |

## Typography

- Project stylesheet declares no font-family, font-size, or text-transform token. Source: `src/debugpilot/tui/styles.tcss`.
- HTML artboard renderer adaptation (not a sourced project token): system monospace stack (`ui-monospace`, `SFMono-Regular`, Consolas, `Liberation Mono`, monospace) and compact terminal-like line-height. The actual terminal renders through Textual/Rich and its configured terminal font.

## Spacing and terminal geometry

Only literal dimensions found in source are recorded here; `1` is a Textual terminal cell/row unit, not a CSS pixel token.

| Source dimensions | Usage | Source |
|---|---|---|
| `height: 1`, `min-height: 1` | Compact controls, status/title rows | `src/debugpilot/tui/styles.tcss` |
| `width: 34` | Sidebar | `src/debugpilot/tui/styles.tcss` |
| `height: 9` | Empty launch section | `src/debugpilot/tui/styles.tcss` |
| `min-height: 8` | Launch section | `src/debugpilot/tui/styles.tcss` |
| `min-height: 5` | Active container section | `src/debugpilot/tui/styles.tcss` |
| `height: 4` | Container info | `src/debugpilot/tui/styles.tcss` |
| `height: 3` | Inline Compose message | `src/debugpilot/tui/styles.tcss` |
| `height: 14` | Compact sidebar | `src/debugpilot/tui/styles.tcss` |
| `min-height: 6` | Compact launch section | `src/debugpilot/tui/styles.tcss` |
| `height: 4`, `min-height: 4` | Compact empty launch section | `src/debugpilot/tui/styles.tcss` |
| `height: 3` | Compact empty welcome | `src/debugpilot/tui/styles.tcss` |
| `min-width: 10`, `min-width: 14`, `width: 12`, `width: 20` | Buttons and launch-file action | `src/debugpilot/tui/styles.tcss` |
| `padding: 0 1` | Button and text inset | `src/debugpilot/tui/styles.tcss` |

The HTML boards use a 1440 × 900 CSS-pixel viewing canvas, CSS grid, and monospace character alignment as a renderer adaptation. Their responsive layouts demonstrate how the same hierarchy can collapse to terminal-width panes; they do not assert CSS pixels equal terminal cells.

## Radius, shadows, components

- Radius: no radius declaration found in `src/debugpilot/tui/styles.tcss`.
- Shadows: no shadow declaration found in `src/debugpilot/tui/styles.tcss`.
- Existing component rules: one-row buttons with no border; distinct hover/focus/disabled states; top status bar; launch-profile and active/stopped container sections; vertical sidebar beside a flexible log panel with a subtle left separator; inline three-row Compose confirmation; compact layout stacks the dashboard vertically. Source: `src/debugpilot/tui/styles.tcss`.
- Mockup adaptation: square corners, low-contrast separators, no gradients or shadows, compact text, visible keyboard focus, native collapsible sections, and explicit keyboard hints. Adaptation, not additional sourced tokens.

## Source inventory

Only `src/debugpilot/tui/styles.tcss` supplied a token source for this sync. The design tool's source detector reported no sources; this explicit stylesheet was provided by the task and was inspected directly.
