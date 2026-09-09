"""Exact intersection test for two path globs.

This is the safety mechanism behind `tasks[].owns`: the orchestrator must refuse to run
two tasks concurrently when *any* path could be written by both. Expanding globs against
the files currently on disk is not enough — most dev tasks create files that do not exist
yet, and those are exactly the ones that collide.

So the test is structural. Each glob is compiled to a small NFA over characters and the
two automata are walked as a product; the globs intersect iff some accepting state pair
is reachable. That answers "could any path match both patterns" without enumerating
anything.

Supported syntax (the subset `tasks-schema.md` allows):

    ?       one character, not `/`
    *       zero or more characters, not `/`
    **      zero or more characters, including `/`
    **/     zero or more whole path segments
    literal anything else, matched exactly
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

# Character classes a transition can carry. Kept as a tiny tagged union rather than real
# sets because the alphabet is "every character", and all we ever ask is whether two
# classes overlap.
ANY = "any"  # any character, including "/"
ANY_NO_SLASH = "any_no_slash"  # any character except "/"
LITERAL = "literal"  # one specific character


@dataclass(frozen=True)
class _Class:
    kind: str
    char: str = ""

    def intersects(self, other: "_Class") -> bool:
        if self.kind == LITERAL and other.kind == LITERAL:
            return self.char == other.char
        if self.kind == LITERAL:
            return other.kind == ANY or self.char != "/"
        if other.kind == LITERAL:
            return self.kind == ANY or other.char != "/"
        # Both are wildcards; ANY_NO_SLASH is non-empty, so any pairing overlaps.
        return True


@dataclass
class _NFA:
    start: int
    accept: int
    # state -> list of (class, next state)
    moves: dict[int, list[tuple[_Class, int]]] = field(default_factory=dict)
    # state -> list of next states reachable without consuming input
    epsilons: dict[int, list[int]] = field(default_factory=dict)

    def closure(self, states: frozenset[int]) -> frozenset[int]:
        """Every state reachable from `states` without consuming a character."""
        seen = set(states)
        stack = list(states)
        while stack:
            state = stack.pop()
            for nxt in self.epsilons.get(state, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return frozenset(seen)


def _tokenize(pattern: str) -> list[tuple[str, str]]:
    """Split a glob into ('gstar_dir'|'gstar'|'star'|'qmark'|'lit', payload) tokens."""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**", i):
                # `**/` spans whole segments (and may span none, so `a/**/b` matches
                # `a/b`). A bare `**` just spans characters including `/`.
                if pattern.startswith("**/", i):
                    tokens.append(("gstar_dir", ""))
                    i += 3
                else:
                    tokens.append(("gstar", ""))
                    i += 2
            else:
                tokens.append(("star", ""))
                i += 1
        elif char == "?":
            tokens.append(("qmark", ""))
            i += 1
        else:
            tokens.append(("lit", char))
            i += 1
    return tokens


def _compile(pattern: str) -> _NFA:
    ids = count()
    start = next(ids)
    nfa = _NFA(start=start, accept=start)
    current = start

    def add_move(src: int, cls: _Class, dst: int) -> None:
        nfa.moves.setdefault(src, []).append((cls, dst))

    def add_epsilon(src: int, dst: int) -> None:
        nfa.epsilons.setdefault(src, []).append(dst)

    for kind, payload in _tokenize(pattern):
        if kind == "lit":
            nxt = next(ids)
            add_move(current, _Class(LITERAL, payload), nxt)
            current = nxt
        elif kind == "qmark":
            nxt = next(ids)
            add_move(current, _Class(ANY_NO_SLASH), nxt)
            current = nxt
        elif kind == "star":
            nxt = next(ids)
            add_epsilon(current, nxt)
            add_move(current, _Class(ANY_NO_SLASH), current)
            current = nxt
        elif kind == "gstar":
            nxt = next(ids)
            add_epsilon(current, nxt)
            add_move(current, _Class(ANY), current)
            current = nxt
        elif kind == "gstar_dir":
            # Optional "(anything ending in /)": skip it entirely, or consume characters
            # and leave only across a slash, which is what makes it segment-aligned.
            middle = next(ids)
            nxt = next(ids)
            add_epsilon(current, nxt)
            add_move(current, _Class(ANY), middle)
            add_move(middle, _Class(ANY), middle)
            add_move(middle, _Class(LITERAL, "/"), nxt)
            add_move(current, _Class(LITERAL, "/"), nxt)
            current = nxt

    nfa.accept = current
    return nfa


def globs_intersect(left: str, right: str) -> bool:
    """True if some path string is matched by both globs.

    Conservative only in the sense that it ignores the filesystem: it answers whether the
    patterns *could* collide, which is the question the orchestrator needs before it lets
    two agents write concurrently.
    """
    left_nfa = _compile(_normalize(left))
    right_nfa = _compile(_normalize(right))

    start = (
        left_nfa.closure(frozenset({left_nfa.start})),
        right_nfa.closure(frozenset({right_nfa.start})),
    )
    seen = {start}
    queue = [start]

    while queue:
        left_states, right_states = queue.pop()
        if left_nfa.accept in left_states and right_nfa.accept in right_states:
            return True

        # Step both automata together over every pair of transitions whose character
        # classes overlap — that pairing is exactly "a character both could consume".
        for left_cls, left_dst in _transitions(left_nfa, left_states):
            for right_cls, right_dst in _transitions(right_nfa, right_states):
                if not left_cls.intersects(right_cls):
                    continue
                nxt = (
                    left_nfa.closure(frozenset({left_dst})),
                    right_nfa.closure(frozenset({right_dst})),
                )
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

    return False


def _transitions(nfa: _NFA, states: frozenset[int]) -> list[tuple[_Class, int]]:
    out: list[tuple[_Class, int]] = []
    for state in states:
        out.extend(nfa.moves.get(state, ()))
    return out


def _normalize(pattern: str) -> str:
    """Strip the cosmetic variations that would otherwise read as different patterns."""
    pattern = pattern.strip()
    if pattern.startswith("./"):
        pattern = pattern[2:]
    pattern = pattern.lstrip("/")
    # A directory-shaped glob owns everything under it: `src/api/` == `src/api/**`.
    if pattern.endswith("/"):
        pattern += "**"
    return pattern


def overlapping_pairs(left: list[str], right: list[str]) -> list[tuple[str, str]]:
    """Every (left glob, right glob) pair that could match a common path."""
    return [
        (one, other)
        for one in left
        for other in right
        if globs_intersect(one, other)
    ]
