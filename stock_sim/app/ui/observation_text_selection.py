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
    if not previous or not current:
        return [0, 0]

    def boundaries(lines: list[str]) -> list[int]:
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line.encode("utf-16-le", errors="surrogatepass")) // 2)
        return offsets

    def units(text: str) -> list[bytes]:
        encoded = text.encode("utf-16-le", errors="surrogatepass")
        return [encoded[index:index + 2] for index in range(0, len(encoded), 2)]

    old, new = previous.splitlines(keepends=True), current.splitlines(keepends=True)
    old_offsets, new_offsets = boundaries(old), boundaries(new)
    # Most facts retain whole lines. Never compare every character in every
    # group on the UI thread; refine only a changed block containing an endpoint.
    changes = SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    refined = {}

    def mapped(offset: int) -> int:
        offset = max(0, min(offset, old_offsets[-1]))
        if offset == old_offsets[-1]:
            return new_offsets[-1]
        for change in changes:
            kind, old_first, old_last, new_first, new_last = change
            old_start, old_end = old_offsets[old_first], old_offsets[old_last]
            new_start, new_end = new_offsets[new_first], new_offsets[new_last]
            if offset < old_end:
                if kind == "equal":
                    return new_start + offset - old_start
                if kind == "delete":
                    return new_start
                if change not in refined:
                    refined[change] = SequenceMatcher(
                        None, units("".join(old[old_first:old_last])),
                        units("".join(new[new_first:new_last])), autojunk=False,
                    ).get_opcodes()
                for detail, left, right, start, end in refined[change]:
                    if offset - old_start < right:
                        distance = offset - old_start - left
                        return new_start + start + (distance if detail == "equal" else min(distance, end - start))
                return new_end
        return new_offsets[-1]

    return [mapped(anchor), mapped(position)]
