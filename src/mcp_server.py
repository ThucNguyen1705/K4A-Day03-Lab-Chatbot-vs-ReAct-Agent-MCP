"""
🔌 MODEL CONTEXT PROTOCOL (MCP) SERVER MODULE
Mô phỏng kiến trúc MCP Server (Client-Server Architecture) cung cấp công cụ chuẩn hóa.

📌 ĐỀ TÀI: Trợ lý Tuyển dụng & Sàng lọc CV (Gợi ý 4.1)

💡 Ý tưởng cốt lõi của MCP: tách NƠI THỰC THI công cụ khỏi NƠI SUY LUẬN.
   - MCP Server (file này) sở hữu & chạy tool, không biết gì về LLM.
   - MCP Client (src/app.py) chỉ suy luận, không biết tool chạy ra sao.
   Nhờ vậy đổi LLM không phải viết lại tool, và thêm tool không phải sửa adapter LLM.
"""

import json
import sys
from typing import Dict, Any, List
from tools import TOOLS_SCHEMA, dispatch_tool_call

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


class MCPRecruitmentServer:
    """
    Giả lập MCP Server tuân thủ chuẩn giao thức Model Context Protocol
    phục vụ nghiệp vụ Tuyển dụng & Sàng lọc CV.
    """

    def __init__(self, server_name: str = "vinhr-recruitment-mcp-server"):
        self.server_name = server_name
        self.version = "2026.1.0"
        self._request_id = 0

    def list_tools(self) -> List[Dict[str, Any]]:
        """Trả về danh sách các Tools chuẩn giao thức MCP"""
        return TOOLS_SCHEMA

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        [TASK 2.1 - ĐÃ HOÀN THIỆN] Thực thi request gọi Tool theo chuẩn MCP JSON-RPC 2.0

        Luồng xử lý:
          1. Gọi dispatch_tool_call() để lấy chuỗi JSON kết quả từ Tool Router.
          2. Chuyển chuỗi JSON đó thành Python Dictionary.
          3. Đóng gói vào "phong bì" JSON-RPC 2.0 rồi trả về.

        ⚠️ Phân tầng cần nhớ:
           - "jsonrpc" / "id" / "server" / "tool" là LỚP GIAO VẬN (phong bì).
           - "result" mới là NỘI DUNG do tool trả về (chính là Observation của Agent).
        """
        self._request_id += 1

        raw_result = dispatch_tool_call(tool_name, arguments)

        try:
            content = json.loads(raw_result)
        except (json.JSONDecodeError, TypeError) as e:
            content = {
                "status": "PARSE_ERROR",
                "error": f"Tool '{tool_name}' trả về dữ liệu không phải JSON hợp lệ: {e}",
                "raw": str(raw_result)
            }

        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "server": self.server_name,
            "tool": tool_name,
            "arguments": arguments,
            "result": content
        }


# Giữ alias để tương thích ngược với mã nguồn/tài liệu cũ của starter repo
MCPAcademicServer = MCPRecruitmentServer


if __name__ == "__main__":
    print("==========================================================")
    print("🔌 KIỂM THỬ ĐỘC LẬP MCP SERVER (vinhr-recruitment-mcp-server)")
    print("==========================================================")

    server = MCPRecruitmentServer()
    tools = server.list_tools()
    print(f"✅ [MCP SERVER] Đã khởi tạo thành công {server.server_name} (Version: {server.version})")
    print(f"📦 Số lượng Tools công bố qua MCP: {len(tools)}")
    for t in tools:
        req = ", ".join(t.get("parameters", {}).get("required", [])) or "—"
        print(f"   • {t['name']:<24} tham số bắt buộc: {req}")

    print("\n--- Kiểm tra trạng thái TODO 1.2 (Tool Schemas) ---")
    incomplete = [t["name"] for t in tools if not t.get("parameters", {}).get("properties")]
    if incomplete:
        print(f"⏳ [TODO 1.2]: Các tool sau chưa khai báo properties trong 'src/tools.py': {', '.join(incomplete)}")
    else:
        print("✅ [TODO 1.2]: Toàn bộ Tool Schemas đã khai báo đầy đủ properties & required.")

    print("\n--- Kiểm tra trạng thái TODO 2.1 (call_tool JSON-RPC) ---")
    test_result = server.call_tool("job_requirement_query", {"position_id": "AIE-01"})
    if not test_result or not test_result.get("result"):
        print("⏳ [TODO 2.1]: Hàm call_tool() đang trả về rỗng. Hãy hoàn thiện TODO 2.1!")
    else:
        print("✅ [TODO 2.1]: Test dispatch tool 'job_requirement_query' thành công.")
        print(f"   Phản hồi JSON-RPC: {json.dumps(test_result, ensure_ascii=False)[:220]} ...")

    print("\n--- Kiểm thử nhanh 3 Tools nghiệp vụ ---")
    demos = [
        ("cv_screening", {"candidate_id": "UV003", "position_id": "AIE-01"}),
        ("cv_screening", {"candidate_id": "UV002", "position_id": "AIE-01"}),
        ("send_interview_invite", {"candidate_id": "UV003", "interview_datetime": "09:00 22/09/2026", "mode": "online"}),
    ]
    for name, args in demos:
        res = server.call_tool(name, args)["result"]
        summary = res.get("verdict") or res.get("invite_id") or res.get("status")
        print(f"   • {name}({json.dumps(args, ensure_ascii=False)}) → {summary}")
