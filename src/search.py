"""Query processing against the inverted index.

Two public entry points:

* :func:`print_word` — pretty-prints the posting for a single term, used by
  the CLI's ``print`` command.
* :func:`find` — answers a query and returns the matching URLs ranked by
  **TF-IDF**.

Query syntax
------------

* Bare words are AND'd together: ``good night`` matches pages containing
  both terms.
* ``"good night"`` (double-quoted) is a **phrase**: matches only pages
  where the words appear at consecutive token positions, verified using
  the position lists stored in the index.
* Uppercase ``AND`` is the redundant default separator.
* Uppercase ``OR`` splits the query into independent groups whose
  results are unioned.
* Uppercase ``NOT word`` (or ``NOT "phrase"``) excludes any document
  containing the named term(s).
* Lowercase ``and`` / ``or`` / ``not`` are treated as ordinary search
  terms so prose like ``cats and dogs`` still searches for those words.

TF-IDF formula
--------------

For document ``d`` and query term ``t``:

* ``tf(t, d) = freq(t, d) / total_tokens(d)`` — relative frequency. The
  document's total token count is approximated as the sum of all term
  frequencies in that document, which is exact for a single-document
  vocabulary and a tight upper bound otherwise.
* ``idf(t)   = log(N / df(t))`` — natural log, with ``N`` = number of
  documents in the corpus and ``df(t)`` = number of documents containing
  ``t``. We use the un-smoothed form because every query term is, by
  construction, present in at least one document (otherwise the AND-set is
  empty and we never reach the ranking step).
* For multi-term queries the per-term TF-IDF scores are summed.

Ties (same score) are broken by URL alphabetical order so results are
deterministic — important for testability.
"""

from __future__ import annotations

import difflib
import logging
import math
import re
from dataclasses import dataclass, field
from typing import List, Set, Tuple

from src.indexer import InvertedIndex, tokenize

logger = logging.getLogger(__name__)


def suggest_terms(
    index: InvertedIndex,
    term: str,
    n: int = 3,
    cutoff: float = 0.7,
) -> List[str]:
    """Return up to ``n`` indexed terms close to ``term`` by edit distance.

    Uses :func:`difflib.get_close_matches`, which ranks candidates by a
    Ratcliff/Obershelp similarity score. The default cutoff of 0.7 trades
    some recall for precision so a typo like ``lvoe`` reliably suggests
    ``love`` without flooding totally unrelated near-matches.
    """
    if not term or not index:
        return []
    return difflib.get_close_matches(term, list(index.keys()), n=n, cutoff=cutoff)


def print_word(index: InvertedIndex, word: str) -> None:
    """Print the inverted-index entry for ``word`` to stdout.

    The output lists each URL containing the word, its frequency on that
    page, and the positions where it occurs. If the word does not appear
    in the index a friendly message is printed; if any near-spelling
    matches exist a "Did you mean" hint is appended so a single typo
    doesn't end the user's session.

    Args:
        index: The inverted index to query.
        word: Term to print. Case is normalised before lookup.
    """
    key = word.strip().lower()
    if not key:
        print("Empty word.")
        return

    posting = index.get(key)
    if not posting:
        suggestions = suggest_terms(index, key)
        if suggestions:
            print(
                f"'{key}' is not in the index. "
                f"Did you mean: {', '.join(suggestions)}?"
            )
        else:
            print(f"'{key}' is not in the index.")
        return

    print(f"'{key}' appears in {len(posting)} document(s):")
    for url in sorted(posting.keys()):
        entry = posting[url]
        freq = entry.get("frequency", 0)
        positions = entry.get("positions", [])
        print(f"  {url}")
        print(f"    frequency: {freq}")
        print(f"    positions: {positions}")


_QUOTED_PHRASE = re.compile(r'"([^"]*)"')
_OPERATOR_TOKEN = re.compile(r"\b(AND|OR|NOT)\b")
_PHRASE_PLACEHOLDER = "__PHRASE_{}__"


@dataclass
class QueryGroup:
    """One OR-arm of a parsed query.

    Within a single group, ``positives`` and ``phrases`` are AND'd, and
    any document containing a ``negatives`` term is excluded. Multiple
    groups produced by an ``OR`` are unioned at the top level.
    """

    positives: List[str] = field(default_factory=list)
    phrases: List[List[str]] = field(default_factory=list)
    negatives: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return ``True`` if the group carries no constraints at all.

        An empty group is produced when the user types an isolated
        operator (``OR``, trailing ``AND``) or when every token in a
        group fails tokenisation. The parser uses this as the signal
        to discard the group instead of appending a no-op shell.

        Returns:
            ``True`` if no positives, phrases or negatives were
            captured; ``False`` otherwise.
        """
        return not (self.positives or self.phrases or self.negatives)

    def has_positive_anchor(self) -> bool:
        """A group needs at least one positive constraint to score URLs against."""
        return bool(self.positives or self.phrases)


def parse_query(raw: str, *, stem: bool = False) -> List[QueryGroup]:
    """Parse ``raw`` into a list of OR-groups.

    Single-group queries (the common case) yield a one-element list, so
    callers that don't care about boolean structure can just look at
    ``parse_query(q)[0]``.

    Args:
        raw: User query string.
        stem: When ``True``, apply :class:`nltk.stem.PorterStemmer` to
            every token (positives, phrase tokens and negatives) so the
            query matches indexes built with stemming enabled.
    """
    extracted_phrases: List[List[str]] = []

    def _capture(match: "re.Match[str]") -> str:
        """Replace one ``"..."`` phrase with a placeholder sentinel.

        Side effect: appends the tokenised phrase to the enclosing
        ``extracted_phrases`` list so :func:`_resolve_phrase_placeholder`
        can recover the tokens later. Phrases that tokenise to nothing
        (e.g. ``""``) are silently dropped.

        Args:
            match: The ``re.Match`` object for one ``"..."`` segment.

        Returns:
            A whitespace-padded placeholder string the second-pass
            tokeniser will recognise, or a single space when the
            phrase was empty.
        """
        toks = tokenize(match.group(1), stem=stem)
        if not toks:
            return " "
        extracted_phrases.append(toks)
        return f" {_PHRASE_PLACEHOLDER.format(len(extracted_phrases) - 1)} "

    remaining = _QUOTED_PHRASE.sub(_capture, raw)
    parts = remaining.split()

    groups: List[QueryGroup] = []
    current = QueryGroup()
    expect_negation = False

    for word in parts:
        if word == "OR":
            if not current.is_empty():
                groups.append(current)
            current = QueryGroup()
            expect_negation = False
            continue
        if word == "AND":
            # Default semantics — no-op, just advance.
            expect_negation = False
            continue
        if word == "NOT":
            expect_negation = True
            continue

        phrase_tokens = _resolve_phrase_placeholder(word, extracted_phrases)
        if phrase_tokens is not None:
            if expect_negation:
                # NOT applied to a phrase: exclude any document containing
                # any of the phrase's tokens. (A more precise "not adjacent"
                # would need negative phrase verification — skipped for
                # simplicity.)
                current.negatives.extend(phrase_tokens)
            else:
                current.phrases.append(phrase_tokens)
            expect_negation = False
            continue

        toks = tokenize(word, stem=stem)
        if not toks:
            expect_negation = False
            continue
        if expect_negation:
            current.negatives.extend(toks)
        else:
            current.positives.extend(toks)
        expect_negation = False

    if not current.is_empty():
        groups.append(current)
    return groups


def _resolve_phrase_placeholder(
    word: str, phrases: List[List[str]]
) -> "List[str] | None":
    """If ``word`` is a phrase sentinel, return the phrase tokens, else ``None``."""
    if not (word.startswith("__PHRASE_") and word.endswith("__")):
        return None
    try:
        idx = int(word[len("__PHRASE_"):-2])
    except ValueError:
        return None
    if 0 <= idx < len(phrases):
        return phrases[idx]
    return None


def reconstruct_tokens(index: InvertedIndex, url: str) -> List[str]:
    """Rebuild the original token stream of ``url`` from its position lists.

    Every token added to the index recorded its 0-indexed position inside
    the document (see :class:`src.indexer.Indexer`), so the document can
    be reconstructed by collecting ``(position, term)`` pairs from every
    posting that mentions ``url`` and sorting by position. This is
    O(V + |D|) per call where V is the vocabulary size; the cost is paid
    only when a snippet is requested, not on every query.

    Args:
        index: The inverted index to consult.
        url: The document whose tokens should be reconstructed.

    Returns:
        Tokens of the document in original order. Empty list if the URL
        is not present in any posting.
    """
    by_position: List[Tuple[int, str]] = []
    for term, posting in index.items():
        entry = posting.get(url)
        if entry is None:
            continue
        for pos in entry.get("positions", []):
            by_position.append((int(pos), term))
    by_position.sort()
    return [tok for _, tok in by_position]


_ANSI_BOLD = "\x1b[1m"
_ANSI_RESET = "\x1b[22m"


def extract_snippet(
    index: InvertedIndex,
    url: str,
    query_terms: List[str],
    *,
    window: int = 8,
    ansi: bool = False,
) -> str:
    """Return a `±window`-token snippet around the first query-term hit.

    The snippet is built from the document reconstruction returned by
    :func:`reconstruct_tokens`. The first occurrence of any query term
    anchors the window; matched terms inside the window are wrapped in
    bold markers — ANSI escape codes when ``ansi=True``, ``**...**``
    markdown otherwise — so the same helper drives both terminal output
    and copy/paste-friendly markdown.

    Args:
        index: The inverted index providing positions.
        url: Document to snippet.
        query_terms: Already-tokenised query terms (lowercased,
            punctuation-stripped). Empty input returns an empty string.
        window: Number of tokens to include on either side of the first
            match. Defaults to 8 per the project specification.
        ansi: When ``True``, wrap matched terms with ANSI bold codes;
            otherwise wrap them in ``**...**`` markdown markers.

    Returns:
        The snippet string, or ``""`` if the URL has no tokens or no
        query term appears in it.
    """
    if not query_terms:
        return ""
    tokens = reconstruct_tokens(index, url)
    if not tokens:
        return ""

    query_set = {t for t in query_terms if t}
    if not query_set:
        return ""

    first_match: int | None = next(
        (i for i, tok in enumerate(tokens) if tok in query_set), None
    )
    if first_match is None:
        return ""

    start = max(0, first_match - window)
    end = min(len(tokens), first_match + window + 1)
    if ansi:
        left, right = _ANSI_BOLD, _ANSI_RESET
    else:
        left, right = "**", "**"

    rendered: List[str] = []
    for tok in tokens[start:end]:
        if tok in query_set:
            rendered.append(f"{left}{tok}{right}")
        else:
            rendered.append(tok)

    snippet = " ".join(rendered)
    if start > 0:
        snippet = "... " + snippet
    if end < len(tokens):
        snippet = snippet + " ..."
    return snippet


def has_phrase(raw_query: str) -> bool:
    """Return ``True`` if ``raw_query`` contains a ``"..."`` segment."""
    return bool(_QUOTED_PHRASE.search(raw_query))


def query_positive_terms(raw_query: str, *, stem: bool = False) -> List[str]:
    """Flatten ``raw_query`` into the positive terms used for snippet matching.

    Positive terms are the union of every OR-group's ``positives`` and
    ``phrases`` token lists. Negatives are skipped — they exclude
    documents but never appear in a result, so highlighting them would
    be misleading.

    Args:
        raw_query: The user's raw query string.
        stem: When ``True``, apply the Porter stemmer so the returned
            terms match the stemmed tokens stored in the index.

    Returns:
        Lowercased, punctuation-free terms in the order the parser saw
        them. Duplicates are preserved so the caller can decide whether
        to dedupe.
    """
    out: List[str] = []
    for group in parse_query(raw_query, stem=stem):
        out.extend(group.positives)
        for phrase in group.phrases:
            out.extend(phrase)
    return out


def has_operators(raw_query: str) -> bool:
    """Return ``True`` if ``raw_query`` contains an uppercase boolean operator."""
    return bool(_OPERATOR_TOKEN.search(raw_query))


def find(index: InvertedIndex, query: str, *, stem: bool = False) -> List[str]:
    """Return URLs matching ``query``, ranked by descending TF-IDF.

    Supports phrase queries (``"..."``), boolean operators (uppercase
    ``AND``/``OR``/``NOT``), and bare-word AND-semantics by default.
    Ties on score break by URL alphabetical order for deterministic
    ordering.

    Args:
        index: The inverted index to query.
        query: Free-text query string.
        stem: When ``True``, apply the Porter stemmer to every query
            token before lookup. Pass the same flag the index was built
            with — see :func:`src.storage.load_index_metadata`.

    Returns:
        Ordered list of URLs (most relevant first). Empty list if no
        document satisfies the query.
    """
    groups = parse_query(query, stem=stem)
    if not groups:
        return []

    union_urls: Set[str] = set()
    scoring_terms: List[str] = []

    for group in groups:
        if not group.has_positive_anchor():
            # A group of pure NOTs has nothing to score against; skip it
            # rather than scanning the entire corpus.
            continue
        urls, group_terms = _resolve_group(index, group)
        if not urls:
            continue
        union_urls |= urls
        scoring_terms.extend(group_terms)

    if not union_urls:
        return []

    total_docs = _count_total_documents(index)
    scored = [
        (url, _score(index, scoring_terms, url, total_docs))
        for url in union_urls
    ]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return [url for url, _ in scored]


def find_with_suggestions(
    index: InvertedIndex, query: str, *, stem: bool = False
) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Run :func:`find` and additionally suggest replacements for missing terms.

    Returns ``(results, suggestions)`` where ``suggestions`` is a list of
    ``(missing_term, [candidate, ...])`` pairs — empty when the query
    succeeded or when no near-matches were found. The CLI uses this to
    print a "Did you mean: ..." hint after a no-results query.

    Args:
        index: The inverted index to query.
        query: Free-text query string.
        stem: When ``True``, apply the Porter stemmer to every query
            token before lookup so the search matches a stemmed index.
    """
    results = find(index, query, stem=stem)
    if results:
        return results, []
    suggestions: List[Tuple[str, List[str]]] = []
    seen: Set[str] = set()
    for group in parse_query(query, stem=stem):
        candidate_terms: List[str] = list(group.positives)
        for phrase in group.phrases:
            candidate_terms.extend(phrase)
        for term in candidate_terms:
            if term in seen or term in index:
                continue
            seen.add(term)
            hints = suggest_terms(index, term)
            if hints:
                suggestions.append((term, hints))
    return results, suggestions


def _resolve_group(
    index: InvertedIndex, group: QueryGroup
) -> "tuple[Set[str], List[str]]":
    """Return ``(matching_urls, scoring_terms)`` for one OR-group."""
    must_have = list(group.positives)
    for phrase in group.phrases:
        must_have.extend(phrase)

    urls = _intersect_postings(index, must_have)
    if not urls:
        return set(), must_have

    for phrase in group.phrases:
        urls = {u for u in urls if _has_phrase_at(index, u, phrase)}
        if not urls:
            return set(), must_have

    if group.negatives:
        excluded: Set[str] = set()
        for neg in group.negatives:
            excluded |= set(index.get(neg, {}).keys())
        urls -= excluded

    return urls, must_have


def _has_phrase_at(
    index: InvertedIndex, url: str, phrase_tokens: List[str]
) -> bool:
    """Return ``True`` iff ``phrase_tokens`` appear at consecutive positions in ``url``.

    Implementation: collect each token's position set in ``url``;
    a phrase match exists iff some position ``p`` is in token-0's set,
    ``p+1`` in token-1's set, and so on through the end of the phrase.
    Single-token phrases trivially match iff the word appears at all.
    """
    if not phrase_tokens:
        return True
    position_sets: List[Set[int]] = []
    for tok in phrase_tokens:
        entry = index.get(tok, {}).get(url)
        if entry is None:
            return False
        positions = entry.get("positions", [])
        if not isinstance(positions, list):
            return False
        position_sets.append({int(p) for p in positions})
    if len(phrase_tokens) == 1:
        return bool(position_sets[0])
    for start in position_sets[0]:
        if all((start + offset) in position_sets[offset]
               for offset in range(1, len(phrase_tokens))):
            return True
    return False


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _intersect_postings(
    index: InvertedIndex, terms: List[str]
) -> Set[str]:
    """Return the set of URLs that contain every term in ``terms``."""
    url_sets = []
    for term in terms:
        posting = index.get(term)
        if not posting:
            return set()
        url_sets.append(set(posting.keys()))
    # Intersect smallest-first for a tiny perf win on skewed indexes.
    url_sets.sort(key=len)
    result = url_sets[0]
    for other in url_sets[1:]:
        result &= other
        if not result:
            break
    return result


def _count_total_documents(index: InvertedIndex) -> int:
    """Return the number of distinct documents represented in ``index``."""
    seen: Set[str] = set()
    for posting in index.values():
        seen.update(posting.keys())
    return len(seen)


def _document_length(index: InvertedIndex, url: str) -> int:
    """Approximate ``url``'s token count by summing all term frequencies.

    This is exact: every token in the document was added to exactly one
    posting list, contributing 1 to that posting's ``frequency`` for ``url``.
    """
    total = 0
    for posting in index.values():
        entry = posting.get(url)
        if entry is not None:
            total += int(entry.get("frequency", 0))
    return total


def _score(
    index: InvertedIndex, terms: List[str], url: str, total_docs: int
) -> float:
    """Compute the summed TF-IDF score for ``url`` against ``terms``."""
    doc_len = _document_length(index, url)
    if doc_len == 0:
        return 0.0

    score = 0.0
    for term in terms:
        posting = index.get(term, {})
        entry = posting.get(url)
        if entry is None:
            continue
        freq = int(entry.get("frequency", 0))
        df = len(posting)
        if df == 0:
            continue
        tf = freq / doc_len
        idf = math.log(total_docs / df) if total_docs > 0 else 0.0
        score += tf * idf
    return score
