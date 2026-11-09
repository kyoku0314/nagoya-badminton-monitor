import datetime
import http.client
import http.cookiejar
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "https://www.net.city.nagoya.jp/cgi-bin/sp/"
HEADERS = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1", "Referer": BASE + "sps04001", "Origin": "https://www.net.city.nagoya.jp", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "ja-JP,ja;q=0.9"}
COOKIES = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIES))

class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_user = False
        self.select = None
        self.fields = {}
        self.text = []
        self.links = []
        self.forms = []
        self.current_form = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.current_form = {"action": a.get("action"), "method": a.get("method")}
            self.forms.append(self.current_form)
            self.in_user = a.get("name") == "user"
        if self.in_user and tag == "input" and a.get("name"):
            self.fields[a["name"]] = a.get("value", "")
        if self.in_user and tag == "select":
            self.select = a.get("name")
        if self.in_user and tag == "option" and self.select and self.select not in self.fields:
            self.fields[self.select] = a.get("value", "")
        if tag == "a":
            self.links.append(a.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        if tag == "form":
            self.in_user = False
            self.current_form = None

    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text.append(s)

def fetch(url, data=None):
    request = urllib.request.Request(url, data=data, headers=HEADERS)
    with OPENER.open(request, timeout=30) as r:
        raw = r.read()
        print("HTTP", r.status, "URL", r.geturl(), "bytes", len(raw))
    print("Cookie count:", len(COOKIES))
    return raw.decode("shift_jis", errors="replace")

first = Inspector()
first.feed(fetch(BASE + "sps04001"))
print("Initial forms:", first.forms)
print("Initial fields:", first.fields)

# One read-only availability search, not a booking operation.
day = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date() + datetime.timedelta(days=2)
params = dict(first.fields)
params.update({
    "syumoku": "024",
    "month": day.strftime("%m"),
    "day": day.strftime("%d"),
    "joken": "1",
    "kyoyo1": "07",
    "kyoyo2": "00",
    "chiiki": "20",
    "button": "照会",
    "syumokunm": "バドミントン",
    "chiikinm": "全地域",
    "kyoyo1nm": "全供用",
    "kyoyo2nm": "−−",
})
print("Testing read-only search date:", day.isoformat())
try:
    html = fetch(BASE + "sps04002", urllib.parse.urlencode(params, encoding="shift_jis").encode("ascii"))
    parsed = Inspector()
    parsed.feed(html)
    print("Result forms:", parsed.forms)
    print("Result links:", parsed.links[:25])
    print("Result text (first 130 lines):")
    for line in parsed.text[:130]:
        print(line[:200])
except Exception as exc:
    print("Search request error:", type(exc).__name__, str(exc)[:350])
    if isinstance(exc, http.client.IncompleteRead):
        partial = exc.partial
        print("Partial response bytes:", len(partial))
        page = partial.decode("shift_jis", errors="replace")
        print("Partial response:", page[:3000])
        if "サービス時間外エラー画面" in page or "spsConnectionErr.html" in page:
            raise SystemExit("Reservation search is unavailable: service-hours error. Do not interpret as zero vacancies.")
