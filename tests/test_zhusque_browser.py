import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zhusque_browser


NODE = shutil.which("node")
DRIVER = Path(zhusque_browser.__file__).with_name("zhusque-browser.js")


class BrowserDetectorTests(unittest.TestCase):
    def test_app_node_executable_takes_priority_and_legacy_is_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(zhusque_browser.os.environ, {"RUANZHU_NODE_EXECUTABLE": "/app/node", "RUANZHU_NODE": "/old/node"}):
                self.assertEqual(zhusque_browser.BrowserDetector(directory).node, "/app/node")
                self.assertEqual(zhusque_browser.BrowserDetector(directory, node="/explicit/node").node, "/explicit/node")
            with patch.dict(zhusque_browser.os.environ, {"RUANZHU_NODE": "/old/node"}, clear=True):
                self.assertEqual(zhusque_browser.BrowserDetector(directory).node, "/old/node")

    def test_short_text_does_not_start_browser(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen") as popen:
            detector = zhusque_browser.BrowserDetector(directory)
            with self.assertRaises(zhusque_browser.BrowserDetectionError) as error:
                detector.detect("短段落", "test")
            self.assertEqual(error.exception.reason, "unsupported")
            popen.assert_not_called()

    def test_text_is_sent_only_on_stdin_and_provenance_retained(self):
        result = {"status": "success", "labels_ratio": {"0": 0.7, "1": 0.1, "2": 0.2},
                  "segment_labels": [{"label": 2, "position": [0, 350]}], "channel": "web",
                  "evidence": {"ratio_source": "visible-segment-nonwhitespace-character-weighted"}}
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps(result), "")
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen", return_value=process) as popen:
            detector = zhusque_browser.BrowserDetector(directory, node="node")
            text = "不应出现在命令行的材料正文。" * 30
            returned = detector.detect(text, "../../private/request")
            command = popen.call_args.args[0]
            self.assertNotIn(text, " ".join(command))
            sent = json.loads(process.communicate.call_args.args[0])
            self.assertEqual(sent["text"], text)
            self.assertFalse(sent["force"])
            self.assertNotIn("/", sent["request_id"])
            self.assertEqual(returned["channel"], "web")
            self.assertEqual(returned["evidence"], result["evidence"])

    def test_captcha_error_is_not_a_success(self):
        process = Mock(returncode=2)
        process.communicate.return_value = (json.dumps({"status": "error", "reason": "captcha", "message": "需要验证码",
                                                       "evidence": {"screenshot": "local.png"}}), "")
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen", return_value=process):
            detector = zhusque_browser.BrowserDetector(directory, node="node")
            with self.assertRaises(zhusque_browser.BrowserDetectionError) as error:
                detector.detect("原文" * 200, "test")
            self.assertEqual(error.exception.reason, "captcha")
            self.assertEqual(error.exception.evidence["screenshot"], "local.png")

    def test_timeout_kills_driver_only(self):
        process = Mock(returncode=None)
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired("node", 10), ("", "")]
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen", return_value=process):
            with self.assertRaises(zhusque_browser.BrowserDetectionError) as error:
                zhusque_browser.BrowserDetector(directory, node="node").detect("原文" * 200, "test")
            self.assertEqual(error.exception.reason, "unavailable")
            process.kill.assert_called_once()

    def test_malformed_output_is_not_a_success(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("not json", "")
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen", return_value=process):
            with self.assertRaises(zhusque_browser.BrowserDetectionError):
                zhusque_browser.BrowserDetector(directory, node="node").detect("原文" * 200, "test")

    def test_missing_ratios_are_an_explicit_unsupported_error(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps({"status": "success", "channel": "web"}), "")
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen", return_value=process):
            with self.assertRaises(zhusque_browser.BrowserDetectionError) as error:
                zhusque_browser.BrowserDetector(directory, node="node").detect("原文" * 200, "test")
            self.assertEqual(error.exception.reason, "unsupported")

    def test_force_flag_is_forwarded_without_changing_default_interface(self):
        process = Mock(returncode=2)
        process.communicate.return_value = (json.dumps({"status": "error", "reason": "captcha"}), "")
        with tempfile.TemporaryDirectory() as directory, patch.object(zhusque_browser.subprocess, "Popen", return_value=process):
            with self.assertRaises(zhusque_browser.BrowserDetectionError):
                zhusque_browser.BrowserDetector(directory, node="node").detect("原文" * 200, "same-request", force=True)
            self.assertTrue(json.loads(process.communicate.call_args.args[0])["force"])


@unittest.skipUnless(NODE, "Node.js not installed")
class VisiblePageParserTests(unittest.TestCase):
    def run_parser(self, method, args):
        # Pure parsing tests: no browser launch or network requests.
        program = "const m=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{try{const p=JSON.parse(s);console.log(JSON.stringify(m[p.method](...p.args)))}catch(e){console.log(JSON.stringify({reason:e.reason,message:e.message}))}})"
        output = subprocess.run([NODE, "-e", program, str(DRIVER)], input=json.dumps({"method": method, "args": args}),
                                text=True, capture_output=True, check=True, timeout=10)
        return json.loads(output.stdout)

    def test_verified_classes_use_full_coverage_and_unicode_positions(self):
        result = self.run_parser("parseSegments", [[
            {"text": "甲😀", "className": "txt-segmentType-success"},
            {"text": "乙", "className": "txt-segmentType-danger"},
            {"text": "丙", "className": "txt-segmentType-warning"}], "甲😀\n乙 丙"])
        self.assertEqual(result["labels_ratio"], {"0": 0.5, "1": 0.25, "2": 0.25})
        self.assertEqual(result["segment_labels"][0]["position"], [0, 2])
        self.assertEqual(result["segment_labels"][2]["position"], [5, 1])

    def test_example_or_truncated_result_is_not_accepted(self):
        for text in ["另一份示例", "实际材料还有后半部分"]:
            result = self.run_parser("parseSegments", [[{"text": "实际材料", "className": "txt-segmentType-success"}], text])
            self.assertIsNone(result)

    def test_unknown_label_is_not_counted_as_human(self):
        result = self.run_parser("parseSegments", [[{"text": "原文", "className": "unknown"}], "原文"])
        self.assertEqual(result["reason"], "unsupported")

    def test_all_known_risk_results_are_preserved(self):
        result = self.run_parser("parseSegments", [[{"text": "原文", "className": "txt-segmentType-danger"}], "原文"])
        self.assertEqual(result["labels_ratio"], {"0": 0, "1": 1, "2": 0})

    def test_blockers_do_not_confuse_header_login_or_faq_with_errors(self):
        self.assertIsNone(self.run_parser("classifyBlocker", [{"buttonText": "立即检测(今日剩余3次)", "alerts": "本结果仅为辅助判断"}]))
        cases = [({"captchaVisible": True}, "captcha"), ({"buttonText": "立即检测(今日剩余0次)"}, "quota"),
                 ({"loginDialog": True}, "login"), ({"alerts": "检测文本长度需大于350字"}, "unsupported")]
        for state, reason in cases:
            self.assertEqual(self.run_parser("classifyBlocker", [state])["reason"], reason)

    def run_page_flow(self, states, followup=None, force=False, tamper_marker=False, fail_click=False):
        program = """
const {detectOnPage}=require(process.argv[1]); let raw='';
process.stdin.on('data', d=>raw+=d); process.stdin.on('end', async()=>{
  const config=JSON.parse(raw); let states=config.states, marker='', value='', clears=0, submissions=0, reads=0;
  const page={url:()=> 'https://matrix.tencent.com/ai-detect/',
    evaluate:async(fn,arg)=>{if(arg&&arg.attribute){marker=arg.value;return;}
      reads++; if(!states.length) throw new Error('missing fixture'); return {...states.shift(),submissionMarker:marker};},
    getByRole:(_role, options)=>options.name.test('Clear')
      ? {waitFor:async()=>{}, click:async()=>{clears++;}}
      : {click:async()=>{submissions++;if(config.fail_click) throw new Error('click timeout');}},
    getByPlaceholder:()=>({fill:async text=>{value=text;},inputValue:async()=>value})};
  const input={text:'原文',request_id:'task-123',material_dir:config.directory,profile_dir:config.directory+'/profile'};
  let result; try {result=await detectOnPage(page,input,Date.now()+3000);}
  catch(e){result={reason:e.reason,message:e.message};}
  const firstResult=result;
  if(config.followup){states=config.followup;if(config.tamper_marker) marker='another-document';
    try {result=await detectOnPage(page,{...input,force:config.force},Date.now()+3000);}
    catch(e){result={reason:e.reason,message:e.message};}}
  const fs=require('node:fs'), path=require('node:path');
  const evidence=path.join(config.directory,'朱雀复核','网页证据');
  const pendingFiles=fs.existsSync(evidence)?fs.readdirSync(evidence).filter(n=>n.startsWith('pending-')):[];
  console.log(JSON.stringify({result,firstResult,clears,submissions,reads,pendingFiles}));
});
"""
        with tempfile.TemporaryDirectory() as directory:
            config = {"states": states, "followup": followup, "force": force, "tamper_marker": tamper_marker,
                      "fail_click": fail_click, "directory": directory}
            output = subprocess.run([NODE, "-e", program, str(DRIVER)], input=json.dumps(config), text=True,
                                    capture_output=True, check=True, timeout=10)
        return json.loads(output.stdout)

    def state(self, remaining=1, label=None, alerts=""):
        segments = [] if label is None else [{"text": "原文", "className": "txt-segmentType-" + label}]
        return {"segments": segments, "buttonText": f"立即检测(今日剩余{remaining}次)", "alerts": alerts}

    def test_identical_preexisting_result_requires_new_submission(self):
        data = self.run_page_flow([self.state(label="success"), self.state(), self.state(label="danger")])
        self.assertEqual(data["clears"], 1)
        self.assertEqual(data["submissions"], 1)
        self.assertEqual(data["result"]["result"]["labels_ratio"]["1"], 1)
        self.assertEqual(data["result"]["result"]["delivery"], "new")

    def test_last_allowed_submission_waits_for_result_despite_zero_button(self):
        data = self.run_page_flow([self.state(), self.state(), self.state(0), self.state(0, label="danger")])
        self.assertEqual(data["reads"], 4)
        self.assertEqual(data["submissions"], 1)
        self.assertEqual(data["result"]["result"]["labels_ratio"]["1"], 1)

    def test_explicit_quota_error_after_submission_still_stops(self):
        data = self.run_page_flow([self.state(), self.state(), self.state(0, alerts="今日检测次数已用尽")])
        self.assertEqual(data["result"]["reason"], "quota")
        self.assertEqual(data["submissions"], 1)

    def test_no_remaining_quota_does_not_submit_or_reuse_old_result(self):
        data = self.run_page_flow([self.state(0, label="success")])
        self.assertEqual(data["result"]["reason"], "quota")
        self.assertEqual(data["submissions"], 0)

    def test_uncleared_old_result_blocks_submission(self):
        data = self.run_page_flow([self.state(label="success"), self.state(label="success")])
        self.assertEqual(data["result"]["reason"], "unsupported")
        self.assertEqual(data["submissions"], 0)

    def test_receipted_captcha_result_resumes_without_resubmission(self):
        captcha = {**self.state(0), "captchaVisible": True}
        data = self.run_page_flow([self.state(), self.state(), captcha], followup=[self.state(0, label="danger")])
        self.assertEqual(data["firstResult"]["reason"], "captcha")
        self.assertEqual(data["submissions"], 1)
        self.assertEqual(data["clears"], 1)
        self.assertEqual(data["result"]["result"]["delivery"], "resumed")
        self.assertEqual(data["pendingFiles"], [])

    def test_force_never_reuses_receipted_result(self):
        captcha = {**self.state(), "captchaVisible": True}
        data = self.run_page_flow([self.state(), self.state(), captcha],
                                 followup=[self.state(label="success"), self.state(), self.state(label="danger")], force=True)
        self.assertEqual(data["submissions"], 2)
        self.assertEqual(data["result"]["result"]["delivery"], "new")
        self.assertEqual(data["result"]["result"]["labels_ratio"]["1"], 1)

    def test_receipt_cannot_resume_another_or_reloaded_document(self):
        captcha = {**self.state(), "captchaVisible": True}
        data = self.run_page_flow([self.state(), self.state(), captcha],
                                 followup=[self.state(label="success")], tamper_marker=True)
        self.assertEqual(data["result"]["reason"], "unavailable")
        self.assertEqual(data["submissions"], 1)
        self.assertTrue(data["pendingFiles"])

    def test_receipt_still_rejects_demo_text_mismatch(self):
        captcha = {**self.state(), "captchaVisible": True}
        mismatched = {**self.state(label="success"), "captchaVisible": True,
                      "segments": [{"text": "公开示例而非待检测任务", "className": "txt-segmentType-success"}]}
        data = self.run_page_flow([self.state(), self.state(), captcha], followup=[mismatched])
        self.assertEqual(data["result"]["reason"], "captcha")
        self.assertEqual(data["submissions"], 1)
        self.assertTrue(data["pendingFiles"])

    def test_uncertain_click_does_not_automatically_submit_again(self):
        data = self.run_page_flow([self.state(), self.state()], followup=[self.state(label="success")], fail_click=True)
        self.assertEqual(data["result"]["reason"], "unavailable")
        self.assertEqual(data["submissions"], 1)
        self.assertTrue(data["pendingFiles"])

    def test_english_quota_and_error_messages(self):
        cases = [({"buttonText": "Detect now(0 left)"}, "quota"),
                 ({"alerts": "Daily detection limit reached"}, "quota"),
                 ({"alerts": "Please log in first"}, "login"),
                 ({"alerts": "Text length must be more than 350 characters"}, "unsupported"),
                 ({"alerts": "Network error"}, "unavailable")]
        for state, reason in cases:
            self.assertEqual(self.run_parser("classifyBlocker", [state])["reason"], reason)
        self.assertIsNone(self.run_parser("classifyBlocker", [{"buttonText": "Detect now(0 left)", "checkQuotaButton": False}]))

    def test_captcha_requires_visible_ancestor_and_intersection_with_viewport(self):
        program = """
const {snapshotDOM}=require(process.argv[1]);let raw='';process.stdin.on('data',d=>raw+=d);process.stdin.on('end',()=>{
 const cases=JSON.parse(raw), results=[];global.innerWidth=1200;global.innerHeight=800;
 for(const cfg of cases){
   const rect={left:0,top:cfg.top||0,width:300,height:150,right:300,bottom:(cfg.top||0)+150};
   const parent={style:{opacity:String(cfg.opacity),visibility:'visible',display:cfg.display||'block'},parentElement:null};
   const frame={style:{opacity:'1',visibility:'visible',display:'block'},parentElement:parent,getClientRects:()=>[rect],getBoundingClientRect:()=>rect};
   global.getComputedStyle=e=>e.style;
   global.document={documentElement:{getAttribute:()=>''},querySelector:()=>frame,querySelectorAll:()=>[]};
   results.push(snapshotDOM().captchaVisible);
 }
 console.log(JSON.stringify(results));
});
"""
        cases = [{"opacity": 0, "top": -1000000}, {"opacity": 1, "top": -1000000},
                 {"opacity": 1, "display": "none"}, {"opacity": 1, "top": 100}]
        output = subprocess.run([NODE, "-e", program, str(DRIVER)], input=json.dumps(cases), text=True,
                                capture_output=True, check=True, timeout=10)
        self.assertEqual(json.loads(output.stdout), [False, False, False, True])


if __name__ == "__main__":
    unittest.main()
