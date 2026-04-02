# Quotes Search Engine

A command-line search engine that crawls [quotes.toscrape.com](https://quotes.toscrape.com/),
builds an inverted index, and answers user queries from an interactive shell.

Coursework submission for **COMP3011 Web Services and Web Data**, University of Leeds,
2025/26.

## Status

Work in progress. See the commit history for incremental development steps.

## Quick start

```bash
pip install -r requirements.txt
python -m src.main
```

## Testing

```bash
pytest --cov=src tests/
```

More documentation will be added as the project develops.
