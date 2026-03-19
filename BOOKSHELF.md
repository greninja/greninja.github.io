# Bookshelf

Books are listed on **`books.html`**, but the actual entries live in **`_data/bookshelf.yml`**. Jekyll reads that file at **build time** and turns it into HTML — no in-browser fetch, no editing `<li>` tags.

## Add or change a book (usual workflow)

1. Open **`_data/bookshelf.yml`**.
2. Under `currently_reading:` or `read:`, add a block like:

   ```yaml
   - title: "Your title"
     author: "Author Name"
     url: "https://example.com/some-link"
   ```

3. Save, commit, push. GitHub Pages will rebuild and `shadabs.com` will update.

To preview locally: `bundle exec jekyll serve` and open `/books.html`.

## Optional: sync from Goodreads (one command)

If your Goodreads shelves are up to date and you want to **overwrite** `_data/bookshelf.yml` from the RSS feeds:

```bash
python3 generate_books.py
```

Requires `requests` (`pip install requests`). **This replaces the whole YAML file** with what Goodreads returns — any hand edits you only made in YAML (not on Goodreads) will be lost.

The script follows Goodreads RSS **`page=1,2,…`** until a page is empty, so there is **no “only take 20 books” cap** (aside from an extreme safety cap in code if something misbehaves).

**If a book you just added on Goodreads is missing:** the feed can lag (try again in 10–30 minutes). Confirm the book is on **Currently reading** or **Read** (not “Want to read”). Open the raw RSS in a browser and search for the title—if it’s not there, Goodreads hasn’t published it to RSS yet; add it manually to `_data/bookshelf.yml` if you need it on the site immediately.

## If you still see old “Loading books…” on the site

That was removed; a stale deploy or cache was the usual cause. Hard-refresh after push.
