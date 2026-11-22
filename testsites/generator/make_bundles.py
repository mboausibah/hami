"""Write the synthetic 'kit' bundles shared by Site A (NovaMart VIP) and Site D (Quorvia login wall).

Both sites serve byte-identical app chunks and an English language pack (content-hashed build names, like a
real Vite build), so kit fingerprinting can be tested without any private data. Fictional strings only.

    python testsites/generator/make_bundles.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SITES = Path(__file__).resolve().parent.parent / "sites"

LANG_PACK = {
    "nav.tasks": "Task hall", "nav.vip": "VIP levels", "nav.team": "My team", "nav.wallet": "Wallet",
    "task.grab": "Grab orders", "task.daily": "Daily tasks completed", "task.locked": "Tasks are locked for your level",
    "task.unlock": "Recharge to unlock more tasks", "task.commission": "Commission per order",
    "vip.title": "VIP level benefits", "vip.upgrade": "Upgrade VIP level", "vip.v1": "VIP 1", "vip.v2": "VIP 2",
    "vip.v3": "VIP 3", "vip.req": "Deposit required for this VIP level",
    "wallet.deposit": "Deposit", "wallet.depositNow": "Deposit now", "wallet.recharge": "Recharge",
    "wallet.rechargeAmount": "Recharge amount", "wallet.withdraw": "Withdraw", "wallet.withdrawNow": "Withdraw now",
    "wallet.withdrawRule": "Withdrawal is available after completing all tasks of your level",
    "wallet.withdrawFee": "Withdrawal fee", "wallet.balance": "Available balance",
    "invite.code": "Invitation code", "invite.friends": "Invite friends to earn commission",
    "invite.reward": "Invitation reward", "service.online": "Online customer service",
    "ar.deposit": "إيداع", "ar.withdraw": "سحب", "ar.tasks": "المهام اليومية", "ar.vip": "مستوى VIP",
    "ar.invite": "رمز الدعوة", "ar.unlock": "اشحن الرصيد لفتح المهام",
}

TASK_HALL_JS = """export function renderTaskHall(t){const levels=[1,2,3].map(n=>({name:'VIP '+n,orders:20+n*10}));
return {title:t['nav.tasks'],levels,locked:t['task.locked'],cta:t['task.unlock'],grab:t['task.grab']}}
export const ORDER_STATES=['pending','frozen','completed'];export const RECHARGE_PRESETS=[500,1500,5000];
"""
RECHARGE_CSS = """.recharge-panel{display:grid;gap:8px;padding:16px;border-radius:12px;background:#fff7ef}
.recharge-panel .preset{border:1px solid #ffb36b;border-radius:8px;padding:8px 12px;font-weight:700}
.recharge-panel .preset.active{background:#ff7a00;color:#fff}.vip-badge{display:inline-block;padding:2px 8px;border-radius:999px;background:#2b1d0e;color:#ffd27a}
.withdraw-rule{font-size:12px;color:#7a5a3a}.task-locked{opacity:.5;filter:grayscale(1)}
"""
TEAM_JS = """export function inviteLink(code){return '/register?inviteCode='+encodeURIComponent(code)}
export function teamLevels(){return [{level:1,rate:0.3},{level:2,rate:0.2},{level:3,rate:0.1}]}
export const TEAM_COPY={title:'My team',share:'Share your invitation link',earn:'Earn commission from your team'};
"""


def _grow_js(name: str, base: str) -> str:
    """Realistic chunk size (a few KB): generated helper functions, as a bundler would emit."""
    helpers = "".join(
        f"function {name}H{i}(e,t){{const n=(e||[]).map(r=>({{id:r.id,lv:r.level*{i + 1},amt:r.amount+{i * 50}}}));"
        f"return t?n.filter(r=>r.lv>={i}):n}}\n" for i in range(30))
    return base + helpers + f"export const {name}Helpers=[" + ",".join(f"{name}H{i}" for i in range(30)) + "];\n"


def _grow_css(base: str) -> str:
    rules = "".join(f".recharge-panel .row-{i}{{margin:{i}px 0;padding:{i % 7 + 4}px;border-left:{i % 3}px solid #ff7a00}}\n"
                    for i in range(40))
    return base + rules


def build_name(stem: str, ext: str, content: str) -> str:
    h = hashlib.sha256(content.encode()).digest()
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    code = "".join(alphabet[b % len(alphabet)] for b in h[:8])
    if not any(c.isdigit() for c in code):
        code = code[:7] + "7"
    return f"{stem}-{code}.{ext}"


def main() -> dict[str, str]:
    files = {
        ("en-US", "js"): "export default " + json.dumps(LANG_PACK, ensure_ascii=False) + ";\n",
        ("views-taskHall", "js"): _grow_js("taskHall", TASK_HALL_JS),
        ("views-team", "js"): _grow_js("team", TEAM_JS),
        ("views-recharge", "css"): _grow_css(RECHARGE_CSS),
    }
    names = {}
    for site in ("site-a", "site-d"):
        d = SITES / site / "assets"
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*-*.*"):
            if old.suffix in (".js", ".css"):
                old.unlink()
        for (stem, ext), content in files.items():
            name = build_name(stem, ext, content)
            (d / name).write_text(content, encoding="utf-8", newline="\n")
            names[stem] = name
    (SITES / "bundles.json").write_text(json.dumps(names, indent=2), encoding="utf-8")
    print("bundles:", names)
    return names


if __name__ == "__main__":
    main()
