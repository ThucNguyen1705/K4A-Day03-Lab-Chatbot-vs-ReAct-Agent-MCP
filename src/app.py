"""
🚀 CORE AGENT APPLICATION (DAY 03: CHATBOT VS REACT AGENT)
Thực thi so sánh giữa Chatbot Baseline (Cấp 2) và ReAct Agent kết nối MCP Server (Cấp 3).

📌 ĐỀ TÀI: Trợ lý Tuyển dụng & Sàng lọc CV (Gợi ý 4.1)

Các chế độ chạy:
    python src/app.py --all           Chạy toàn bộ bộ Test Cases nghiệm thu
    python src/app.py --interactive   Trò chuyện trực tiếp với Agent
    python src/app.py --compare       So sánh Chatbot Baseline vs ReAct Agent trên cùng câu hỏi
"""

import json
import os
import sys
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from mcp_server import MCPRecruitmentServer
from tools import MOCK_CANDIDATES
from prompts import (
    CHATBOT_BASELINE_PROMPT,
    REACT_AGENT_SYSTEM_PROMPT,
    MAX_ITERATIONS
)
from providers import get_llm_provider

load_dotenv()


# ==============================================================================
# TIỆN ÍCH CẤU HÌNH & GHI VẾT
# ==============================================================================

def load_test_cases():
    """Tải danh sách test cases từ config/test_cases.json hoặc config/test_cases.example.json"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "test_cases.json")
    if not os.path.exists(config_path):
        example_path = os.path.join(base_dir, "config", "test_cases.example.json")
        if os.path.exists(example_path):
            print("⚠️ [CONFIG NOTICE]: Chưa thấy file 'config/test_cases.json'. Đang dùng mẫu 'config/test_cases.example.json'.")
            print("👉 Hãy chạy: copy config/test_cases.example.json config/test_cases.json và viết test cases theo đề tài của bạn!\n")
            config_path = example_path
        else:
            config_path = "test_cases.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_waterfall_trace(trace_data: list):
    """Ghi vết log Waterfall Trace Log ra file docs/trace_waterfall.json"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(base_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    trace_path = os.path.join(docs_dir, "trace_waterfall.json")
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(trace_data, f, ensure_ascii=False, indent=2)
    print(f"📊 [OBSERVABILITY]: Đã lưu {len(trace_data)} sự kiện Waterfall Trace tại '{trace_path}'!")


def _short(obj, limit: int = 260) -> str:
    """Rút gọn JSON khi in ra terminal cho dễ đọc"""
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + " …"


# ==============================================================================
# HÀNG RÀO CỨNG TẦNG ORCHESTRATOR (POLICY GUARD)
# ==============================================================================

def _screening_passed(history: list, candidate_id: str) -> bool:
    """Kiểm tra trong lịch sử phiên đã có kết quả cv_screening = PASS cho ứng viên này chưa"""
    target = str(candidate_id or "").strip().upper()
    for msg in history:
        if msg.get("role") != "tool_result" or msg.get("tool_name") != "cv_screening":
            continue
        content = msg.get("content") or {}
        if not isinstance(content, dict):
            continue
        if content.get("verdict") == "PASS" and str(content.get("candidate_id", "")).upper() == target:
            return True
    return False


def _policy_block_payload(candidate_id: str) -> dict:
    """Observation trả về khi Agent cố gửi thư mời mà chưa qua sàng lọc.

    ⚠️ Prompt là hàng rào MỀM (LLM vẫn có xác suất bỏ qua), code là hàng rào CỨNG.
       Thông điệp được viết sao cho LLM đọc xong tự biết phải làm gì ở vòng sau.
    """
    cid = str(candidate_id or "").strip().upper()
    record = MOCK_CANDIDATES.get(cid)
    position = record.get("position_applied") if record else None

    hint = (f"Hãy chạy cv_screening cho ứng viên {cid} với vị trí {position} trước."
            if position else
            f"Hãy chạy cv_screening cho ứng viên {cid} với vị trí tương ứng trước.")

    return {
        "status": "BLOCKED_BY_POLICY",
        "candidate_id": cid,
        "message": (f"Từ chối gửi thư mời cho {cid}: chưa có kết quả sàng lọc verdict='PASS' "
                    f"trong phiên làm việc này. {hint}")
    }


# ==============================================================================
# CẤP 2 — CHATBOT BASELINE
# ==============================================================================

def run_baseline_chatbot(user_query: str, provider) -> str:
    """Chạy Chatbot gốc (Cấp 2) không có công cụ gọi Tool"""
    print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")
    response = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    print(f"🤖 Chatbot phản hồi:\n{response}")
    return response


# ==============================================================================
# CẤP 3 — REACT AGENT LOOP
# ==============================================================================

def run_react_agent(user_query: str, provider, mcp_server: MCPRecruitmentServer) -> list:
    """
    [REACT AGENT LOOP] Vòng lặp Thought -> Action -> Observation thật với MCP Server.

    Điểm mấu chốt: sau mỗi Observation, cả tool_call lẫn kết quả đều được NẠP NGƯỢC
    vào `history` rồi quay lại đầu vòng, để chính LLM đọc dữ liệu và tự quyết định
    bước kế tiếp — thay vì lập trình viên ghép câu trả lời bằng if/else.

    Trả về danh sách trace log của phiên thực thi.
    """
    print(f"\n🤖 [REACT AGENT] Câu hỏi: {user_query}")

    step = 0
    trace_logs = []
    tools_list = mcp_server.list_tools()
    history = [{"role": "user", "content": user_query}]

    while step < MAX_ITERATIONS:
        step += 1
        step_start_time = time.time()
        print(f"\n--- 🔄 Vòng lặp ReAct Loop (Step {step}/{MAX_ITERATIONS}) ---")

        # ---- Gọi LLM kèm toàn bộ lịch sử hội thoại (Native Tool Calling) ----
        llm_response = provider.generate_with_tools(
            user_query, tools_list, system_prompt=REACT_AGENT_SYSTEM_PROMPT, history=history
        ) or {}
        latency_ms = round((time.time() - step_start_time) * 1000, 2)

        thought = llm_response.get("thought", "Đang suy luận...")
        print(f"🧠 [Thought]: {thought}")

        # ---------- TRƯỜNG HỢP 1: LLM kết luận bằng văn bản ----------
        if llm_response.get("type") == "text":
            final_content = llm_response.get("content", "")
            print(f"🏁 [Final Answer]: {final_content}")
            trace_logs.append({
                "step": step,
                "query": user_query,
                "action_type": "FINAL_ANSWER",
                "thought": thought,
                "output": final_content,
                "latency_ms": latency_ms
            })
            history.append({"role": "assistant_text", "content": final_content})
            break

        # ---------- TRƯỜNG HỢP 2: LLM đề xuất gọi Tool ----------
        if llm_response.get("type") == "tool_call":
            tool_name = llm_response.get("tool_name")
            arguments = llm_response.get("arguments", {}) or {}
            call_id = llm_response.get("call_id") or f"call_{step}"

            print(f"🛠️ [Action Proposed]: {tool_name}({json.dumps(arguments, ensure_ascii=False)})")

            # --- HÀNG RÀO CỨNG: chặn tool có tác dụng phụ khi chưa đủ điều kiện ---
            if tool_name == "send_interview_invite" and not _screening_passed(history, arguments.get("candidate_id")):
                obs_data = _policy_block_payload(arguments.get("candidate_id"))
                print(f"🛡️ [POLICY BLOCK]: {obs_data['message']}")
                trace_logs.append({
                    "step": step,
                    "query": user_query,
                    "action_type": "POLICY_BLOCK",
                    "thought": thought,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "observation": obs_data,
                    "latency_ms": latency_ms
                })
            else:
                mcp_result = mcp_server.call_tool(tool_name, arguments)
                obs_data = mcp_result.get("result", {})
                print(f"👁️ [Observation từ MCP Server]: {_short(obs_data)}")
                trace_logs.append({
                    "step": step,
                    "query": user_query,
                    "action_type": "TOOL_EXECUTION",
                    "thought": thought,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "observation": obs_data,
                    "mcp_request_id": mcp_result.get("id"),
                    "latency_ms": latency_ms
                })

            # --- NẠP NGƯỢC vào lịch sử rồi QUAY LẠI ĐẦU VÒNG (không break) ---
            history.append({"role": "assistant_tool_call", "tool_name": tool_name,
                            "arguments": arguments, "call_id": call_id, "thought": thought})
            history.append({"role": "tool_result", "tool_name": tool_name,
                            "content": obs_data, "call_id": call_id})
            continue

        # ---------- TRƯỜNG HỢP 3: phản hồi không hợp lệ ----------
        print("⚠️ [LLM ERROR]: Phản hồi không đúng định dạng mong đợi, dừng vòng lặp.")
        trace_logs.append({
            "step": step,
            "query": user_query,
            "action_type": "INVALID_RESPONSE",
            "thought": thought,
            "output": _short(llm_response),
            "latency_ms": latency_ms
        })
        break

    else:
        # Vòng lặp chạm trần mà LLM chưa đưa ra kết luận -> ghi vết trung thực
        print(f"⏹️ [MAX ITERATIONS]: Đã chạm trần {MAX_ITERATIONS} vòng mà chưa có Final Answer.")
        trace_logs.append({
            "step": step,
            "query": user_query,
            "action_type": "MAX_ITERATIONS_REACHED",
            "thought": f"Đã thực hiện {MAX_ITERATIONS} vòng lặp nhưng chưa tổng hợp được câu trả lời cuối.",
            "output": "",
            "latency_ms": 0.0
        })

    return trace_logs


# ==============================================================================
# BÁO CÁO TỔNG KẾT
# ==============================================================================

def summarize(traces: list) -> dict:
    """Thống kê nhanh phục vụ điền báo cáo docs/trace_eval.md"""
    tool_calls = [t for t in traces if t["action_type"] == "TOOL_EXECUTION"]
    return {
        "events": len(traces),
        "tool_calls": len(tool_calls),
        "tools_used": sorted({t.get("tool_name") for t in tool_calls if t.get("tool_name")}),
        "policy_blocks": len([t for t in traces if t["action_type"] == "POLICY_BLOCK"]),
        "final_answers": len([t for t in traces if t["action_type"] == "FINAL_ANSWER"]),
        "avg_latency_ms": round(sum(t.get("latency_ms", 0) for t in traces) / len(traces), 2) if traces else 0.0
    }


# ==============================================================================
# ĐIỂM VÀO CHƯƠNG TRÌNH
# ==============================================================================

if __name__ == "__main__":
    print("==========================================================")
    print("🏢 VINUNI AI COURSE - DAY 03 LAB: CHATBOT VS REACT AGENT")
    print("📋 Đề tài: Trợ lý Tuyển dụng & Sàng lọc CV (Gợi ý 4.1)")
    print("==========================================================")

    provider = get_llm_provider()
    mcp_server = MCPRecruitmentServer()

    print(f"🔌 LLM Provider: {provider.__class__.__name__} ({getattr(provider, 'model_name', 'n/a')})")
    print(f"🌐 MCP Server: {mcp_server.server_name} | Tools: {len(mcp_server.list_tools())}\n")

    tests = load_test_cases()
    print(f"✅ Đã tải thành công {len(tests)} Test Cases thử nghiệm.\n")

    # ------------------------------------------------------------------ CHAT
    if "--interactive" in sys.argv:
        print("🎮 [INTERACTIVE MODE] Trò chuyện trực tiếp với ReAct Agent:")
        print("💡 Gợi ý câu hỏi thử nghiệm:")
        print("   - Câu hỏi chung:   'Quy trình tuyển dụng tại công ty gồm những vòng nào?'")
        print("   - Tra cứu JD:      'Cho tôi biết tiêu chí tuyển dụng của vị trí AIE-01'")
        print("   - Sàng lọc CV:     'Ứng viên UV002 có đạt vị trí AIE-01 không?'")
        print("   - Đa bước:         'UV003 ứng tuyển AIE-01, nếu đạt thì mời phỏng vấn 09:00 22/09/2026'")
        print("   - Gõ 'exit' hoặc 'quit' để kết thúc phiên trò chuyện.\n")
        session_traces = []
        while True:
            try:
                user_input = input("👤 HR hỏi: ").strip()
                if not user_input or user_input.lower() in ["exit", "quit"]:
                    print("👋 Tạm biệt! Kết thúc phiên trò chuyện.")
                    break
                logs = run_react_agent(user_input, provider, mcp_server)
                session_traces.extend(logs)
                save_waterfall_trace(session_traces)
            except (KeyboardInterrupt, EOFError):
                print("\n👋 Đã thoát phiên tương tác.")
                break

    # --------------------------------------------------------------- COMPARE
    elif "--compare" in sys.argv:
        print("⚖️ [COMPARE MODE] Cùng một câu hỏi, hai kiến trúc khác nhau:")
        queries = [
            "Cho tôi biết tiêu chí tuyển dụng của vị trí AIE-01.",
            "Ứng viên UV003 ứng tuyển vị trí AIE-01. Hãy kiểm tra hồ sơ có đạt tiêu chí không, "
            "nếu đạt thì gửi thư mời phỏng vấn lúc 09:00 ngày 22/09/2026."
        ]
        all_traces = []
        for q in queries:
            print("\n" + "=" * 62)
            print(f"❓ CÂU HỎI: {q}")
            print("=" * 62)
            print("\n──────── CẤP 2: CHATBOT BASELINE (không có Tool) ────────")
            run_baseline_chatbot(q, provider)
            print("\n──────── CẤP 3: REACT AGENT (MCP + Native Tool Calling) ────────")
            logs = run_react_agent(q, provider, mcp_server)
            all_traces.extend(logs)
            s = summarize(logs)
            print(f"\n📊 Agent dùng {s['tool_calls']} lượt gọi Tool: {', '.join(s['tools_used']) or '—'}")
        save_waterfall_trace(all_traces)

    # ------------------------------------------------------------- TEST SUITE
    elif "--all" in sys.argv:
        print(f"🚀 [TEST SUITE MODE] Kiểm tra {len(tests)} Test Cases:")
        completed_count = 0
        todo_count = 0
        all_traces = []

        for tc in tests:
            print(f"\n==================================================")
            print(f"🧪 [{tc['id']}] Loại test: {tc['type']} (Độ phức tạp: {tc['complexity']})")
            print(f"📌 Kỳ vọng: {tc['expected_behavior']}")

            if tc["question"].strip().startswith("TODO"):
                print(f"⏸️ [CHƯA KÍCH HOẠT - ĐANG LÀ TODO]:")
                print(f"   {tc['question']}")
                print(f"   👉 Hãy mở file 'config/test_cases.json' để viết câu hỏi thực tế cho Test Case này!")
                todo_count += 1
            else:
                logs = run_react_agent(tc["question"], provider, mcp_server)
                all_traces.extend(logs)
                completed_count += 1

        stats = summarize(all_traces)
        print(f"\n==================================================")
        print(f"📊 [KẾT QUẢ TEST SUITE]: Đã thực thi {completed_count}/{len(tests)} Test Cases "
              f"| {todo_count} Test Cases đang chờ điền câu hỏi (TODO)")
        print(f"   • Tổng sự kiện trace      : {stats['events']}")
        print(f"   • Lượt gọi Tool qua MCP   : {stats['tool_calls']}  ({', '.join(stats['tools_used']) or '—'})")
        print(f"   • Lượt bị chặn bởi chính sách: {stats['policy_blocks']}")
        print(f"   • Câu trả lời cuối (Final): {stats['final_answers']}")
        print(f"   • Độ trễ trung bình / bước: {stats['avg_latency_ms']} ms")
        if all_traces:
            save_waterfall_trace(all_traces)
        print(f"💡 So sánh Chatbot vs Agent: python src/app.py --compare")

    # ------------------------------------------------------------------ DEMO
    else:
        print("ℹ️ HƯỚNG DẪN SỬ DỤNG CHƯƠNG TRÌNH:")
        print("  1. Chạy toàn bộ Test Cases:     python src/app.py --all")
        print("  2. Chat trực tiếp liên tục:     python src/app.py --interactive")
        print("  3. So sánh Chatbot vs Agent:    python src/app.py --compare\n")

        sample_query = tests[3]["question"] if len(tests) > 3 else tests[-1]["question"]
        print(f"--- 🏁 DEMO CHẠY THỬ 1 TEST CASE MẪU (suy luận đa bước) ---")
        logs = run_react_agent(sample_query, provider, mcp_server)
        save_waterfall_trace(logs)
        print("\n💡 Hãy thử ngay lệnh: python src/app.py --all để chạy toàn bộ bộ kiểm thử!")
