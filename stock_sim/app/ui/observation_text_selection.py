"""Keep a read-only QML text selection attached to surviving observed content."""

from difflib import SequenceMatcher


def remap_observation_selection(
    previous: str, current: str, anchor: int, position: int,
) -> list[int]:
    """Map Qt UTF-16 offsets, retaining selection direction and the end anchor.

    Changed/deleted content clamps to its replacement. Unchanged content follows
    its matching span even when multiple preceding observations change length.
    This only positions a reader; it never delays or filters incoming facts.
    """
    def units(text: str) -> list[bytes]:
        encoded = text.encode("utf-16-le", errors="surrogatepass")
        return [encoded[index:index + 2] for index in range(0, len(encoded), 2)]

    old, new = units(previous), units(current)
    if not old:
        return [0, 0]
    changes = SequenceMatcher(None, old, new, autojunk=False).get_opcodes()

    def mapped(offset: int) -> int:
        offset = max(0, min(offset, len(old)))
        if old and offset == len(old):
            return len(new)
        for kind, old_start, old_end, new_start, new_end in changes:
            if offset < old_end:
                distance = offset - old_start
                return new_start + (distance if kind == "equal" else min(distance, new_end - new_start))
        return len(new)

    return [mapped(anchor), mapped(position)]
