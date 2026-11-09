import urllib.request
from html.parser import HTMLParser

URL = "https://www.net.city.nagoya.jp/cgi-bin/sp/sps04001"

class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form = None
        self.select = None
        self.option = None
        self.option_text = []
        self.forms = 0
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms += 1
            self.form = self.forms
            print("FORM", self.form, "method", a.get("method"), "action", a.get("action"))
        elif self.form and tag == "select":
            self.select = a.get("name")
            self.fields.setdefault(self.form, {})[self.select] = []
        elif self.form and tag == "option" and self.select:
            self.option = a.get("value", "")
            self.option_text = []
        elif self.form and tag == "input":
            print("INPUT", self.form, a.get("name"), a.get("type"), repr(a.get("value", "")), "checked", "checked" in a)

    def handle_data(self, data):
        if self.option is not None:
            self.option_text.append(data)

    def handle_endtag(self, tag):
        if tag == "option" and self.option is not None:
            name = " ".join("".join(self.option_text).split())
            print("OPTION", self.form, self.select, repr(self.option), repr(name))
            self.fields[self.form][self.select].append((self.option, name))
            self.option = None
        elif tag == "select":
            self.select = None
        elif tag == "form":
            self.form = None

req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as response:
    raw = response.read()
    print("HTTP", response.status, "bytes", len(raw))
html = raw.decode("shift_jis", errors="replace")
inspector = Inspector()
inspector.feed(html)
print("Forms found:", inspector.forms)
