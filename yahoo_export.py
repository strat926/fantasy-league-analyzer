#!/usr/bin/env python3
"""
Yahoo Fantasy NBA 聯盟資料匯出（給「九項賽季作戰室」用）

匯出內容：聯盟設定、8 隊陣容、本週對戰、自由球員、所有相關球員的本季數據。
只需要 requests：  pip3 install requests
執行：            python3 yahoo_export.py
第一次執行會請你到 Yahoo 授權，之後會自動更新登入憑證（存在 yahoo_token.json）。
"""
import base64
import datetime
import json
import pathlib
import sys
import time
import urllib.parse
import webbrowser

try:
    import requests
except ImportError:
    sys.exit("缺少 requests 套件，請先執行：pip3 install requests")

HERE = pathlib.Path(__file__).resolve().parent
CFG_FILE = HERE / "yahoo_config.json"
TOKEN_FILE = HERE / "yahoo_token.json"
DEBUG_DIR = HERE / "debug"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2/"
DEBUG = "--debug" in sys.argv

CFG_TEMPLATE = {
    "client_id": "貼上 Yahoo App 的 Client ID",
    "client_secret": "貼上 Yahoo App 的 Client Secret",
    "redirect_uri": "https://localhost:8080",
    "league_id": "48312",
    "free_agents_count": 150,
}


# ---------------- config & OAuth ----------------
def load_cfg():
    if not CFG_FILE.exists():
        CFG_FILE.write_text(json.dumps(CFG_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(f"已建立設定檔 {CFG_FILE.name}，請填入 client_id 和 client_secret 後再執行一次。")
    cfg = json.loads(CFG_FILE.read_text(encoding="utf-8"))
    if "貼上" in cfg.get("client_id", "") or "貼上" in cfg.get("client_secret", ""):
        sys.exit(f"請先在 {CFG_FILE.name} 填入 client_id 和 client_secret。")
    return cfg


def _basic(cfg):
    raw = f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode(),
            "Content-Type": "application/x-www-form-urlencoded"}


def _save_token(tok):
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    return tok


def authorize(cfg):
    q = urllib.parse.urlencode({"client_id": cfg["client_id"], "redirect_uri": cfg.get("redirect_uri", "https://localhost:8080"),
                                "response_type": "code", "language": "en-us"})
    url = f"{AUTH_URL}?{q}"
    print("\n請在瀏覽器登入 Yahoo 並按「同意」。如果瀏覽器沒有自動打開，請手動打開這個網址：\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("按「同意」後，瀏覽器會跳到一個打不開的 localhost 頁面，這是正常的。")
    code = input("把那個頁面網址列的整串網址複製貼上（或只貼 code= 後面的授權碼）：").strip()
    if "code=" in code:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get("code", [""])[0]
    r = requests.post(TOKEN_URL, headers=_basic(cfg), data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": cfg.get("redirect_uri", "https://localhost:8080")})
    if r.status_code != 200:
        sys.exit(f"取得授權失敗（{r.status_code}）：{r.text[:300]}")
    print("授權成功，之後執行不用再授權。")
    return _save_token(r.json())


def refresh(cfg, tok):
    r = requests.post(TOKEN_URL, headers=_basic(cfg), data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        "redirect_uri": cfg.get("redirect_uri", "https://localhost:8080")})
    if r.status_code != 200:
        print("登入憑證更新失敗，重新授權一次。")
        return authorize(cfg)
    new = r.json()
    new.setdefault("refresh_token", tok["refresh_token"])
    return _save_token(new)


def get_token(cfg):
    if TOKEN_FILE.exists():
        tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return refresh(cfg, tok) if time.time() > tok.get("expires_at", 0) else tok
    return authorize(cfg)


class Yahoo:
    def __init__(self, cfg):
        self.cfg, self.tok, self.n = cfg, get_token(cfg), 0

    def get(self, path, allow_fail=False):
        for attempt in range(3):
            r = requests.get(API + path, params={"format": "json"},
                             headers={"Authorization": f"Bearer {self.tok['access_token']}"}, timeout=30)
            if r.status_code == 401:
                self.tok = refresh(self.cfg, self.tok)
                continue
            if r.status_code == 999 or r.status_code == 429:   # Yahoo rate limit
                time.sleep(5 * (attempt + 1))
                continue
            break
        self.n += 1
        if DEBUG:
            DEBUG_DIR.mkdir(exist_ok=True)
            (DEBUG_DIR / f"{self.n:03d}.json").write_text(
                json.dumps({"path": path, "status": r.status_code, "body": r.text[:200000]}, ensure_ascii=False),
                encoding="utf-8")
        if r.status_code != 200:
            if allow_fail:
                return None
            sys.exit(f"Yahoo API 錯誤（{r.status_code}）：{path}\n{r.text[:400]}")
        time.sleep(0.15)
        return r.json()


# ---------------- JSON helpers (Yahoo JSON is deeply nested lists of one-key dicts) ----------------
def merge(lst):
    out = {}
    if isinstance(lst, dict):
        return dict(lst)
    for x in lst or []:
        if isinstance(x, dict):
            out.update(x)
        elif isinstance(x, list):
            out.update(merge(x))
    return out


def find_all(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from find_all(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from find_all(v, key)


BASE_POS = ["PG", "SG", "SF", "PF", "C"]


def parse_player(v):
    attrs = merge(v[0]) if v and isinstance(v[0], list) else merge(v)
    extra = {}
    for x in (v[1:] if isinstance(v, list) else []):
        if isinstance(x, dict):
            extra.update(x)
    pos = [e.get("position") for e in attrs.get("eligible_positions", []) if isinstance(e, dict)]
    slot = merge(extra.get("selected_position", [])).get("position", "")
    stats = {}
    for s in find_all(extra.get("player_stats", {}), "stat"):
        if isinstance(s, dict) and "stat_id" in s:
            stats[str(s["stat_id"])] = s.get("value")
    name = attrs.get("name", {})
    return {
        "key": attrs.get("player_key", ""), "id": attrs.get("player_id", ""),
        "name": name.get("full", "") if isinstance(name, dict) else str(name),
        "nba": attrs.get("editorial_team_abbr", ""),
        "pos": [p for p in BASE_POS if p in pos],
        "status": attrs.get("status", "") or "",
        "slot": slot, "_stats": stats,
    }


def players_in(j):
    return [parse_player(v) for v in find_all(j, "player") if isinstance(v, list)]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def split_pair(x):
    try:
        a, b = str(x).split("/")
        return num(a), num(b)
    except ValueError:
        return 0.0, 0.0


# ---------------- export ----------------
def main():
    cfg = load_cfg()
    y = Yahoo(cfg)

    game = merge(next(find_all(y.get("game/nba"), "game")))
    league_key = f"{game['game_key']}.l.{cfg['league_id']}"
    print(f"NBA {game.get('season')} 球季，聯盟 {league_key}")

    st = y.get(f"league/{league_key}/settings")
    lg_node = next(find_all(st, "league"))
    lg = merge(lg_node[0]) if isinstance(lg_node[0], list) else merge(lg_node)
    cats = []
    for s in find_all(st, "stat"):
        if isinstance(s, dict) and "stat_id" in s and "display_name" in s:
            cats.append({"id": str(s["stat_id"]), "name": s.get("display_name"),
                         "display_only": str(s.get("is_only_display_stat", "0")) == "1"})

    tj = y.get(f"league/{league_key}/teams")
    teams = []
    for v in find_all(tj, "team"):
        a = merge(v[0]) if isinstance(v, list) and v and isinstance(v[0], list) else merge(v)
        if "team_key" in a:
            teams.append({"key": a["team_key"], "name": a.get("name", ""),
                          "mine": str(a.get("is_owned_by_current_login", "0")) == "1", "players": []})
    print(f"隊伍 {len(teams)} 隊")

    for t in teams:
        t["players"] = players_in(y.get(f"team/{t['key']}/roster/players"))
        print(f"  {t['name']}: {len(t['players'])} 人")

    matchups = []
    sb = y.get(f"league/{league_key}/scoreboard", allow_fail=True)
    if sb:
        for m in find_all(sb, "matchup"):
            keys = [merge(v[0]).get("team_key") for v in find_all(m, "team")
                    if isinstance(v, list) and v and isinstance(v[0], list)]
            keys = [k for k in keys if k]
            if len(keys) == 2:
                matchups.append(keys)

    rostered = {p["key"] for t in teams for p in t["players"]}
    fas, seen = [], set()
    for sort, limit in (("AR", int(cfg.get("free_agents_count", 150))), ("OR", 100)):
        for start in range(0, limit, 25):
            page = players_in(y.get(f"league/{league_key}/players;status=A;sort={sort};start={start};count=25"))
            if not page:
                break
            for p in page:
                if p["key"] and p["key"] not in seen and p["key"] not in rostered:
                    seen.add(p["key"])
                    fas.append(p)
    print(f"自由球員 {len(fas)} 人")

    keys = list(rostered) + [p["key"] for p in fas]
    season, avg = {}, {}
    for i in range(0, len(keys), 25):
        chunk = ",".join(keys[i:i + 25])
        for p in players_in(y.get(f"league/{league_key}/players;player_keys={chunk}/stats;type=season")):
            season[p["key"]] = p["_stats"]
        aj = y.get(f"league/{league_key}/players;player_keys={chunk}/stats;type=average_season", allow_fail=True)
        for p in players_in(aj) if aj else []:
            avg[p["key"]] = p["_stats"]
        print(f"  數據 {min(i + 25, len(keys))}/{len(keys)}")

    stats = {}
    for k in keys:
        s, a = season.get(k, {}), avg.get(k, {})
        fgm, fga = (num(s.get("4")), num(s.get("3"))) if "3" in s else split_pair(s.get("9004003"))
        ftm, fta = (num(s.get("7")), num(s.get("6"))) if "6" in s else split_pair(s.get("9007006"))
        gp = num(s.get("0"))
        if not gp and num(a.get("12")) > 0:
            gp = round(num(s.get("12")) / num(a.get("12")))
        stats[k] = {"gp": gp, "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "tpm": num(s.get("10")),
                    "pts": num(s.get("12")), "reb": num(s.get("15")), "ast": num(s.get("16")),
                    "stl": num(s.get("17")), "blk": num(s.get("18")), "tov": num(s.get("19"))}

    for t in teams:
        for p in t["players"]:
            p.pop("_stats", None)
    for p in fas:
        p.pop("_stats", None)

    out = {
        "source": "yahoo_export.py",
        "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "league": {"key": league_key, "name": lg.get("name", ""), "season": game.get("season"),
                   "num_teams": len(teams), "current_week": lg.get("current_week"), "stat_categories": cats},
        "teams": teams, "matchups": matchups, "free_agents": fas, "stats": stats,
    }
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    for name in (f"league_{stamp}.json", "league_latest.json"):
        (HERE / name).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    with_gp = sum(1 for v in stats.values() if v["gp"] > 0)
    print(f"\n完成：league_{stamp}.json（{len(teams)} 隊、{len(fas)} 位自由球員、{with_gp} 人有本季數據，呼叫 API {y.n} 次）")
    print("把這個檔案拖進「九項賽季作戰室」頁面就能分析。")


if __name__ == "__main__":
    main()
