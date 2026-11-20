"""Loose text matching shared by the pickers that filter as you type."""


def letters_in_order(query: str, text: str) -> bool:
    """Whether every letter of the query appears in the text, in order."""
    position = 0
    for letter in query:
        position = text.find(letter, position) + 1
        if not position:
            return False
    return True
