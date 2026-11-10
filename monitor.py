"""Read-only Nagoya badminton availability monitor. No login or booking submission."""
import datetime as dt
import http.client
import http.cookiejar
import json
import urllib.error
import os
import re
import time
import urllib.parse
import urllib.request
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
BASE = "https://www.net.city.nagoya.jp/cgi-bin/sp/"
STATE = Path("seen.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Referer": BASE + "sps04001",
    "Origin": "https://www.net.city.nagoya.jp",
    "Accept-Language": "ja-JP,ja;q=0.9",
}
class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.select = None
        self.fields = {}
        self.text = []
        self.capture = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.inside = a.get("name") == "user"
        if self.inside and tag == "input" and a.get("name"):
            if a.get("type") not in ("radio", "checkbox") or "checked" in a:
                self.fields[a["name"]] = a.get("value", "")
        if self.inside and tag == "select":
            self.select = a.get("name")
        if self.inside and tag == "option" and self.select and self.select not in self.fields:
            self.fields[self.select] = a.get("value", "")
        if tag in ("script", "style"):
            self.capture = True
    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False
        if tag == "select":
            self.select = None
        if tag in ("script", "style"):
            self.capture = False
    def handle_data(self, data):
        value = " ".join(data.split())
        if value and not self.capture:
            self.text.append(unicodedata.normalize("NFKC", value))

def fetch(opener, path, fields=None):
    data = urllib.parse.urlencode(fields, encoding="shift_jis").encode("ascii") if fields else None
    req = urllib.request.Request(BASE + path, data=data, headers=HEADERS)
    with opener.open(req, timeout=25) as response:
        return response.read().decode("shift_jis", errors="replace")

def parse_results(lines, day):
    results = []
    for i in range(len(lines) - 12):
        if lines[i:i+2] != ["No.", str(len(results) + 1)] and lines[i] != "No.":
            continue
        section = lines[i:i+18]
        def after(label):
            try:
                return section[section.index(label) + 1]
            except (ValueError, IndexError):
                return ""
        venue, area, slot = after("施設"), after("地域"), after("供用区分")
        match = re.search(r"(\d{1,2}):(\d{2})\s*[-−ー~～]\s*(\d{1,2}):(\d{2})", slot)
        if venue and area and match:
            start = int(match.group(1))*60 + int(match.group(2))
            end = int(match.group(3))*60 + int(match.group(4))
            if day.weekday() >= 5 or (start <= 18*60 and end >= 21*60):
                results.append({"date": day.isoformat(), "area": area, "venue": venue,
                                "time": f"{match.group(1).zfill(2)}:{match.group(2)}-{match.group(3).zfill(2)}:{match.group(4)}"})
    return results

def main():
    now = dt.datetime.now(JST)
    if not (8 <= now.hour < 24):
        print("Outside monitoring hours (JST).")
        return
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    first = Parser()
    first.feed(fetch(opener, "sps04001"))
    if "syumoku" not in first.fields:
        raise RuntimeError("Search form missing; refusing to interpret as empty")
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    found = {}
    # 14 queries per run, rotate through a 60-day horizon; limits load on city servers.
    horizon = 30
    for offset in range(4):
        delta = 2 + ((now.hour * 4 + now.minute // 15 + offset) % (horizon - 1))
        day = now.date() + dt.timedelta(days=delta)
        fields = dict(first.fields)
        fields.update(syumoku="024", month=day.strftime("%m"), day=day.strftime("%d"),
                      joken="1", kyoyo1="07", kyoyo2="00", chiiki="20",
                      button="照会", syumokunm="バドミントン", chiikinm="全地域",
                      kyoyo1nm="全供用", kyoyo2nm="−−")
        page = Parser()
        try:
            page.feed(fetch(opener, "sps04002", fields))
        except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead) as exc:
            print(f"Query failed for {day}: {type(exc).__name__}; restarting from menu")
            try:
                jar.clear()
                with opener.open(urllib.request.Request(
                    "https://www.net.city.nagoya.jp/sporec/index.html",
                    headers=HEADERS), timeout=12) as response:
                    response.read()
                refreshed = Parser()
                refreshed.feed(fetch(opener, "sps04001"))
                if "syumoku" not in refreshed.fields:
                    raise RuntimeError("Search form missing after recovery")
                fields = dict(refreshed.fields)
                fields.update(syumoku="024", month=day.strftime("%m"), day=day.strftime("%d"),
                              joken="1", kyoyo1="07", kyoyo2="00", chiiki="20",
                              button="照会", syumokunm="バドミントン", chiikinm="全地域",
                              kyoyo1nm="全供用", kyoyo2nm="−−")
                time.sleep(2)
                page = Parser()
                page.feed(fetch(opener, "sps04002", fields))
                print(f"Recovered query for {day}")
            except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead, RuntimeError) as recovery_error:
                print(f"Recovery failed for {day}: {type(recovery_error).__name__}; skipped, not marked empty")
                continue
        if "サービス時間外エラー画面" in page.text or "spsConnectionErr.html" in page.text:
            raise RuntimeError("Site service error; not zero availability")
        if "空き検索結果" not in " ".join(page.text):
            raise RuntimeError("Unexpected results page")
        rows = parse_results(page.text, day)
        for row in rows:
            key = "|".join(row.values())
            found[key] = row
        print(day, "matching slots:", len(rows))
        time.sleep(2.0)
    new = {k:v for k,v in found.items() if k not in previous}
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if new and webhook:
        for batch_start in range(0, len(new), 8):
            batch = list(new.values())[batch_start:batch_start+8]
            msg = "🏸 名古屋市羽毛球空场（尚未预约）\n" + "\n".join(
                f"{v['date']} {v['time']} | {v['area']} {v['venue']}" for v in batch)
            payload = json.dumps({"content": msg}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as response:
                print("Discord status:", response.status)
    elif new:
        print("Discord webhook missing; no notification sent")
    # Only mark notified slots as seen; retain history for 65 days.
    if webhook:
        previous.update(new)
        cutoff = (now.date() - dt.timedelta(days=1)).isoformat()
        previous = {k:v for k,v in previous.items() if v.get("date", "") >= cutoff}
        STATE.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n")
    print("New matching slots:", len(new), "Booking disabled")

if __name__ == "__main__":
    main()
