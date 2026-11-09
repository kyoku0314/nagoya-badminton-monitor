import urllib.request
from html.parser import HTMLParser

URL = "https://www.net.city.nagoya.jp/cgi-bin/sp/sps04001"

class FormInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_form = False
        self.forms = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_form = True
            self.forms += 1
            print("FORM", self.forms, "method:", attrs.get("method", "GET"), "action:", attrs.get("action", ""))
        if self.in_form and tag in ("input", "select", "button"):
            print(tag, "name:", attrs.get("name", ""), "type:", attrs.get("type", ""), "value:", attrs.get("value", "")[:60])

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False

req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as r:
    raw = r.read()
    print("HTTP:", r.status)
    print("Final URL:", r.geturl())
    print("Content-Type:", r.headers.get("Content-Type"))
    print("Bytes:", len(raw))
    charset = r.headers.get_content_charset() or "shift_jis"

html = raw.decode(charset, errors="replace")
print("Response body (first 1500 characters):")
print(html[:1500])
FormInspector().feed(html)
print("Forms found:", FormInspector().forms if False else html.lower().count("<form"))
