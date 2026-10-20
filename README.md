# Personal webpage

Visit [shadabs.com](https://shadabs.com/).

To locally test webpage deployment, run `bundle exec jekyll serve`

## Updating the bookshelf

Run `python3 generate_books.py` to sync the bookshelf from Goodreads — it overwrites `_data/bookshelf.yml`, which `books.html` reads at build time. To update manually instead, edit `_data/bookshelf.yml` directly.
