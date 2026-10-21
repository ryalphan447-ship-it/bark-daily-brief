"""Daily public RSS digest. Python 3.12+, standard library only."""
import argparse
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

BJT = dt.timezone(dt.timedelta(hours=8))
UTC = dt.timezone.utc
MAX_BYTES = 3_000_000


class BriefError(Exception):
    """Messages in this exception are safe for public Actions logs."""


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'li'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = TextOnly()
    parser.feed(value or '')
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def safe_url(value):
    try:
        p = urllib.parse.urlsplit((value or '').strip())
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            return ''
        if any(ord(c) < 32 for c in value):
            return ''
        return urllib.parse.urlunsplit(p._replace(fragment=''))
    except ValueError:
        return ''


def canonical(url):
    p = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urllib.parse.urlunsplit(p._replace(netloc=p.netloc.lower(), query=urllib.parse.urlencode(query), fragment=''))


def parse_date(value):
    if not value:
        return None
    try:
        result = email.utils.parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError):
        try:
            result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    return result.astimezone(UTC) if result.tzinfo else None


def child_text(node, names):
    for child in node:
        if child.tag.split('}')[-1] in names:
            return ''.join(child.itertext()).strip()
    return ''


def parse_feed(data, source, now, hours, summary_chars):
    # Reject DTDs/entities, including XML encoded as UTF-16/32.
    if re.search(br'<!\s*(DOCTYPE|ENTITY)', data.replace(b'\x00', b''), re.I):
        raise BriefError('RSS 使用不支持的 XML 声明。')
    root = ET.fromstring(data)
    if root.tag.split('}')[-1].lower() not in ('rss', 'feed', 'rdf'):
        raise BriefError('来源未返回 RSS/Atom。')
    items, skipped = [], 0
    for node in root.iter():
        if node.tag.split('}')[-1] not in ('item', 'entry'):
            continue
        title = plain(child_text(node, {'title'}))
        link = child_text(node, {'link'})
        if not link:
            for child in node:
                if child.tag.split('}')[-1] == 'link' and child.get('rel', 'alternate') == 'alternate':
                    link = child.get('href', '')
                    break
        link = safe_url(link)
        date = parse_date(child_text(node, {'pubDate', 'published', 'date'}))
        if date is None:
            date = parse_date(child_text(node, {'updated'}))
        if date is None:
            skipped += 1
            continue
        if not title or not link or not now - dt.timedelta(hours=hours) <= date <= now + dt.timedelta(minutes=5):
            continue
        summary = plain(child_text(node, {'description', 'summary'}))
        if len(summary) > summary_chars:
            summary = summary[:summary_chars].rstrip() + '…'
        items.append({'title': title[:240], 'url': link, 'summary': summary,
                      'published': date.isoformat(), 'source': source['name'],
                      'category': source.get('category', '新闻')})
    return items, skipped


def read_url(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'MorningBrief/1.0 (personal RSS reader)', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=20) as response:
        if urllib.parse.urlsplit(response.url).scheme != 'https':
            raise BriefError('来源重定向至非 HTTPS。')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise BriefError('来源内容超过大小限制。')
    return data


def fetch_source(source, config, now):
    for attempt in range(2):
        try:
            data = read_url(source['url'])
            items, skipped = parse_feed(data, source, now, config['lookback_hours'], config['summary_chars'])
            return items, {'name': source['name'], 'ok': True, 'skipped': skipped, 'eligible': len(items)}
        except Exception:
            if attempt == 0:
                time.sleep(2)
    return [], {'name': source['name'], 'ok': False, 'skipped': 0, 'eligible': 0}


def select_items(items, total, per_source):
    selected, seen_urls, seen_titles, counts = [], set(), set(), {}
    for item in sorted(items, key=lambda x: x['published'], reverse=True):
        url = canonical(item['url'])
        title = re.sub(r'\W+', '', item['title']).casefold()
        source = item['source']
        if url in seen_urls or title in seen_titles or counts.get(source, 0) >= per_source:
            continue
        selected.append(item)
        seen_urls.add(url)
        seen_titles.add(title)
        counts[source] = counts.get(source, 0) + 1
        if len(selected) >= total:
            break
    return selected


def render(config, items, statuses, now, marker, demo=False):
    esc = html.escape
    cards = []
    for i, item in enumerate(items, 1):
        stamp = dt.datetime.fromisoformat(item['published']).astimezone(BJT).strftime('%m-%d %H:%M')
        cards.append(f'''<article><div class="meta">{i:02d} / {esc(item['category'])} · {esc(item['source'])} · {stamp}</div>
<h2><a href="{esc(item['url'], quote=True)}" rel="noopener noreferrer">{esc(item['title'])}</a></h2>
<p>{esc(item['summary'] or '该来源未提供摘要，请阅读原文。')}</p><a class="read" href="{esc(item['url'], quote=True)}" rel="noopener noreferrer">阅读原文 ↗</a></article>''')
    health = ''.join(f"<li>{esc(s['name'])}：" + (f"可用，时间窗内 {s['eligible']} 条；{s['skipped']} 条日期不明已跳过" if s['ok'] else '获取失败，本期未收录') + '</li>' for s in statuses)
    notice = '<div class="notice">版式演示 · 以下为示例内容，不是实时新闻</div>' if demo else ''
    if any(not s['ok'] for s in statuses):
        notice += '<div class="notice">部分来源暂时不可用，本期覆盖不完整。</div>'
    body = ''.join(cards) or '<article><h2>本期暂无可核验时间的新条目</h2><p>不会用过期新闻填充。请查看下方来源状态。</p></article>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="brief-build" content="{esc(marker)}"><title>{esc(config['title'])} · {now:%Y-%m-%d}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f5ef;color:#182e2b;font-family:system-ui,-apple-system,'Microsoft YaHei',sans-serif;line-height:1.8}}main{{max-width:1040px;margin:auto;padding:48px 24px}}.brand{{font-size:12px;letter-spacing:3px;font-weight:700;color:#507369}}header{{border-bottom:2px solid #254c40;padding:20px 0 28px}}h1{{font-size:clamp(32px,6vw,54px);letter-spacing:-1px;line-height:1.2;margin:16px 0}}.sub,.meta{{font-size:13px;color:#60746b}}.stats{{display:flex;gap:24px;flex-wrap:wrap;margin-top:20px}}.stats b{{font-size:22px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:0 32px}}article{{padding:28px 0;border-bottom:1px solid #d2dbd2;min-width:0}}h2{{font-size:21px;line-height:1.5;margin:10px 0}}a{{color:inherit;text-decoration:none;overflow-wrap:anywhere}}a:hover{{text-decoration:underline}}p{{color:#42594f;font-size:15px}}.read{{font-size:13px;color:#236248;font-weight:650}}.notice{{background:#eee6cd;padding:12px 16px;margin:20px 0;font-size:14px}}footer{{margin-top:32px;font-size:13px;color:#63756b}}details{{background:#edf0e8;padding:14px 18px;border-radius:8px}}summary{{cursor:pointer}}@media(max-width:650px){{main{{padding:24px 20px}}.grid{{grid-template-columns:1fr}}h2{{font-size:20px}}}}@media(prefers-color-scheme:dark){{body{{background:#182520;color:#e5eee5}}p,.sub,.meta,footer{{color:#bbcbbd}}details{{background:#263a30}}.notice{{background:#4b4530}}.read{{color:#9ed0ae}}}}</style></head><body><main>
<div class="brand">MORNING / 每日阅读</div><header><div class="sub">{now:%Y年%m月%d日} · 北京时间</div><h1>{esc(config['title'])}</h1>
<div class="sub">用几分钟，了解正在发生的事。</div><div class="stats"><span><b>{len(items):02d}</b> 条速览</span><span>回看 {config['lookback_hours']} 小时</span><span>{now:%H:%M} 生成</span></div></header>{notice}
<section class="grid">{body}</section><footer><details><summary>来源状态与收录规则</summary><ul>{health}</ul><p>按发布时间排序、去重，每来源最多 {config['per_source']} 条。摘要摘自 RSS，并非 AI 分析；只展示短摘录，不转载新闻全文。</p></details>
<p>这是公开新闻阅读页，不包含个人信息。当前网址仅保留最近一期；旧通知也会打开最近一期。新闻版权归原发布者所有，请以原文为准。</p></footer></main></body></html>'''


def build(config_path, out, meta_path, demo=False):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    now = dt.datetime.now(BJT)
    for field, maximum in [('lookback_hours', 168), ('max_items', 50), ('per_source', 20), ('summary_chars', 200)]:
        if not isinstance(config[field], int) or not 1 <= config[field] <= maximum:
            raise BriefError('配置中的数量或时间范围无效。')
    if not 1 <= len(config['feeds']) <= 12 or any(not safe_url(s['url']).startswith('https://') for s in config['feeds']):
        raise BriefError('请配置 1–12 个 HTTPS RSS 来源。')
    if demo:
        items = [{'title': title, 'summary': summary, 'url': 'https://example.com/', 'source': '演示来源', 'category': category, 'published': now.astimezone(UTC).isoformat()} for title, summary, category in [
            ('国际动态：在这里快速浏览当天的重要消息', '每条新闻保留来源、发布时间和原文入口。摘要来自公开订阅源，避免为填满版面而混入过期内容。', '国际'),
            ('科技观察：关注新产品与研究进展', '页面适配手机阅读。点击通知后进入完整简报，再选择感兴趣的新闻阅读原文。', '科技'),
            ('信息有出处，阅读有边界', '单个来源暂时失败不会阻止其他新闻发布；所有来源失败时停止更新和推送。', '综合'),
            ('后续可以扩展更多日常主题', '股票、投资、AI 工具与餐食模块可逐步加入，涉及个人资料时先调整访问保护。', '生活')]]
        statuses = [{'name':'演示来源','ok':True,'skipped':0,'eligible':len(items)}]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda s: fetch_source(s, config, now), config['feeds']))
        statuses = [r[1] for r in results]
        if not any(s['ok'] for s in statuses):
            raise BriefError('全部 RSS 来源失败，停止发布和推送。请稍后重试。')
        items = select_items([item for r in results for item in r[0]], config['max_items'], config['per_source'])
    marker = uuid.uuid4().hex
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text(render(config, items, statuses, now, marker, demo), encoding='utf-8')
    (out / 'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
    (out / '.nojekyll').touch()
    meta = {'build_id': marker, 'title': config['title'], 'date': now.strftime('%Y-%m-%d'), 'count': len(items), 'partial': any(not s['ok'] for s in statuses), 'demo': demo}
    Path(meta_path).parent.mkdir(parents=True, exist_ok=True)
    Path(meta_path).write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    print(f"Generated {len(items)} items; {sum(s['ok'] for s in statuses)}/{len(statuses)} sources available.")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BriefError('Bark 返回重定向，已停止以保护密钥。')


def send_bark(key, meta, page_url):
    payload = {'device_key': key, 'title': f"{meta['date']} · {meta['title']}",
               'body': f"本期 {meta['count']} 条新闻。点击阅读完整简报。" + (' 部分来源暂不可用。' if meta['partial'] else ''),
               'url': page_url, 'group': '每日简报', 'isArchive': 0}
    req = urllib.request.Request('https://api.day.app/push', data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                 headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    # Never print request, key, response body, or raw exceptions. Do not retry
    # ambiguous POST timeouts: Bark may already have accepted the notification.
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
            result = json.loads(response.read(64000))
        if result.get('code') != 200:
            raise ValueError('rejected')
    except Exception:
        raise BriefError('Bark 未确认接收。检查 Secret 和服务状态；超时可能已送达，重跑可能重复。') from None
    print('Bark accepted the notification; device delivery must be checked on iPhone.')


def verify_page(url, marker, attempts=12):
    for attempt in range(attempts):
        try:
            page = read_url(url + '?build=' + marker).decode('utf-8')
            if f'name="brief-build" content="{marker}"' in page:
                return
        except Exception:
            pass
        if attempt + 1 < attempts:
            time.sleep(10)
    raise BriefError('发布后仍无法确认本期网页，未发送通知。请检查 Pages。')


def notify(meta_path):
    key = os.environ.get('BARK_KEY', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,256}', key):
        raise BriefError('缺少或无效的 BARK_KEY：请在 GitHub Actions Secrets 保存设备密钥，不是完整测试链接。')
    base = os.environ.get('PAGE_URL', '').strip()
    if not safe_url(base).startswith('https://') or urllib.parse.urlsplit(base).query or urllib.parse.urlsplit(base).fragment:
        raise BriefError('缺少或无效的 Pages HTTPS 地址。')
    url = base.rstrip('/') + '/index.html'
    meta = json.loads(Path(meta_path).read_text(encoding='utf-8'))
    if meta.get('demo'):
        raise BriefError('演示简报不能发送。')
    verify_page(url, meta['build_id'])
    send_bark(key, meta, url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['build', 'notify'])
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--out', default='site')
    parser.add_argument('--meta', default='work/meta.json')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            build(args.config, args.out, args.meta, args.demo)
        else:
            notify(args.meta)
    except BriefError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('处理失败。请检查配置和运行环境；已隐藏异常细节以避免敏感信息进入日志。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
