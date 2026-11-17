"""The "debugealo" theme: today's near-black palette, expressed as Textual theme variables.

Every color in the app comes from the active theme, so Ctrl+P → Theme recolors it all.
Only a few marks stay fixed on purpose (breakpoint glyphs, the yellow paused line, and the
colors a program writes to its terminal): changing them with the theme would confuse.
"""

from textual.theme import Theme

DEFAULT_THEME = "debugealo"

DEBUGEALO_THEME = Theme(
    name=DEFAULT_THEME,
    # Textual's own accents (inputs, scrollbars, toasts) as in textual-dark.
    primary="#0178D4",
    secondary="#004578",
    accent="#ffa62b",
    # The yellow of a focused terminal's border.
    warning="#facc15",
    error="#ba3c5b",
    success="#4EBF71",
    foreground="#d6d9dc",
    background="#080b0e",
    surface="#101518",
    panel="#171c20",
    dark=True,
    variables={
        # Section titles, column headers and labels.
        "text-secondary": "#a9c2cc",
        "text-muted": "#9ba5aa",
        "text-disabled": "#697279",
        "text-success": "#7fc8a9",
        "text-warning": "#e5c07b",
        # Thin separators between panes.
        "border-blurred": "#2b3439",
        # The selected row or the focused control.
        "block-cursor-background": "#30414c",
        "block-cursor-foreground": "#ffffff",
        "block-hover-background": "#242c32",
        # Container state borders and the inline confirmation bar.
        "success-muted": "#3f7d4f",
        "error-muted": "#8a4b4b",
        "warning-muted": "#292316",
        "footer-background": "#101518",
        "footer-key-background": "#101518",
        "footer-description-background": "#101518",
        "footer-item-background": "#101518",
        "footer-foreground": "#9ba5aa",
        "footer-key-foreground": "#a9c2cc",
        "footer-description-foreground": "#9ba5aa",
    },
)
