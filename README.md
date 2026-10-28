# Personal webpage

Visit [shadabs.com](https://shadabs.com/).

To locally test webpage deployment, run `bundle exec jekyll serve`

## Updating the bookshelf

Run `python3 generate_books.py` to sync the bookshelf from Goodreads — it overwrites `_data/bookshelf.yml`, which `books.html` reads at build time. To update manually instead, edit `_data/bookshelf.yml` directly.

If Goodreads RSS returns 403 or 404, the script automatically tries Goodreads' public bookshelf widgets. It checks each shelf's book count against your public profile before saving. Widgets can limit the number of books returned; incomplete results leave your existing data untouched.

Run the script's tests with `python3 -m unittest discover -s tests`.
