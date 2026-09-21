#!/usr/bin/env python3
"""按演示数据方案调用项目本地 API，并提供可逆回滚。

这个脚本刻意不连接数据库，也不猜测项目接口。接口由用户在独立的
``演示数据接口.json`` 中显式配置。默认 ``apply`` 只预览请求；必须带
``--allow-write`` 才会真正发送写请求，并且默认只允许 localhost。
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
WRITE_METHODS = {"POST", "PUT", "PATCH"}
ROLLBACK_METHODS = {"DELETE", "POST", "PUT", "PATCH"}
TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def load_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON：{path}（{exc}）") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError(f"JSON 顶层必须是对象或数组：{path}")
    return value


def lookup(context, key):
    current = context
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""
    return current


def render(value, context):
    """递归替换模板；整值占位符保留数字/布尔类型。"""
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    if not isinstance(value, str):
        return value
    match = TOKEN.fullmatch(value.strip())
    if match:
        return lookup(context, match.group(1))
    return TOKEN.sub(lambda m: str(lookup(context, m.group(1))), value)


def host_allowed(base_url, allow_nonlocal=False):
    parsed = urllib.parse.urlparse(base_url)
    return parsed.scheme in {"http", "https"} and (
        allow_nonlocal or parsed.hostname in LOCAL_HOSTS
    )


def join_url(base_url, path):
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"接口 path 必须以 / 开头：{path!r}")
    return base_url.rstrip("/") + path


def extract(value, path):
    if not path:
        return None
    current = value
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def read_headers(config):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    for key, env_name in (config.get("headers_env") or {}).items():
        if not isinstance(key, str) or not isinstance(env_name, str):
            continue
        value = os.environ.get(env_name)
        if value:
            headers[key] = value
    for key, value in (config.get("headers") or {}).items():
        # 允许固定的本地开发头，但不把密钥写进回滚记录或输出。
        if isinstance(key, str) and isinstance(value, str):
            headers[key] = value
    return headers


def request_once(url, method, headers, payload=None, timeout=20):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw
            return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, body


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("接口配置顶层必须是对象")
    base_url = str(config.get("base_url", "")).strip()
    if not base_url:
        raise ValueError("接口配置缺少 base_url")
    requests = config.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("接口配置需要非空 requests 数组")
    for index, item in enumerate(requests, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个接口项必须是对象")
        method = str(item.get("method", "POST")).upper()
        if method not in WRITE_METHODS:
            raise ValueError(f"第 {index} 个接口只允许 POST/PUT/PATCH：{method}")
        if not str(item.get("path", "")).startswith("/"):
            raise ValueError(f"第 {index} 个接口 path 必须以 / 开头")
        rollback = item.get("rollback")
        if rollback:
            rollback_method = str(rollback.get("method", "DELETE")).upper()
            if rollback_method not in ROLLBACK_METHODS:
                raise ValueError(f"第 {index} 个回滚 method 不受支持：{rollback_method}")
            if not str(rollback.get("path", "")).startswith("/"):
                raise ValueError(f"第 {index} 个回滚 path 必须以 / 开头")


def make_context(record, project):
    values = dict(record.get("values") or {})
    values.update({"record_no": record.get("record_no"), "project": project})
    return values


def load_records(plan):
    records = plan.get("records") if isinstance(plan, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("演示数据方案缺少 records")
    return records


def apply_plan(plan, config, allow_write=False, allow_nonlocal=False, rollback_file=None):
    validate_config(config)
    base_url = str(config["base_url"]).strip()
    if not host_allowed(base_url, allow_nonlocal):
        raise ValueError("默认只允许 localhost/127.0.0.1/::1；跨主机写入需显式 --allow-nonlocal")
    headers = read_headers(config)
    records = load_records(plan)
    dry_run = not allow_write
    actions = []
    for record in records:
        context = make_context(record, plan.get("project", "业务项目"))
        for item in config["requests"]:
            method = str(item.get("method", "POST")).upper()
            url = join_url(base_url, render(item["path"], context))
            payload = render(item.get("payload", {}), context)
            action = {"record_no": record.get("record_no"), "name": item.get("name", "未命名接口"),
                      "method": method, "url": url, "status": "preview" if dry_run else "pending"}
            if dry_run:
                print(f"[预览] {method} {url} 记录={record.get('record_no')}")
                actions.append(action)
                continue
            status, body = request_once(url, method, headers, payload)
            action["http_status"] = status
            action["status"] = "ok" if 200 <= status < 300 else "failed"
            print(f"[写入] {method} {url} -> HTTP {status}")
            if not 200 <= status < 300:
                # 先落盘已成功请求的回滚动作，避免后续接口失败时前面的本地数据失去撤销入口。
                if rollback_file and actions:
                    path = Path(rollback_file).expanduser()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"base_url": base_url, "actions": actions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print(f"已保存部分回滚记录：{path}")
                raise RuntimeError(f"接口写入失败：{item.get('name', url)} HTTP {status}")
            rollback = item.get("rollback")
            if rollback:
                rollback_context = dict(context)
                rollback_context["id"] = extract(body, item.get("id_path", ""))
                rollback_context["response"] = body
                rollback_url = join_url(base_url, render(rollback["path"], rollback_context))
                actions.append({"record_no": record.get("record_no"), "name": item.get("name", "未命名接口"),
                                "method": str(rollback.get("method", "DELETE")).upper(),
                                "url": rollback_url, "payload": render(rollback.get("payload"), rollback_context),
                                "status": "rollback_pending"})
    if rollback_file and allow_write and actions:
        path = Path(rollback_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"base_url": base_url, "actions": actions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已保存回滚记录：{path}")
    return actions


def rollback(rollback_path, config, allow_write=False, allow_nonlocal=False):
    if not allow_write:
        raise ValueError("回滚会写入本地接口，必须显式提供 --allow-write")
    data = load_json(rollback_path)
    validate_config(config)
    base_url = str(data.get("base_url") or config.get("base_url") or "").strip()
    if not host_allowed(base_url, allow_nonlocal):
        raise ValueError("默认只允许回滚 localhost/127.0.0.1/::1；跨主机需显式 --allow-nonlocal")
    headers = read_headers(config)
    actions = data.get("actions") or []
    for action in reversed(actions):
        method = str(action.get("method", "DELETE")).upper()
        url = str(action.get("url", ""))
        if method not in ROLLBACK_METHODS or not url:
            continue
        status, _ = request_once(url, method, headers, action.get("payload"))
        print(f"[回滚] {method} {url} -> HTTP {status}")
        if not 200 <= status < 300 and status != 404:
            raise RuntimeError(f"回滚失败：{url} HTTP {status}")


def main():
    parser = argparse.ArgumentParser(description="执行或回滚软著合成演示数据（默认仅预览）")
    sub = parser.add_subparsers(dest="command", required=True)
    apply_parser = sub.add_parser("apply", help="按接口配置创建记录")
    apply_parser.add_argument("--plan", required=True, help="演示数据方案 JSON")
    apply_parser.add_argument("--config", required=True, help="演示数据接口 JSON")
    apply_parser.add_argument("--allow-write", action="store_true", help="真正写入本地 API")
    apply_parser.add_argument("--allow-nonlocal", action="store_true", help="允许非本机地址（不建议）")
    apply_parser.add_argument("--rollback-file", help="回滚记录路径")
    rollback_parser = sub.add_parser("rollback", help="按回滚记录逆序删除/撤销")
    rollback_parser.add_argument("--rollback-file", required=True, help="apply 生成的回滚记录")
    rollback_parser.add_argument("--config", required=True, help="演示数据接口 JSON")
    rollback_parser.add_argument("--allow-write", action="store_true", help="真正调用回滚接口")
    rollback_parser.add_argument("--allow-nonlocal", action="store_true", help="允许非本机地址（不建议）")
    args = parser.parse_args()
    try:
        config = load_json(args.config)
        if args.command == "apply":
            plan = load_json(args.plan)
            rollback_file = args.rollback_file or str(Path(args.plan).with_name("演示数据回滚.json"))
            apply_plan(plan, config, args.allow_write, args.allow_nonlocal, rollback_file)
            if not args.allow_write:
                print("仅预览，未写入；如确认接口与本地环境无误，再添加 --allow-write。")
        else:
            rollback(args.rollback_file, config, args.allow_write, args.allow_nonlocal)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
