"""Read-only Nagoya badminton availability monitor. No login or booking submission."""
import datetime as dt
import http.client
import http.cookiejar
import json
from browser_fallback import query_with_browser
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
FAILED_STATE = Path("failed_dates.json")
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
    with opener.open(req, timeout=8) as response:
        return response.read().decode("shift_jis", errors="replace")

def parse_results(lines, day):
    results = []
    for i in range(len(lines)):
        if lines[i] != "No.":
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
    # Check every date from tomorrow through day 20 on each scheduled run.
    horizon = 20
    checked = 0
    failed = 0
    # Keep one browser-like session and one form state for the entire scan.
    # Only change the day; update month only when the scan crosses a month boundary.
    fields = dict(first.fields)
    fields.update(syumoku="024", joken="1", kyoyo1="07", kyoyo2="00",
                  chiiki="20", button="照会", syumokunm="バドミントン",
                  chiikinm="全地域", kyoyo1nm="全供用", kyoyo2nm="−−")
    current_month = None
    window = [now.date() + dt.timedelta(days=delta) for delta in range(1, horizon + 1)]
    try:
        old_failed = json.loads(FAILED_STATE.read_text()) if FAILED_STATE.exists() else []
    except (ValueError, OSError):
        old_failed = []
    priority = set(old_failed) if isinstance(old_failed, list) else set()
    dates = sorted(window, key=lambda d: (d.isoformat() not in priority, d))
    failed_dates = []
    for day in dates:
        if current_month != (day.year, day.month):
            fields["month"] = day.strftime("%m")
            current_month = (day.year, day.month)
        fields["day"] = day.strftime("%d")
        fields["kyoyo1"] = "05" if day.weekday() < 5 else "07"
        fields["kyoyo1nm"] = "夜間" if day.weekday() < 5 else "全供用"
        page = None
        try:
            candidate = Parser()
            candidate.feed(fetch(opener, "sps04002", fields))
            if "サービス時間外エラー画面" in candidate.text or "spsConnectionErr.html" in candidate.text:
                raise RuntimeError("Site service error")
            if "空き検索結果" not in " ".join(candidate.text):
                raise RuntimeError("Unexpected results page")
            page = candidate
        except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead, RuntimeError) as exc:
            print(f"HTTP query failed for {day}: {type(exc).__name__}", flush=True)
            print(f"Waiting 10 seconds before browser recovery for {day}", flush=True)
            time.sleep(10)
            try:
                html = query_with_browser(day, fields)
                candidate = Parser()
                candidate.feed(html)
                if "空き検索結果" not in " ".join(candidate.text):
                    raise RuntimeError("Browser did not return search results")
                page = candidate
                print(f"Browser recovered query for {day}", flush=True)
                # Browser session is separate from urllib session. Restart the
                # HTTP form session before querying subsequent dates.
                jar.clear()
                refreshed = Parser()
                refreshed.feed(fetch(opener, "sps04001"))
                if "syumoku" in refreshed.fields:
                    fields = dict(refreshed.fields)
                    fields.update(syumoku="024", joken="1", kyoyo1="07",
                                  kyoyo2="00", chiiki="20", button="照会",
                                  syumokunm="バドミントン", chiikinm="全地域",
                                  kyoyo1nm="全供用", kyoyo2nm="−−",
                                  month=day.strftime("%m"), day=day.strftime("%d"))
                    current_month = (day.year, day.month)
            except Exception as recovery_error:
                print(f"Browser recovery failed for {day}: {type(recovery_error).__name__}: {str(recovery_error)[:160]}", flush=True)
        if page is None:
            failed += 1
            failed_dates.append(day.isoformat())
            print(f"Skipped {day}; not marked empty", flush=True)
            continue
        rows = parse_results(page.text, day)
        for row in rows:
            key = "|".join(row.values())
            found[key] = row
        checked += 1
        print(day, "matching slots:", len(rows), flush=True)
        time.sleep(0.5)
    FAILED_STATE.write_text(json.dumps(failed_dates, ensure_ascii=False, indent=2) + "\\n".replace("\\n", "\n"))
    print(f"Priority backlog for next run: {len(failed_dates)} dates", flush=True)
    new = {k:v for k,v in found.items() if k not in previous}
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if new and webhook:
        for batch_start in range(0, len(new), 8):
            batch = list(new.values())[batch_start:batch_start+8]
            msg = "🏸 名古屋市羽毛球空场（尚未预约）\n" + "\n".join(
                f"{v['date']} {v['time']} | {v['area']} {v['venue']}" for v in batch)
            msg += "\n官网手动预约：https://www.net.city.nagoya.jp/cgi-bin/sp/sps04001\n请自行确认空位及网上预约期限；此消息不代表预约成功。"
            payload = json.dumps({"content": msg}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as response:
                print("Discord status:", response.status)
    elif new:
        print("Discord webhook missing; no notification sent")
    # Always report each completed monitoring cycle, including zero vacancies.
    if webhook:
        start_date = window[0].isoformat()
        end_date = window[-1].isoformat()
        status = ("✅ 全部查询完成" if failed == 0 else
                  f"⚠️ 有 {failed} 天查询失败，已安排下次优先补查")
        vacancy = (f"🏸 本次发现 {len(found)} 条匹配空场，其中新增 {len(new)} 条"
                   if found else "🏸 本次未发现符合条件的空场")
        report = (
            "📋 名古屋市羽毛球场地监控报告\\n"
            f"⏰ 查询时间：{now.strftime('%Y-%m-%d %H:%M')}（日本时间）\\n"
            f"📅 查询日期：{start_date} ～ {end_date}（共 {horizon} 天）\\n"
            f"📍 查询区域：全地域\\n"
            "🕕 周一至周五：夜間；周末：全供用\\n"
            f"🔎 成功查询：{checked}/{horizon} 天；失败：{failed} 天\\n"
            f"{vacancy}\\n"
            f"{status}\\n"
            "官网：https://www.net.city.nagoya.jp/cgi-bin/sp/sps04001"
        )
        payload = json.dumps({"content": report}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(webhook, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            print("Discord monitoring report status:", response.status, flush=True)
    else:
        print("Discord webhook missing; monitoring report not sent", flush=True)
    # Only mark notified slots as seen; retain history for 65 days.
    if webhook:
        previous.update(new)
        cutoff = (now.date() - dt.timedelta(days=1)).isoformat()
        previous = {k:v for k,v in previous.items() if v.get("date", "") >= cutoff}
        STATE.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n")
    print(f"Date coverage: {checked}/{horizon} checked, {failed} failed; new matching slots: {len(new)}; booking disabled", flush=True)

if __name__ == "__main__":
    main()
