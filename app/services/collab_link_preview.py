"""Small, bounded public web previews. Never resolves through internal services."""
import http.client
import ipaddress
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from functools import lru_cache


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values, self.title, self.in_title = {}, '', False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key and attrs.get('content'):
                self.values[key.lower()] = attrs['content']

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def public_target(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Public HTTPS URL required')
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Non-public address')
    return p, addresses[0][4][0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip):
        super().__init__(host, timeout=4, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        # Connect to the address we checked, while validating TLS for the real host.
        sock = socket.create_connection((self.ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


@lru_cache(maxsize=512)
def _preview(url, hour):
    original = url
    for _ in range(4):
        p, ip = public_target(url)
        conn = PinnedHTTPS(p.hostname, ip)
        try:
            conn.request('GET', (p.path or '/') + ('?' + p.query if p.query else ''), headers={
                'User-Agent': 'Dan-LinkPreview/1.0', 'Accept': 'text/html', 'Accept-Encoding': 'identity'})
            res = conn.getresponse()
            if res.status in (301, 302, 303, 307, 308):
                url = urljoin(url, res.getheader('Location', ''))
                continue
            if res.status != 200 or 'text/html' not in (res.getheader('Content-Type') or ''):
                return None
            body = res.read(512 * 1024).decode('utf-8', errors='replace')
        finally:
            conn.close()
        parser = MetadataParser()
        parser.feed(body)
        v = parser.values
        title = v.get('og:title') or v.get('twitter:title') or parser.title
        if not title.strip():
            return None
        return {'url': original, 'site': p.hostname, 'title': title.strip()[:240],
                'description': (v.get('og:description') or v.get('description') or '').strip()[:400]}
    return None


def preview(url):
    if len(url) > 2048:
        return None
    try:
        return _preview(url, int(time.time() // 3600))
    except (OSError, ValueError, http.client.HTTPException):
        return None
