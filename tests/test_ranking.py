"""Unit tests for :mod:`src.ranking`.

The fixtures construct a tiny three-document index by hand so each test can
reason about the expected score numerically rather than rely on the live
crawl. Every public function in :mod:`src.ranking` is exercised, including
edge cases the evaluation harness depends on (empty query, zero document
length, one-document corpus, query terms missing from the index).
"""

from __future__ import annotations

import math

import pytest

from src.ranking import (
    average_document_length,
    bm25_score,
    document_lengths,
    tfidf_score,
    total_documents,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def tiny_index():
    """Three documents, two query terms, hand-rolled posting lists.

    Document layout:

    * ``a`` — ``love love truth``       (3 tokens; 'love' x 2, 'truth' x 1)
    * ``b`` — ``love life``             (2 tokens; 'love' x 1, 'life' x 1)
    * ``c`` — ``life truth wisdom``     (3 tokens; 'life' x 1, 'truth' x 1, 'wisdom' x 1)
    """
    return {
        "love": {
            "a": {"frequency": 2, "positions": [0, 1]},
            "b": {"frequency": 1, "positions": [0]},
        },
        "truth": {
            "a": {"frequency": 1, "positions": [2]},
            "c": {"frequency": 1, "positions": [1]},
        },
        "life": {
            "b": {"frequency": 1, "positions": [1]},
            "c": {"frequency": 1, "positions": [0]},
        },
        "wisdom": {
            "c": {"frequency": 1, "positions": [2]},
        },
    }


# --------------------------------------------------------------------------- #
# Corpus helpers                                                              #
# --------------------------------------------------------------------------- #


def test_total_documents_counts_unique_urls(tiny_index):
    assert total_documents(tiny_index) == 3


def test_total_documents_handles_empty_index():
    assert total_documents({}) == 0


def test_document_lengths_sum_frequencies(tiny_index):
    assert document_lengths(tiny_index) == {"a": 3, "b": 2, "c": 3}


def test_average_document_length(tiny_index):
    assert average_document_length(tiny_index) == pytest.approx((3 + 2 + 3) / 3)


def test_average_document_length_empty():
    assert average_document_length({}) == 0.0


# --------------------------------------------------------------------------- #
# tfidf_score                                                                 #
# --------------------------------------------------------------------------- #


def test_tfidf_score_single_term(tiny_index):
    n = total_documents(tiny_index)
    score = tfidf_score(tiny_index, ["love"], "a", n, doc_length=3)
    # tf = 2/3, df=2, idf = ln(3/2) -> tf*idf
    expected = (2 / 3) * math.log(3 / 2)
    assert score == pytest.approx(expected)


def test_tfidf_score_multi_term_sums(tiny_index):
    n = total_documents(tiny_index)
    score = tfidf_score(tiny_index, ["love", "truth"], "a", n, doc_length=3)
    expected_love = (2 / 3) * math.log(3 / 2)
    expected_truth = (1 / 3) * math.log(3 / 2)
    assert score == pytest.approx(expected_love + expected_truth)


def test_tfidf_score_returns_zero_for_empty_query(tiny_index):
    score = tfidf_score(tiny_index, [], "a", total_documents(tiny_index), 3)
    assert score == 0.0


def test_tfidf_score_returns_zero_for_zero_doc_length(tiny_index):
    score = tfidf_score(tiny_index, ["love"], "a", 3, doc_length=0)
    assert score == 0.0


def test_tfidf_score_skips_terms_not_in_index(tiny_index):
    score = tfidf_score(tiny_index, ["love", "missing"], "a", 3, doc_length=3)
    expected = (2 / 3) * math.log(3 / 2)
    assert score == pytest.approx(expected)


def test_tfidf_score_returns_zero_for_unknown_url(tiny_index):
    # url 'z' isn't in any posting -> no contribution
    score = tfidf_score(tiny_index, ["love"], "z", 3, doc_length=3)
    assert score == 0.0


def test_tfidf_score_returns_zero_when_corpus_size_zero(tiny_index):
    score = tfidf_score(tiny_index, ["love"], "a", total_docs=0, doc_length=3)
    assert score == 0.0


# --------------------------------------------------------------------------- #
# bm25_score                                                                  #
# --------------------------------------------------------------------------- #


def test_bm25_score_single_term(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    score = bm25_score(
        tiny_index, ["love"], "a", n, doc_length=3, avg_doc_length=avg_len
    )
    df = 2
    idf = math.log(((n - df + 0.5) / (df + 0.5)) + 1.0)
    k1, b = 1.5, 0.75
    length_norm = 1.0 - b + b * (3 / avg_len)
    numerator = 2 * (k1 + 1.0)
    denominator = 2 + k1 * length_norm
    expected = idf * (numerator / denominator)
    assert score == pytest.approx(expected)


def test_bm25_score_returns_zero_for_empty_query(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    assert bm25_score(tiny_index, [], "a", n, 3, avg_len) == 0.0


def test_bm25_score_returns_zero_for_zero_doc_length(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    assert bm25_score(tiny_index, ["love"], "a", n, 0, avg_len) == 0.0


def test_bm25_score_returns_zero_for_zero_avg_doc_length(tiny_index):
    n = total_documents(tiny_index)
    assert bm25_score(tiny_index, ["love"], "a", n, 3, 0.0) == 0.0


def test_bm25_score_skips_missing_terms(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    only_love = bm25_score(tiny_index, ["love"], "a", n, 3, avg_len)
    plus_missing = bm25_score(tiny_index, ["love", "ghost"], "a", n, 3, avg_len)
    assert only_love == pytest.approx(plus_missing)


def test_bm25_score_handles_url_not_in_posting(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    # 'wisdom' is only in 'c' - asking about 'a' should yield 0
    assert bm25_score(tiny_index, ["wisdom"], "a", n, 3, avg_len) == 0.0


def test_bm25_score_parameter_sensitivity(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    base = bm25_score(tiny_index, ["love"], "a", n, 3, avg_len)
    # b=0 disables length normalisation; for a doc longer than average this
    # should raise the score (numerator unchanged, denominator smaller).
    no_norm = bm25_score(
        tiny_index, ["love"], "a", n, 3, avg_len, k1=1.5, b=0.0
    )
    assert no_norm >= base


def test_bm25_score_higher_freq_gives_higher_score(tiny_index):
    """Document 'a' (love x2) should score higher than 'b' (love x1)."""
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    score_a = bm25_score(tiny_index, ["love"], "a", n, 3, avg_len)
    score_b = bm25_score(tiny_index, ["love"], "b", n, 2, avg_len)
    assert score_a > score_b


def test_tfidf_and_bm25_agree_on_zero_score_when_no_term_present(tiny_index):
    n = total_documents(tiny_index)
    avg_len = average_document_length(tiny_index)
    # 'a' contains 'love' and 'truth', neither 'life' nor 'wisdom'
    assert tfidf_score(tiny_index, ["life", "wisdom"], "a", n, 3) == 0.0
    assert bm25_score(tiny_index, ["life", "wisdom"], "a", n, 3, avg_len) == 0.0
