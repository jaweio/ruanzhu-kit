#!/usr/bin/env python3
"""自动截图：按路由逐页拍 Web 项目界面，存进 用户截图/，再由 screenshots.py 整理编号。

用已经装好的 Chrome 命令行截图（render_pdfs.py 也在用），不引入 Playwright 等新依赖。
路由优先从《说明书素材.json》的 entry 字段取——素材里抽到的就是真实页面，正好一一对应。

需要登录的页面：先用 --login 打开有界面的 Chrome，由**用户本人**登录一次，会话存到指定
profile 目录；之后截图复用该 profile。agent 不碰账号密码。

支持的端（--target）：
  web          浏览器能打开的项目（Web/H5/后台/Egret 等 H5 游戏），按路由批量截
  ios          iOS 模拟器（xcrun simctl）
  ios-device   连接电脑的 iPhone/iPad 真机（idevicescreenshot；iOS 17+ 需挂开发者镜像）
  ios-mirror   iPhone 真机投屏：**由用户自己**在 QuickTime 里把来源选成 iPhone，脚本只截该窗口
               （不会自动新建录制，避免误开 Mac 摄像头）
  android      Android 模拟器或 USB 真机（adb）
  mac          任意 macOS 应用窗口（screencapture，按应用名定位）——桌面应用、Electron 应用都走这个
  miniprogram  微信小程序：截微信开发者工具的模拟器窗口（mac 通道的快捷方式）
  auto         自动挑一个当前可用的端

web 是批量的；其余一次截一张当前屏幕：由人或 agent（computer-use / 模拟器工具 / adb）先把界面点到位，
再调用本脚本落盘。`--detect` 可以先看本机哪些端可用。

用法：
  # ① 先启动项目（由用户或 Claude 在另一个终端跑 npm run dev 等）
  # ② 登录一次（需要登录时才做）
  python3 capture.py --base-url http://localhost:5173 --login
  # ③ 按素材里的路由逐页截图
  python3 capture.py --base-url http://localhost:5173 \
      --spec soft-copyright-materials/说明书素材.json \
      --out soft-copyright-materials/01-XXX软件/用户截图
  # ④ 整理编号（对上模块名）
  python3 screenshots.py --materials soft-copyright-materials/01-XXX软件 --spec ...说明书素材.json
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_pdfs import CHROME, _find_tool  # noqa: E402

ADB = _find_tool("RUANZHU_ADB", str(Path.home() / "Android/sdk/platform-tools/adb"),
                 ["/opt/homebrew/bin/adb", "/usr/local/bin/adb"]) or "adb"

SAFE = re.compile(r"[^\w一-龥.-]+")


def wait_server(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except urllib.error.HTTPError:
            return True          # 4xx/5xx 也说明服务起来了
        except OSError:
            time.sleep(1)
    return False


def routes_from_spec(spec_path, limit):
    """素材里的 entry：/house/list、pages/index/index、views/LoginView 等。"""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    out = []
    for p in spec["pages"]:
        entry = str(p.get("entry", "")).strip()
        if not entry:
            continue
        path = entry if entry.startswith("/") else "/" + entry.lstrip("/")
        out.append({"path": path, "module": p["module"]})
    return out[:limit]


def login(base_url, profile):
    profile.mkdir(parents=True, exist_ok=True)
    print(f"打开 Chrome，请**你本人**在窗口里登录 {base_url}；登录完成后关闭该窗口。")
    print("（会话保存在 %s，之后截图复用，agent 不接触账号密码）" % profile)
    subprocess.run([CHROME, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                    base_url], check=False)
    print("窗口已关闭，可以开始截图。")


def http_status(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def detect(base_url=None):
    """探测本机可用的截图端。"""
    rows = []
    if base_url:
        rows.append(("web", wait_server(base_url, timeout=3), base_url))
    else:
        rows.append(("web", None, "传 --base-url 后才能判断"))

    booted = run(["xcrun", "simctl", "list", "devices", "booted"]).stdout
    sims = [l.strip() for l in booted.splitlines() if "Booted" in l]
    rows.append(("ios", bool(sims), "；".join(sims)[:70] or "没有已启动的模拟器（Simulator 里启动一个）"))

    idev = _find_tool("RUANZHU_IDEVICE", "/opt/homebrew/bin/idevicescreenshot", ["/usr/local/bin/idevicescreenshot"])
    ids = run([idev.replace("idevicescreenshot", "idevice_id"), "-l"]).stdout.split() if idev else []
    rows.append(("ios-device", bool(ids), ("已连接 " + "、".join(ids)) if ids else
                 ("装了 libimobiledevice，但没检测到已连接的 iPhone" if idev else "未装 libimobiledevice（brew install libimobiledevice）")))

    devs = [l.split("\t")[0] for l in run([ADB, "devices"]).stdout.splitlines()[1:] if "\tdevice" in l]
    rows.append(("android", bool(devs), ("；".join(f"{d}（{'模拟器' if d.startswith('emulator') else '真机'}）" for d in devs))
                 or "adb devices 为空"))

    apps = [a.strip() for a in run(["osascript", "-e",
            'tell application "System Events" to get name of every process whose background only is false']).stdout.split(",")]
    rows.append(("mac", bool(apps), f"{len(apps)} 个前台应用，如：" + "、".join(apps[:5])))
    wx = next((a for a in apps if "微信开发者工具" in a or "wechatwebdevtools" in a.lower()), None)
    rows.append(("miniprogram", bool(wx), f"检测到「{wx}」" if wx else
                 ("未运行微信开发者工具" if Path("/Applications/wechatwebdevtools.app").exists() else "本机未安装微信开发者工具")))
    return rows


def pick_auto(base_url):
    for name, ok, _ in detect(base_url):
        if ok and name != "mac":          # mac 需要指定应用名，不作为自动首选
            return name
    return "mac"


def looks_blank(path):
    """纯色图判定：缩成 32x32 位图统计颜色。全黑多半是缺「屏幕录制」权限，全白多半是页面没渲染完。
    依赖 macOS 自带 sips；其他平台跳过检查（返回 False，不误伤）。"""
    sips = Path("/usr/bin/sips")
    if not sips.exists():
        return False
    tmp = path.with_suffix(".probe.bmp")
    try:
        run([str(sips), "-s", "format", "bmp", "-z", "32", "32", str(path), "--out", str(tmp)])
        if not tmp.exists():
            return False
        d = tmp.read_bytes()
        off = int.from_bytes(d[10:14], "little")
        w = int.from_bytes(d[18:22], "little", signed=True)
        h = abs(int.from_bytes(d[22:26], "little", signed=True))
        bpp = int.from_bytes(d[28:30], "little") or 24
        stride = ((bpp * w + 31) // 32) * 4
        step = bpp // 8
        colors = {}
        for row in range(h):
            base = off + row * stride
            for col in range(w):
                i = base + col * step
                key = bytes(d[i:i + 3])
                if len(key) == 3:
                    colors[key] = colors.get(key, 0) + 1
        total = sum(colors.values()) or 1
        top = max(colors.values()) / total
        return len(colors) <= 3 or top > 0.97
    except Exception:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def next_index(out_dir):
    used = [int(m.group(1)) for f in out_dir.glob("*.png")
            if (m := re.match(r"^(\d+)_", f.name))]
    return max(used, default=0) + 1


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kw)


def shoot_ios_mirror(dest, app="QuickTime Player"):
    """iOS 17+ 真机：idevicescreenshot 需要挂开发者镜像，改用投屏窗口截图。

    **不会自动新建影片录制**——QuickTime 的默认来源是 Mac 摄像头，自动开会拍到人和房间。
    需要用户先自己设置好投屏：QuickTime →「文件 › 新建影片录制」→ 录制按钮旁的箭头里把来源
    选成自己的 iPhone，确认画面是手机屏幕之后，本脚本才去截那个窗口。
    """
    win, err = mac_window_id(app)
    if not win:
        return False, (f"没找到「{app}」的投屏窗口。请先手动设置投屏："
                       "打开 QuickTime →「文件 › 新建影片录制」→ 点红色录制键旁的箭头 →"
                       "在「摄像头」里选你的 iPhone → 画面变成手机屏幕后再重试。"
                       "（脚本不会替你打开，以免默认打开 Mac 摄像头拍到人）")
    r = run(["screencapture", "-x", "-o", "-l", win, str(dest)])
    if not dest.exists() or dest.stat().st_size < 5000:
        return False, (r.stderr.strip()[:120] or "截图失败")
    if looks_blank(dest):
        dest.unlink()
        return False, "投屏窗口是纯色：确认手机已解锁、画面已投出来"
    return True, ""


def shoot_ios_device(dest):
    idev = _find_tool("RUANZHU_IDEVICE", "/opt/homebrew/bin/idevicescreenshot", ["/usr/local/bin/idevicescreenshot"])
    if not idev:
        return False, "未装 libimobiledevice：brew install libimobiledevice"
    r = run([idev, str(dest)])
    if dest.exists() and dest.suffix == ".png" and dest.stat().st_size > 5000:
        return True, ""
    msg = (r.stderr.strip() or r.stdout.strip() or "真机截图失败：确认 iPhone 已解锁并信任本电脑")[:140]
    if "Developer disk image" in msg or "Invalid service" in msg:
        msg += "（iOS 17+ 需挂载开发者镜像；更省事的办法：--target ios-mirror，用 QuickTime 投屏后截窗口）"
    return False, msg


def shoot_ios(dest):
    booted = run(["xcrun", "simctl", "list", "devices", "booted"]).stdout
    if "Booted" not in booted:
        return False, "没有已启动的 iOS 模拟器：先在 Xcode/Simulator 里启动设备并把应用点到目标界面"
    r = run(["xcrun", "simctl", "io", "booted", "screenshot", str(dest)])
    if not dest.exists():
        return False, r.stderr.strip()[:120]
    if looks_blank(dest):
        dest.unlink()
        return False, "模拟器屏幕是纯色：确认应用已启动且不在黑屏/锁屏状态"
    return True, ""


def shoot_android(dest):
    devices = [l for l in run([ADB, "devices"]).stdout.splitlines()[1:] if "\tdevice" in l]
    if not devices:
        return False, "没有已连接的 Android 设备/模拟器：adb devices 为空"
    raw = subprocess.run([ADB, "exec-out", "screencap", "-p"], capture_output=True, timeout=60).stdout
    if len(raw) < 5000:
        return False, "adb 返回数据过小，截图失败"
    dest.write_bytes(raw)
    return True, ""


SWIFT_WINLIST = r'''
import CoreGraphics
import Foundation
let opts = CGWindowListOption(arrayLiteral: .optionOnScreenOnly, .excludeDesktopElements)
if let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] {
  for w in list {
    let owner = w[kCGWindowOwnerName as String] as? String ?? ""
    let num = w[kCGWindowNumber as String] as? Int ?? 0
    let name = w[kCGWindowName as String] as? String ?? ""
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    let h = b["Height"] as? Double ?? 0, wd = b["Width"] as? Double ?? 0
    if h > 120 && wd > 200 { print("\(num)|\(Int(wd*h))|\(owner)|\(name)") }
  }
}
'''


def mac_window_id(app):
    """用 CGWindowList 找目标应用最大的那个窗口；按窗口 ID 截图可避开遮挡。需要 Xcode 的 swift。"""
    swift = _find_tool("RUANZHU_SWIFT", "/usr/bin/swift", ["/usr/local/bin/swift"])
    if not swift:
        return None, "未找到 swift（Xcode 命令行工具），改用窗口区域截图"
    src = Path(tempfile.gettempdir()) / "ruanzhu_winlist.swift"
    src.write_text(SWIFT_WINLIST, encoding="utf-8")
    r = run([swift, str(src)])
    best, best_area = None, 0
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        num, area, owner = parts[0], int(parts[1]), parts[2]
        if app.lower() in owner.lower() or owner.lower() in app.lower():
            if area > best_area:
                best, best_area = num, area
    if best:
        return best, ""
    owners = sorted({l.split("|")[2] for l in r.stdout.splitlines() if len(l.split("|")) > 2})
    return None, f"窗口列表里没有「{app}」。当前有窗口的应用：{('、'.join(owners[:12])) or '无'}"


def mac_window_bounds(app):
    script = (f'tell application "System Events" to tell process "{app}" '
              'to get {position, size} of window 1')
    r = run(["osascript", "-e", script])
    nums = re.findall(r"-?\d+", r.stdout)
    if len(nums) < 4:
        return None, (r.stderr.strip() or "拿不到窗口位置")[:120] + \
            "（需要在 系统设置 › 隐私与安全性 › 辅助功能 里允许终端控制电脑）"
    x, y, w, h = (int(n) for n in nums[:4])
    return (x, y, w, h), ""


def shoot_mac(dest, app):
    if not app:
        return False, "--target mac 需要 --app <应用名>，如 --app \"微信开发者工具\""
    run(["osascript", "-e", f'tell application "{app}" to activate'])
    time.sleep(1.2)

    win, werr = mac_window_id(app)
    if win:                                   # 首选：按窗口 ID 截，遮挡也不影响
        r = run(["screencapture", "-x", "-o", "-l", win, str(dest)])
    else:                                     # 兜底：把应用切到最前，再截它的窗口区域
        front = run(["osascript", "-e",
                     'tell application "System Events" to get name of first process whose frontmost is true']).stdout.strip()
        if app.lower() not in front.lower() and front.lower() not in app.lower():
            return False, f"{werr}；且无法把「{app}」切到最前（当前最前是「{front}」）：手工点一下该窗口再重试"
        bounds, err = mac_window_bounds(app)
        if not bounds:
            return False, err
        x, y, w, h = bounds
        r = run(["screencapture", "-x", "-o", "-R", f"{x},{y},{w},{h}", str(dest)])
    if not (dest.exists() and dest.stat().st_size > 5000):
        return False, r.stderr.strip()[:120] or "截图为空"
    if looks_blank(dest):
        dest.unlink()
        return False, ("截出来是纯色图：macOS 缺「屏幕录制」权限。到 系统设置 › 隐私与安全性 › 屏幕录制 "
                       "勾选运行本脚本的程序（终端 / Claude），重启该程序后重试")
    return True, ""


def shoot(base_url, route, out_dir, idx, profile, size, wait_ms, full_page):
    url = base_url.rstrip("/") + route["path"]
    status = http_status(url)
    if status >= 400 or status == 0:
        # 服务端直接报错的路由不截：截了也只是一张 404 页，混进说明书更糟
        return {"module": route["module"], "url": url, "file": "", "ok": False, "size": 0,
                "err": f"HTTP {status or '连接失败'}，跳过（前端路由项目可忽略此项，改用 --routes 指定真实路径）"}
    name = f"{idx:02d}_{SAFE.sub('-', route['module'])[:24]}.png"
    dest = out_dir / name
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={size}", f"--virtual-time-budget={wait_ms}",
           f"--screenshot={dest}", url]
    if full_page:
        cmd.insert(1, "--screenshot-format=png")
    if profile:
        cmd.insert(1, f"--user-data-dir={profile}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    ok = dest.exists() and dest.stat().st_size > 5000      # 太小基本是白屏
    if ok and looks_blank(dest):
        ok, r.stderr = False, "页面是纯色（白屏/未渲染完）：调大 --wait，或确认该路由不需要登录"
    if not ok and dest.exists():
        dest.unlink()
    return {"module": route["module"], "url": url, "file": name if ok else "",
            "ok": ok, "size": dest.stat().st_size if ok else 0,
            "err": "" if ok else (r.stderr.strip().splitlines() or ["截图为空或过小，可能是白屏/路由不存在"])[-1][:120]}


def main():
    ap = argparse.ArgumentParser(description="按路由自动截图 Web 项目界面")
    ap.add_argument("--target", default="web",
                    choices=["web", "ios", "ios-device", "ios-mirror", "android", "mac", "miniprogram", "auto"],
                    help="截图来源端，默认 web；auto 自动挑可用的")
    ap.add_argument("--detect", action="store_true", help="只探测本机可用的截图端")
    ap.add_argument("--base-url", help="web 模式的项目地址，如 http://localhost:5173")
    ap.add_argument("--name", help="ios/android/mac 模式：这张截图对应的模块名")
    ap.add_argument("--app", help="mac 模式：应用名，如 微信开发者工具 / Electron 应用名")
    ap.add_argument("--spec", help="说明书素材.json，从中读取路由")
    ap.add_argument("--routes", nargs="*", default=[], help="手工指定路由，如 /login /house/list")
    ap.add_argument("--out", default="用户截图", help="截图输出目录")
    ap.add_argument("--profile", help="已登录的 Chrome profile 目录（需要登录的项目）")
    ap.add_argument("--login", action="store_true", help="打开有界面的 Chrome 供用户登录一次")
    ap.add_argument("--size", default="1440,900", help="窗口尺寸，默认 1440,900；移动端可用 390,844")
    ap.add_argument("--wait", type=int, default=4000, help="每页渲染等待毫秒，默认 4000")
    ap.add_argument("--max", type=int, default=15, help="最多截几页")
    args = ap.parse_args()

    if args.detect:
        print(f"{'端':<12}{'可用':<6}说明")
        for name, ok, note in detect(args.base_url):
            mark = "✓" if ok else ("?" if ok is None else "×")
            print(f"{name:<12}{mark:<6}{note}")
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = pick_auto(args.base_url) if args.target == "auto" else args.target
    if args.target == "auto":
        print(f"自动选择端：{target}")
    if target == "miniprogram":
        target, args.app = "mac", args.app or "微信开发者工具"

    if target != "web":
        name = SAFE.sub("-", args.name or "界面")[:24]
        dest = out_dir / f"{next_index(out_dir):02d}_{name}.png"
        fn = {"ios": lambda: shoot_ios(dest), "ios-device": lambda: shoot_ios_device(dest),
              "ios-mirror": lambda: shoot_ios_mirror(dest, args.app or "QuickTime Player"),
              "android": lambda: shoot_android(dest), "mac": lambda: shoot_mac(dest, args.app)}[target]
        ok, err = fn()
        if ok:
            print(f"✓ {dest}（{dest.stat().st_size // 1024} KB）")
            print(f"把界面点到下一页后再跑一次；全部截完执行：python3 screenshots.py --materials {out_dir.parent}")
        else:
            print(f"× 截图失败：{err}")
            sys.exit(1)
        return

    if not args.base_url:
        sys.exit("--target web 需要 --base-url")
    if not CHROME:
        sys.exit("找不到 Chrome：设置环境变量 RUANZHU_CHROME 指向 Chrome 可执行文件")
    profile = Path(args.profile).resolve() if args.profile else None
    if args.login:
        if not profile:
            sys.exit("--login 需要配合 --profile <目录>")
        login(args.base_url, profile)
        return

    if not wait_server(args.base_url):
        sys.exit(f"{args.base_url} 连不上：先把项目跑起来（npm run dev 之类），再执行本脚本")

    routes = [{"path": r if r.startswith("/") else "/" + r, "module": r.strip("/").split("/")[-1] or "首页"}
              for r in args.routes]
    if args.spec:
        routes += routes_from_spec(args.spec, args.max)
    if not routes:
        routes = [{"path": "/", "module": "首页"}]
    seen, uniq = set(), []
    for r in routes:
        if r["path"] not in seen:
            seen.add(r["path"])
            uniq.append(r)
    routes = uniq[: args.max]

    results = []
    for i, route in enumerate(routes, 1):
        res = shoot(args.base_url, route, out_dir, i, profile, args.size, args.wait, True)
        results.append(res)
        print(f"{'✓' if res['ok'] else '×'} {i:02d} {route['module']:<14} {res['url']}"
              + (f"  {res['err']}" if not res["ok"] else f"  {res['size'] // 1024} KB"))

    ok = sum(1 for r in results if r["ok"])
    (out_dir / "截图记录.json").write_text(json.dumps(
        {"base_url": args.base_url, "size": args.size, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n成功 {ok}/{len(results)} → {out_dir}")
    if ok < len(results):
        print("失败的多半是：路由需要登录（加 --profile）、前端路由未匹配、或页面渲染慢（调大 --wait）")
    print(f"下一步：python3 screenshots.py --materials {out_dir.parent} --spec <说明书素材.json>")


if __name__ == "__main__":
    main()
