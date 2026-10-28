import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import generate_books as books


class BookshelfTests(unittest.TestCase):
    def widget_responses(self, expected_count=1, served_shelf="read"):
        profile = f'<a href="/review/list/85262689?shelf=read">read ({expected_count})</a>'
        html = (
            f'<h2><a href="/review/list/85262689?shelf={served_shelf}">Books</a></h2>'
            '<div class="gr_custom_title_test"><a href="https://www.goodreads.com/review/show/123?utm_source=widget">'
            'A &amp; B: Reader\'s book</a></div>'
            '<div class="gr_custom_author_test">by <a href="/author/1">Éva  Author</a></div>'
        )
        payload = json.dumps(html, ensure_ascii=False)[1:-1].replace("'", "\\'")
        return [Mock(text=profile), Mock(text=f"var widget_code = '{payload}'")]

    def test_widgets_parse_titles_authors_and_check_counts(self):
        with patch.object(books, "SHELVES", [("read", "read")]), patch.object(
            books.requests, "get", side_effect=self.widget_responses()
        ):
            self.assertEqual(books.fetch_widget_shelves(30), {"read": [{
                "title": "A & B: Reader's book", "author": "Éva Author",
                "link": "https://www.goodreads.com/review/show/123",
            }]})

    def test_widgets_reject_truncated_or_wrong_shelves(self):
        for responses in [self.widget_responses(expected_count=2), self.widget_responses(served_shelf="to-read")]:
            with patch.object(books, "SHELVES", [("read", "read")]), patch.object(
                books.requests, "get", side_effect=responses
            ), self.assertRaises(RuntimeError):
                books.fetch_widget_shelves(30)

    def test_rss_unavailable_automatically_uses_widgets(self):
        result = {shelf: [] for shelf, _ in books.SHELVES}
        with patch("sys.argv", ["generate_books.py"]), patch.object(
            books, "fetch_entire_shelf", side_effect=books.RssUnavailable("404")
        ), patch.object(books, "fetch_widget_shelves", return_value=result) as widget, patch.object(
            books, "write_bookshelf_yaml"
        ) as write, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(books.main(), 0)
            widget.assert_called_once_with(30)
            self.assertEqual(write.call_args.args[1], result)

    def test_http_failure_triggers_widget_fallback(self):
        for status in (403, 404):
            with patch.object(books.requests, "get", return_value=Mock(status_code=status)):
                with self.assertRaisesRegex(books.RssUnavailable, f"HTTP {status}"):
                    books.fetch_rss_xml("read", 1, 30)

    def test_failed_sync_never_writes(self):
        with patch("sys.argv", ["generate_books.py"]), patch.object(
            books, "fetch_entire_shelf", side_effect=[[], RuntimeError("RSS unavailable")]
        ), patch.object(books, "write_bookshelf_yaml") as write, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(books.main(), 1)
            write.assert_not_called()
            self.assertIn("Existing bookshelf was not changed", error.getvalue())

    def test_repeated_rss_page_is_rejected(self):
        xml = "<rss><channel><title>Reader's bookshelf: read</title><item><title>Book</title><link>https://example.com/1</link></item></channel></rss>"
        with patch.object(books, "fetch_rss_xml", return_value=xml) as fetch:
            with self.assertRaisesRegex(RuntimeError, "repeated a page"):
                books.fetch_entire_shelf("read", 30)
            self.assertEqual(fetch.call_count, 2)

    def test_rss_pagination_stops_at_empty_page(self):
        pages = [
            "<rss><channel><title>Reader's bookshelf: read</title><item><title>Book by Author</title><link>https://example.com/1</link></item></channel></rss>",
            "<rss><channel><title>Reader's bookshelf: read</title></channel></rss>",
        ]
        with patch.object(books, "fetch_rss_xml", side_effect=pages):
            self.assertEqual(books.fetch_entire_shelf("read", 30), [books.Book("Book", "Author", "https://example.com/1")])


if __name__ == "__main__":
    unittest.main()
