import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import brief

NOW = dt.datetime(2026, 10, 21, 1, tzinfo=brief.UTC)
SOURCE = {'name': 'Test', 'category': '新闻'}


def rss(date='Wed, 21 Oct 2026 00:00:00 GMT', link='https://example.com/a'):
    return f'''<rss><channel><item><title>新闻标题</title><link>{link}</link><pubDate>{date}</pubDate><description><![CDATA[<p>摘要</p><script>bad()</script>]]></description></item></channel></rss>'''.encode()


class BriefTests(unittest.TestCase):
    def test_rss_and_sanitization(self):
        items, skipped = brief.parse_feed(rss(), SOURCE, NOW, 24, 120)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['summary'], '摘要')
        self.assertEqual(skipped, 0)

    def test_old_future_missing_dates(self):
        for value in ['Mon, 19 Oct 2026 00:00:00 GMT', 'Thu, 22 Oct 2026 00:00:00 GMT', 'bad']:
            self.assertEqual(brief.parse_feed(rss(value), SOURCE, NOW, 24, 120)[0], [])

    def test_unsafe_links(self):
        for value in ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:password@example.com']:
            self.assertEqual(brief.parse_feed(rss(link=value), SOURCE, NOW, 24, 120)[0], [])

    def test_atom(self):
        data = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom</title><link href="https://example.com/a"/><updated>2026-10-21T00:00:00Z</updated><summary>Short</summary></entry></feed>'
        self.assertEqual(len(brief.parse_feed(data, SOURCE, NOW, 24, 120)[0]), 1)

    def test_entities_and_non_feeds_rejected(self):
        for data in [b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>', '<!DOCTYPE rss><rss/>'.encode('utf-16'), b'<html/>']:
            with self.assertRaises(brief.BriefError):
                brief.parse_feed(data, SOURCE, NOW, 24, 120)

    def test_duplicate_tracking_and_source_limit(self):
        item = brief.parse_feed(rss(), SOURCE, NOW, 24, 120)[0][0]
        same = dict(item, url=item['url'] + '?utm_source=x', title='不同标题')
        other = dict(item, url='https://example.com/b', title='第二条')
        self.assertEqual(len(brief.select_items([item, same, other], 12, 4)), 2)
        self.assertEqual(len(brief.select_items([item, other], 12, 1)), 1)

    def test_all_sources_fail_no_publication(self):
        with tempfile.TemporaryDirectory() as tmp, patch('brief.fetch_source', return_value=([], {'name':'Test','ok':False,'skipped':0,'eligible':0})):
            with self.assertRaises(brief.BriefError):
                brief.build('config.json', tmp + '/site', tmp + '/meta.json')
            self.assertFalse(Path(tmp, 'site').exists())

    def test_partial_and_empty_are_explicit(self):
        config = json.loads(Path('config.json').read_text(encoding='utf-8'))
        page = brief.render(config, [], [{'name':'Test','ok':False,'skipped':0,'eligible':0}], NOW, 'id')
        self.assertIn('覆盖不完整', page)
        self.assertIn('暂无可核验', page)

    def test_render_escapes_injected_markup(self):
        config = json.loads(Path('config.json').read_text(encoding='utf-8'))
        item = brief.parse_feed(rss(), SOURCE, NOW, 24, 120)[0][0]
        item['title'] = '<img src=x onerror=bad()>'
        page = brief.render(config, [item], [], NOW, 'id')
        self.assertNotIn('<img', page)
        self.assertIn('&lt;img', page)

    def test_readiness_rejects_stale_page(self):
        with patch('brief.read_url', return_value=b'<html>old</html>'):
            with self.assertRaises(brief.BriefError):
                brief.verify_page('https://example.com/', 'new', attempts=1)
        with patch('brief.read_url', return_value=b'<meta name="brief-build" content="new">'):
            brief.verify_page('https://example.com/', 'new', attempts=1)

    def test_secret_only_in_post_body(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"code":200}'
        meta = {'date':'2026-10-21','title':'Daily','count':3,'partial':False}
        output = io.StringIO()
        with patch('brief.urllib.request.build_opener', return_value=opener), contextlib.redirect_stdout(output):
            brief.send_bark('FAKE_KEY_TEST_ONLY', meta, 'https://example.com/')
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://api.day.app/push')
        self.assertEqual(json.loads(req.data)['device_key'], 'FAKE_KEY_TEST_ONLY')
        self.assertNotIn('FAKE_KEY_TEST_ONLY', output.getvalue())

    def test_bark_failure_hides_key_and_does_not_retry(self):
        opener = MagicMock()
        opener.open.side_effect = RuntimeError('FAKE_KEY_TEST_ONLY')
        with patch('brief.urllib.request.build_opener', return_value=opener):
            with self.assertRaises(brief.BriefError) as caught:
                brief.send_bark('FAKE_KEY_TEST_ONLY', {'date':'x','title':'x','count':0,'partial':False}, 'https://example.com/')
        self.assertNotIn('FAKE_KEY_TEST_ONLY', str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)

    def test_missing_key_prevents_network(self):
        with patch.dict(os.environ, {'BARK_KEY':''}), patch('brief.verify_page') as verify:
            with self.assertRaises(brief.BriefError):
                brief.notify('does-not-exist.json')
            verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
