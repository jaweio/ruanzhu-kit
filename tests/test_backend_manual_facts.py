"""Regression: generic backend projects must not inherit routes from other products."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_docs.py"
spec = importlib.util.spec_from_file_location("generate_docs_backend_facts", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_backend_sections_use_only_configured_facts():
    project = {
        "document_kind": "backend", "modules": [["任务规划", "POST /ai/coding/plans 返回提示"]],
        "module_playbooks": {"任务规划": {
            "steps": ["调用 POST /ai/coding/plans。"], "failure": "路径非法时返回 400。"
        }},
        "verification": [["能力查询", "GET /ai/coding/capabilities 返回 200"]],
        "configuration_overview": "端口由 server.port 配置。",
    }
    text = module.backend_module_sections(project)
    assert "/ai/coding/plans" in text and "路径非法时返回 400" in text
    assert "/api/issues" not in text
    assert module.backend_verification_rows(project) == project["verification"]
    assert module.backend_configuration_overview(project) == project["configuration_overview"]
    assert module.backend_first_check(project) == ""


def test_unconfigured_backend_omits_assumptions():
    project = {"document_kind": "backend", "modules": [["任务规划", "目标处理"]]}
    text = module.backend_module_sections(project)
    assert "操作步骤" not in text and "异常处理" not in text
    assert module.backend_verification_rows(project) == []
    assert module.backend_configuration_overview(project) == ""
    assert module.backend_extra_content("典型业务流程", "真实说明") == "真实说明"


def test_rights_modes_are_not_assumed():
    cfg = {}
    project = {"name": "软件", "short_name": "简称", "version": "V1.0", "summary": "真实描述"}
    doc = module.application_copy(project, cfg, None)
    assert "原始取得" not in doc and "独立开发" not in doc
    scoped = {"stats": {"source_lines": 140, "source_files": 4,
                        "note": "仅本轮新增的 AI 编程功能文件；全仓扫描含上游"}}
    assert "全仓代码包含上游文件" in module.spec_lines(scoped)


def test_scoped_source_lines_in_application_form():
    import importlib.util
    script = SCRIPT.with_name("application_form.py")
    spec = importlib.util.spec_from_file_location("application_form_scope", script)
    form_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(form_module)
    form = {"step2_basic": {"softwareName": "软件", "shortName": "简称", "version": "V1.0", "category": "应用软件", "copyrightHolder": "", "completionDate": "", "published": False},
            "step1_identity": {"acquireType": "", "developType": ""},
            "step3_dev": {"devHardware": "", "runHardware": "", "devOS": "", "devTools": "", "runOS": "", "runSupport": "", "language": "Java", "languageOther": "", "sourceLines": "140"},
            "step4_features": {"devPurpose": "", "targetIndustry": "", "techFeatureTag": "应用软件", "techFeatureText": "", "mainFunction": "", "programPdf": "", "docPdf": ""}}
    text = form_module.copy_md(form, [], {"name": "软件", "source_scope": "仅新功能四个文件"})
    assert "140 行（仅新功能四个文件）" in text
    assert "全项目源码行数" not in text


def test_registration_source_lines_include_owned_tests_only(tmp_path):
    script = SCRIPT.with_name("application_form.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("application_form_owned_scope", script)
    form_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(form_module)
    (tmp_path / "Main.java").write_text("class Main {}\n\n", encoding="utf-8")
    (tmp_path / "MainTest.java").write_text("class MainTest {}\n", encoding="utf-8")
    (tmp_path / "Upstream.java").write_text("class Upstream {}\n" * 50, encoding="utf-8")
    project = {"source_count_mode": "source_files", "source_files": ["Main.java", "MainTest.java"]}
    manual_spec = {"repo": str(tmp_path), "stats": {"source_lines": 2}}
    assert form_module.source_line_count(project, manual_spec) == "3"


def test_optional_deployment_is_not_registration_support_software():
    script = SCRIPT.with_name("environment_profile.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("environment_profile_runtime", script)
    env_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env_module)
    project = {"environment_profile": {"runtime": {
        "support_software": ["Java 25运行时"],
        "deployment": ["模型服务按需配置"],
    }}}
    values, _ = env_module.resolve_environment(project)
    assert values["run_support"] == "Java 25运行时"


def test_manual_environment_uses_all_six_registration_fields():
    project = {"environment_profile": {
        "development": {"hardware": "开发硬件", "operating_systems": ["开发系统"], "tools": ["开发工具值"]},
        "runtime": {"hardware": "运行硬件", "operating_systems": ["运行系统"], "support_software": ["运行软件"]},
    }, "document_kind": "backend"}
    hardware = module.hardware_section(project)
    software = module.environment_rows(project)
    assert "开发硬件环境" in hardware and "开发硬件" in hardware
    assert "运行硬件环境" in hardware and "运行硬件" in hardware
    assert software == [
        ["开发操作系统", "开发系统"], ["开发工具", "开发工具值"],
        ["运行操作系统", "运行系统"], ["运行支撑环境", "运行软件"],
    ]


def test_ai_api_routes_and_backend_hardware_do_not_inherit_another_product():
    assert module.manual_safe("POST /ai/coding/contexts/rank") == "POST /ai/coding/contexts/rank"
    project = {"document_kind": "backend", "env": {"dev_hardware": "14 CPU", "run_hardware": "14 CPU"}}
    text = module.hardware_section(project)
    assert "Go 服务编译" not in text and "Docker 构建" not in text
    assert "开发、构建和本地验证" in text
