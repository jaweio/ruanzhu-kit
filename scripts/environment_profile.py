"""Resolve the six registration-form development/runtime environment fields.

Structured ``environment_profile`` entries are preferred because they keep
machine facts separate from prose. Legacy ``env`` strings remain supported as
overrides. Values that cannot be established from the project (especially
hardware and the OS actually used during development) are never fabricated.
"""

from pathlib import Path


FIELD_MAP = {
    "dev_hardware": ("development", "hardware"),
    "run_hardware": ("runtime", "hardware"),
    "dev_os": ("development", "operating_systems"),
    "dev_tools": ("development", "tools"),
    "run_os": ("runtime", "operating_systems"),
    "run_support": ("runtime", "support_software"),
}


def _items(value, sep="、"):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return sep.join(str(x).strip() for x in value if str(x).strip())
    return ""


def _hardware(value):
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    parts = []
    if value.get("recommended"):
        parts.append("建议配置")
    if value.get("cpu_cores"):
        cores = str(value["cpu_cores"]).strip()
        parts.append(f"CPU：{cores}核及以上" if cores.isdigit() else f"CPU：{cores}")
    if value.get("memory_gb"):
        memory = str(value["memory_gb"]).strip()
        parts.append(f"内存：{memory}GB" if memory.isdigit() else f"内存：{memory}")
    if value.get("disk_free_gb"):
        disk = str(value["disk_free_gb"]).strip()
        parts.append(f"磁盘：{disk}GB可用" if disk.isdigit() else f"磁盘：{disk}")
    if value.get("network"):
        parts.append(f"网络：{str(value['network']).strip()}")
    if value.get("storage_note"):
        parts.append(str(value["storage_note"]).strip())
    return "；".join(parts) + ("。" if parts else "")


def _infer_dev_tools(project, spec):
    """Infer only tool versions evidenced by project manifests."""
    # Never let an omitted ``spec.repo`` resolve to the current working
    # directory.  That would accidentally report the ruanzhu-kit repository's
    # own Git/Docker files as the applicant's development tools.
    raw_repo = (spec or {}).get("repo")
    if not raw_repo:
        return ""
    repo = Path(str(raw_repo))
    if not repo.is_dir():
        return ""
    tools = []
    go_mod = repo / "go.mod"
    if go_mod.is_file():
        for line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines()[:8]:
            if line.strip().startswith("go "):
                tools.append("Go " + line.strip().split(maxsplit=1)[1])
                break
    if (repo / ".git").exists():
        tools.append("Git")
    has_docker_files = any((repo / n).exists() for n in ("Dockerfile", "compose.yaml", "compose.yml", "docker-compose.yml"))
    if not has_docker_files:
        has_docker_files = next(repo.rglob("Dockerfile"), None) is not None
    if has_docker_files:
        tools.append("Docker")
    return "、".join(dict.fromkeys(tools))


def _infer_runtime_support(project):
    """Use configured project technology rows, never guess versions."""
    items = []
    for row in project.get("tech_stack", []) or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        category, component = str(row[0]).lower(), str(row[1]).strip()
        if any(word in category for word in ("服务语言", "关系数据库", "数据库", "缓存", "消息队列")):
            if component:
                items.append(component)
    return "、".join(dict.fromkeys(items))


def resolve_environment(project, cfg=None, spec=None):
    """Return (field values, provenance) for application form and manual use."""
    cfg = cfg or {}
    env = {**(cfg.get("env") or {}), **(project.get("env") or {})}
    profile = project.get("environment_profile") or {}
    sources = {}

    for key, (section, name) in FIELD_MAP.items():
        value = ""
        if section in profile and name in profile[section]:
            raw = profile[section][name]
            value = _hardware(raw) if name == "hardware" else _items(raw)
            if key == "run_support" and isinstance(profile.get("runtime", {}).get("deployment"), list):
                deploy = _items(profile["runtime"]["deployment"])
                if deploy:
                    value = "、".join(x for x in (value, deploy) if x)
            if value:
                sources[key] = f"projects[].environment_profile.{section}.{name}"
        if not value:
            value = str(env.get(key, "")).strip()
            if value:
                project_env = project.get("env") or {}
                sources[key] = f"projects[].env.{key}" if project_env.get(key) else f"env.{key}"
        env[key] = value

    if not env.get("dev_tools"):
        inferred = _infer_dev_tools(project, spec)
        if inferred:
            env["dev_tools"] = inferred
            sources["dev_tools"] = "project manifest (go.mod / .git / Docker files)"
    if not env.get("run_support"):
        inferred = _infer_runtime_support(project)
        if inferred:
            env["run_support"] = inferred
            sources["run_support"] = "projects[].tech_stack"
    return env, sources
