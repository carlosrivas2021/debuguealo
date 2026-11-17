"""The "debugealo" theme: today's near-black palette, expressed as Textual theme variables.

Every color in the app comes from the active theme, so Ctrl+P → Theme recolors it all.
Only a few marks stay fixed on purpose (breakpoint glyphs, the yellow paused line, and the
colors a program writes to its terminal): changing them with the theme would confuse.
"""

from rich.style import Style
from textual.color import Color
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


_STYLES: dict[tuple, Style] = {}


def _rich_color(variables: dict[str, str], name: str):
    """A theme variable as an opaque Rich color, or None (the terminal default).

    Values may be "auto 60%" (the background's contrasting text at that strength) or carry
    transparency; both are blended over the theme's background, as Textual draws them.
    """
    try:
        value = variables[name]
        background = Color.parse(variables["background"])
        if value.startswith("auto"):
            _, _, strength = value.partition(" ")
            alpha = float(strength.rstrip("%")) / 100 if strength else 1.0
            color = background.get_contrast_text(alpha)
        else:
            color = Color.parse(value)
        if color.a < 1:
            color = background + color
        return color.rich_color
    except (KeyError, ValueError):
        return None


def theme_style(app, variable: str, *, bold: bool = False, italic: bool = False) -> Style:
    """A Rich style in the active theme's color for text drawn from Python.

    Widgets that keep such text must draw it again when the theme changes.
    """
    key = (app.theme, variable, bold, italic)
    style = _STYLES.get(key)
    if style is None:
        color = _rich_color(app.get_css_variables(), variable)
        style = Style(color=color, bold=bold or None, italic=italic or None)
        if len(_STYLES) > 512:
            _STYLES.clear()
        _STYLES[key] = style
    return style
