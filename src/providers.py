"""
🔌 MULTI-PROVIDER LLM ADAPTER (Google Gemini, OpenAI & Offline Mock)
Hỗ trợ Native Tool Calling + Multi-turn History và chuyển đổi linh hoạt qua biến môi trường LLM_PROVIDER.

💡 VÌ SAO CẦN THAM SỐ `history`:
   LLM API là STATELESS - mỗi lần gọi là một lần "gặp người lạ", nó không nhớ lượt trước.
   Muốn Agent suy luận ĐA BƯỚC thì client phải gửi lại toàn bộ lịch sử mỗi lượt:
      Vòng 1 gửi: [câu hỏi]
      Vòng 2 gửi: [câu hỏi] + [tool_call 1] + [observation 1]
      Vòng 3 gửi: [câu hỏi] + [tool_call 1] + [observation 1] + [tool_call 2] + [observation 2]
   Thiếu history -> mỗi vòng LLM đều nhận lại đúng câu hỏi gốc và gọi lại đúng tool cũ -> lặp vô hạn.

📦 ĐỊNH DẠNG HISTORY TRUNG LẬP (do src/app.py tạo, mỗi Provider tự dịch sang SDK của mình):
   {"role": "user",                "content": "..."}
   {"role": "assistant_text",      "content": "..."}
   {"role": "assistant_tool_call", "tool_name": "...", "arguments": {...}, "call_id": "..."}
   {"role": "tool_result",         "tool_name": "...", "content": {...},  "call_id": "..."}
"""

import os
import re
import sys
import json
import time
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()


# ==============================================================================
# 0. TIỆN ÍCH CHUNG
# ==============================================================================

def _warn_fallback(provider_name: str, detail: str) -> None:
    """In cảnh báo NỔI BẬT khi buộc phải rơi về Mock - tránh nộp bài nhầm chế độ"""
    print("")
    print("🚨 ============================ CẢNH BÁO NGHIỆM THU ============================ 🚨")
    print(f"🚨 [{provider_name}] KHÔNG kết nối được LLM API thật. ĐANG CHẠY MOCK OFFLINE!")
    print(f"🚨 Nguyên nhân: {detail}")
    print("🚨 Bài nộp chỉ chạy Mock sẽ bị trừ điểm Tiêu chí 2 & 3. Hãy kiểm tra lại .env!")
    print("🚨 ============================================================================= 🚨")
    print("")


def _parse_retry_delay(message: str) -> Optional[float]:
    """Đọc khoảng thời gian API yêu cầu chờ lại từ thông báo lỗi 429"""
    for pattern in (r"retryDelay'?\s*:\s*'?(\d+(?:\.\d+)?)s", r"retry in (\d+(?:\.\d+)?)s"):
        m = re.search(pattern, message)
        if m:
            return float(m.group(1))
    return None


def _clean_thought(text: str) -> str:
    """Bỏ phần mở đầu khuôn mẫu và ký tự markdown trong thought summary của model"""
    if not text:
        return ""
    lines = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("#").strip().strip("*").strip()
        if not line:
            continue
        # Bỏ câu dẫn khuôn mẫu kiểu "Here's my summary, as though I'm thinking these thoughts:"
        if re.match(r"^(here'?s|this is) my (summary|thought)", line, re.I):
            continue
        lines.append(line)
    return " ".join(lines)[:600].strip()


def _last_user_query(history: Optional[List[Dict[str, Any]]], fallback: str) -> str:
    """Lấy câu hỏi gốc của người dùng từ history"""
    if history:
        for m in history:
            if m.get("role") == "user":
                return m.get("content", fallback)
    return fallback


class BaseLLMProvider:
    """Interface cơ sở cho các LLM Provider hỗ trợ Native Tool Calling"""

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError

    def generate_with_tools(self,
                            prompt: str,
                            tools_schema: List[Dict[str, Any]],
                            system_prompt: str = "",
                            history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        raise NotImplementedError


# ==============================================================================
# 1. MOCK OFFLINE PROVIDER (chạy miễn phí, mô phỏng được suy luận ĐA BƯỚC)
# ==============================================================================

class MockOfflineProvider(BaseLLMProvider):
    """
    Offline Mock Provider dùng để gõ code & debug mà không tốn API Key.
    Mock này ĐỌC HISTORY để mô phỏng đúng chuỗi ReAct nhiều bước,
    nhờ vậy có thể kiểm thử toàn bộ luồng TC01 -> TC05 ở chế độ 0 đồng.
    """

    def __init__(self):
        self.model_name = "Offline-Mock-Model-2026"

    # ----- Chatbot Baseline (Cấp 2): không có tool -----
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return (
            "[Mock Chatbot Response]: Quy trình tuyển dụng thường gồm sàng lọc hồ sơ, phỏng vấn "
            "chuyên môn và phỏng vấn với quản lý tuyển dụng. Tuy nhiên tôi KHÔNG có công cụ tra cứu "
            "hệ thống ATS nên không thể cung cấp tiêu chí cụ thể của vị trí hay kết quả sàng lọc của "
            "ứng viên nào."
        )

    # ----- Bộ trích xuất thực thể đơn giản phục vụ mô phỏng -----
    @staticmethod
    def _extract_entities(text: str) -> Dict[str, Any]:
        candidate = re.search(r'\b(UV\d{3,4})\b', text, re.IGNORECASE)
        position = re.search(r'\b([A-Z]{3}-\d{2})\b', text, re.IGNORECASE)
        dt = re.search(r'(\d{1,2}:\d{2})\s*(?:ngày\s*)?(\d{1,2}/\d{1,2}/\d{4})', text)

        candidate_id = candidate.group(1).upper() if candidate else None
        position_id = position.group(1).upper() if position else None

        # Nếu chỉ nhắc tới ứng viên -> suy ra vị trí ứng tuyển từ hồ sơ ATS
        if candidate_id and not position_id:
            try:
                from tools import MOCK_CANDIDATES
                rec = MOCK_CANDIDATES.get(candidate_id)
                if rec:
                    position_id = rec.get("position_applied")
            except Exception:
                pass

        return {
            "candidate_id": candidate_id,
            "position_id": position_id,
            "datetime": f"{dt.group(1)} {dt.group(2)}" if dt else "09:00 22/09/2026",
            "mode": "onsite" if re.search(r'onsite|tại văn phòng|trực tiếp', text, re.I) else "online"
        }

    def generate_with_tools(self,
                            prompt: str,
                            tools_schema: List[Dict[str, Any]],
                            system_prompt: str = "",
                            history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        history = history or []
        query = _last_user_query(history, prompt)
        low = query.lower()

        ent = self._extract_entities(query)
        cid, pid = ent["candidate_id"], ent["position_id"]

        results = [m for m in history if m.get("role") == "tool_result"]
        done_tools = [m.get("tool_name") for m in results]
        contents = [m.get("content", {}) if isinstance(m.get("content"), dict) else {} for m in results]

        blocked = any(c.get("status") == "BLOCKED_BY_POLICY" for c in contents)
        passed = any(c.get("verdict") == "PASS" for c in contents)
        failed = any(c.get("verdict") == "FAIL" for c in contents)
        not_found = any(c.get("status") == "NOT_FOUND" for c in contents)
        invited = any(c.get("invite_id") for c in contents)

        wants_invite = bool(re.search(r'mời|thư mời|phỏng vấn|lịch pv|invite', low))
        wants_check = bool(re.search(r'kiểm tra|có đạt|sàng lọc|đánh giá|phù hợp|tiêu chí', low))

        # ---------- ĐÃ ĐỦ DỮ LIỆU -> KẾT LUẬN ----------
        if invited:
            inv = next(c for c in contents if c.get("invite_id"))
            scr = next((c for c in contents if c.get("verdict")), {})
            return self._final(
                f"{inv.get('candidate_name', cid)} đạt {scr.get('match_score', '—')}% tiêu chí "
                f"{scr.get('position_title', pid)}. Đã gửi thư mời {inv['invite_id']} tới "
                f"{inv.get('email_sent_to', '')} cho buổi phỏng vấn {inv.get('mode')} lúc "
                f"{inv.get('interview_datetime')}, người phỏng vấn: {inv.get('interviewer')}.",
                "Thư mời đã phát hành thành công, không cần gọi thêm công cụ nào."
            )

        if not_found:
            nf = next(c for c in contents if c.get("status") == "NOT_FOUND")
            return self._final(
                f"{nf.get('message', 'Không tìm thấy dữ liệu yêu cầu.')} "
                "Anh/chị vui lòng kiểm tra lại mã, hoặc cung cấp thông tin khác để tôi tra cứu.",
                "Công cụ trả về NOT_FOUND. Theo quy tắc chống bịa đặt, phải thừa nhận không có dữ liệu."
            )

        if failed:
            scr = next(c for c in contents if c.get("verdict") == "FAIL")
            return self._final(
                f"Ứng viên {scr.get('candidate_name', cid)} ({cid}) CHƯA đạt tiêu chí vị trí "
                f"{scr.get('position_title', pid)}, mức độ phù hợp {scr.get('match_score')}%. "
                f"Lý do: {scr.get('reason')}. Vì vậy tôi chưa gửi thư mời phỏng vấn.",
                "Kết quả sàng lọc là FAIL. Luật nghiệp vụ cấm gửi thư mời trong trường hợp này."
            )

        if passed and not wants_invite:
            scr = next(c for c in contents if c.get("verdict") == "PASS")
            return self._final(
                f"Ứng viên {scr.get('candidate_name', cid)} ({cid}) ĐẠT tiêu chí vị trí "
                f"{scr.get('position_title', pid)} với mức độ phù hợp {scr.get('match_score')}%. "
                f"Kỹ năng còn thiếu: {', '.join(scr.get('missing_skills') or ['không có'])}.",
                "Đã có kết quả sàng lọc PASS, người dùng không yêu cầu đặt lịch nên chỉ báo cáo kết quả."
            )

        # ---------- CÒN THIẾU DỮ LIỆU -> GỌI TOOL ----------
        if passed and wants_invite:
            return self._call("send_interview_invite", {
                "candidate_id": cid, "interview_datetime": ent["datetime"], "mode": ent["mode"]
            }, "Kết quả sàng lọc là PASS nên luật nghiệp vụ cho phép phát hành thư mời phỏng vấn.")

        if blocked or ("cv_screening" not in done_tools and "job_requirement_query" in done_tools and cid):
            return self._call("cv_screening", {"candidate_id": cid, "position_id": pid},
                              "Đã có tiêu chí vị trí, bước tiếp theo là đối chiếu hồ sơ ứng viên với tiêu chí đó.")

        if "job_requirement_query" in done_tools and not cid:
            jd = next((c.get("data", {}) for c in contents if c.get("data")), {})
            return self._final(
                f"Vị trí {jd.get('title', pid)} ({pid}) thuộc {jd.get('department', '')} yêu cầu tối thiểu "
                f"{jd.get('min_years_exp', '—')} năm kinh nghiệm. Kỹ năng bắt buộc: "
                f"{', '.join(jd.get('required_skills') or [])}. Ưu tiên thêm: "
                f"{', '.join(jd.get('preferred_skills') or ['không có'])}. "
                f"Học vấn: {jd.get('education', '')}. Dải lương {jd.get('salary_range', '')}, "
                f"cần tuyển {jd.get('headcount', '—')} người, quản lý tuyển dụng: {jd.get('hiring_manager', '')}.",
                "Đã nhận đủ tiêu chí vị trí từ MCP Server, tổng hợp lại cho người dùng."
            )

        if not results:
            # Yêu cầu gửi thư mời "thẳng" mà chưa qua sàng lọc -> cố tình thử để hàng rào chính sách chặn
            if wants_invite and not wants_check and cid:
                return self._call("send_interview_invite", {
                    "candidate_id": cid, "interview_datetime": ent["datetime"], "mode": ent["mode"]
                }, "Người dùng yêu cầu gửi thư mời phỏng vấn cho ứng viên này.")

            if cid or (pid and re.search(r'tiêu chí|yêu cầu|jd|tuyển dụng|vị trí', low)):
                return self._call(
                    "job_requirement_query", {"position_id": pid or "AIE-01"},
                    "Muốn biết ứng viên có đạt hay không thì phải biết tiêu chí của vị trí trước."
                    if cid else "Người dùng hỏi tiêu chí tuyển dụng, cần tra cứu JD của vị trí này từ hệ thống ATS."
                )

        # ---------- KHÔNG CẦN TOOL ----------
        return self._final(
            "Quy trình tuyển dụng tại công ty gồm 4 bước: sàng lọc hồ sơ theo tiêu chí vị trí, "
            "phỏng vấn chuyên môn, phỏng vấn với quản lý tuyển dụng, và thương lượng offer. "
            "Thời gian trung bình từ lúc nộp hồ sơ đến khi có kết quả là 2-3 tuần.",
            "Đây là câu hỏi kiến thức chung về quy trình, trả lời trực tiếp mà không cần gọi công cụ."
        )

    # ----- helper dựng phản hồi -----
    @staticmethod
    def _call(tool_name: str, arguments: Dict[str, Any], thought: str) -> Dict[str, Any]:
        return {"type": "tool_call", "tool_name": tool_name,
                "arguments": {k: v for k, v in arguments.items() if v is not None},
                "thought": thought}

    @staticmethod
    def _final(content: str, thought: str) -> Dict[str, Any]:
        return {"type": "text", "content": content, "thought": thought}


# ==============================================================================
# 2. GOOGLE GEMINI PROVIDER
# ==============================================================================

class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider (Native Tool Calling với Google GenAI SDK)"""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gemini-2.5-flash"

    def _has_key(self) -> bool:
        return bool(self.api_key) and self.api_key != "your_gemini_api_key_here"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self._has_key():
            return "[Gemini Error]: Chưa cấu hình GEMINI_API_KEY trong file .env!"
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(model=self.model_name, contents=contents)
            return response.text
        except Exception as e:
            return f"[Gemini Exception]: {str(e)}"

    @staticmethod
    def _build_contents(prompt: str, history: Optional[List[Dict[str, Any]]], types):
        """Dịch history trung lập -> định dạng `contents` của Gemini SDK.

        ⚠️ Gemini dùng role="model" cho lượt của trợ lý (OpenAI dùng "assistant"),
           và kết quả tool được gắn vào role="user" vì với model, môi trường bên
           ngoài đang "nói" với nó.
        """
        if not history:
            return prompt

        contents = []
        for m in history:
            role = m.get("role")
            if role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m.get("content", ""))]))
            elif role == "assistant_text":
                contents.append(types.Content(role="model", parts=[types.Part(text=m.get("content", ""))]))
            elif role == "assistant_tool_call":
                part = types.Part.from_function_call(name=m.get("tool_name", ""), args=m.get("arguments") or {})
                # ⚠️ Gemini 3.x BẮT BUỘC gửi kèm thought_signature của chính lượt function call đó
                #    khi phát lại lịch sử. Thiếu chữ ký -> API trả 400 INVALID_ARGUMENT.
                signature = m.get("signature")
                if signature:
                    try:
                        part.thought_signature = signature
                    except Exception:
                        pass
                contents.append(types.Content(role="model", parts=[part]))
            elif role == "tool_result":
                payload = m.get("content")
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=m.get("tool_name", ""), response={"result": payload})
                ]))
        return contents

    def _generate_with_retry(self, client, contents, config, max_attempts: int = 5):
        """Gọi Gemini API, tự chờ và thử lại khi dính giới hạn tốc độ (HTTP 429).

        Free tier của Gemini giới hạn khoảng 5 request/phút cho mỗi model, trong khi
        một lượt chạy `--all` cần hơn chục request. Không có retry thì Agent sẽ rơi
        về Mock giữa chừng và bài nộp mất điểm nghiệm thu.
        """
        delay = 5.0
        for attempt in range(1, max_attempts + 1):
            try:
                return client.models.generate_content(
                    model=self.model_name, contents=contents, config=config
                )
            except Exception as e:
                message = str(e)
                is_rate_limited = "429" in message or "RESOURCE_EXHAUSTED" in message
                if not is_rate_limited or attempt == max_attempts:
                    raise
                wait = (_parse_retry_delay(message) or delay) + 1.5
                print(f"⏳ [RATE LIMIT] Gemini free tier đang giới hạn tốc độ. "
                      f"Chờ {wait:.0f}s rồi thử lại (lần {attempt}/{max_attempts - 1})...")
                time.sleep(wait)
                delay = min(delay * 2, 60)

    @staticmethod
    def _parse_response(response):
        """Bóc tách 1 lượt phản hồi Gemini thành 4 phần.

        Trả về (reasoning, answer, function_call, thought_signature):
          - reasoning : văn bản suy luận model tự xuất ra (part.thought = True) -> dùng làm Thought THẬT
          - answer    : văn bản trả lời cho người dùng
          - function_call / thought_signature : lượt gọi tool đầu tiên và chữ ký kèm theo
        """
        reasoning, answer, call, signature = "", "", None, None  # noqa: E501
        try:
            parts = response.candidates[0].content.parts or []
        except Exception:
            parts = []

        for part in parts:
            text = getattr(part, "text", None)
            if text and text.strip():
                if getattr(part, "thought", False):
                    reasoning = f"{reasoning} {text.strip()}".strip()
                else:
                    answer = f"{answer} {text.strip()}".strip()

            fc = getattr(part, "function_call", None)
            if fc is not None and call is None:
                call = fc
                signature = getattr(part, "thought_signature", None)

        return _clean_thought(reasoning), answer, call, signature

    def generate_with_tools(self,
                            prompt: str,
                            tools_schema: List[Dict[str, Any]],
                            system_prompt: str = "",
                            history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not self._has_key():
            _warn_fallback("Gemini Provider", "Không tìm thấy GEMINI_API_KEY hợp lệ trong .env")
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt, history)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            function_declarations = []
            for tool in tools_schema:
                if not tool.get("name") or not tool.get("parameters", {}).get("properties"):
                    continue
                function_declarations.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {})
                })

            config = types.GenerateContentConfig(
                system_instruction=system_prompt if system_prompt else None,
                tools=[{"function_declarations": function_declarations}] if function_declarations else None,
                # Tắt AFC: vòng lặp ReAct do src/app.py điều phối, SDK không được tự chạy tool
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                # Yêu cầu model trả kèm phần suy luận -> Thought trong trace là THẬT,
                # không phải chuỗi f-string do code tự ghép
                thinking_config=types.ThinkingConfig(include_thoughts=True),
                temperature=0.2
            )

            response = self._generate_with_retry(
                client, self._build_contents(prompt, history, types), config
            )

            reasoning, answer, call, signature = self._parse_response(response)

            if call is not None:
                args = dict(call.args) if getattr(call, "args", None) else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.name,
                    "arguments": args,
                    "call_id": getattr(call, "id", None) or f"call_{len(history or [])}",
                    "thought_signature": signature,
                    "thought": (reasoning or answer
                                or f"Gọi công cụ '{call.name}' với tham số: {json.dumps(args, ensure_ascii=False)}")
                }

            return {
                "type": "text",
                "content": answer or (getattr(response, "text", "") or ""),
                "thought": reasoning or "Đã đủ dữ liệu để kết luận, không cần gọi thêm công cụ."
            }

        except Exception as e:
            _warn_fallback("Gemini Provider", str(e))
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt, history)


# ==============================================================================
# 3. OPENAI PROVIDER
# ==============================================================================

class OpenAIProvider(BaseLLMProvider):
    """OpenAI Provider (Native Tool Calling với OpenAI SDK)"""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    def _has_key(self) -> bool:
        return bool(self.api_key) and self.api_key != "your_openai_api_key_here"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self._has_key():
            return "[OpenAI Error]: Chưa cấu hình OPENAI_API_KEY trong file .env!"
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(model=self.model_name, messages=messages)
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[OpenAI Exception]: {str(e)}"

    @staticmethod
    def _build_messages(prompt: str, system_prompt: str, history: Optional[List[Dict[str, Any]]]):
        """Dịch history trung lập -> định dạng `messages` của OpenAI SDK"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if not history:
            messages.append({"role": "user", "content": prompt})
            return messages

        for m in history:
            role = m.get("role")
            if role == "user":
                messages.append({"role": "user", "content": m.get("content", "")})
            elif role == "assistant_text":
                messages.append({"role": "assistant", "content": m.get("content", "")})
            elif role == "assistant_tool_call":
                messages.append({
                    "role": "assistant",
                    "content": m.get("thought") or None,
                    "tool_calls": [{
                        "id": m.get("call_id") or "call_0",
                        "type": "function",
                        "function": {
                            "name": m.get("tool_name", ""),
                            "arguments": json.dumps(m.get("arguments") or {}, ensure_ascii=False)
                        }
                    }]
                })
            elif role == "tool_result":
                messages.append({
                    "role": "tool",
                    "tool_call_id": m.get("call_id") or "call_0",
                    "content": json.dumps(m.get("content"), ensure_ascii=False)
                })
        return messages

    def generate_with_tools(self,
                            prompt: str,
                            tools_schema: List[Dict[str, Any]],
                            system_prompt: str = "",
                            history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not self._has_key():
            _warn_fallback("OpenAI Provider", "Không tìm thấy OPENAI_API_KEY hợp lệ trong .env")
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt, history)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            tools = []
            for tool in tools_schema:
                if not tool.get("name") or not tool.get("parameters", {}).get("properties"):
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {})
                    }
                })

            response = client.chat.completions.create(
                model=self.model_name,
                messages=self._build_messages(prompt, system_prompt, history),
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=0.2
            )

            msg = response.choices[0].message
            reasoning = (msg.content or "").strip()

            if msg.tool_calls:
                call = msg.tool_calls[0]
                args = json.loads(call.function.arguments) if call.function.arguments else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.function.name,
                    "arguments": args,
                    "call_id": call.id,
                    "thought": reasoning or f"Gọi công cụ '{call.function.name}' với tham số: {json.dumps(args, ensure_ascii=False)}"
                }

            return {
                "type": "text",
                "content": reasoning,
                "thought": "Đã đủ dữ liệu để kết luận, không cần gọi thêm công cụ."
            }

        except Exception as e:
            _warn_fallback("OpenAI Provider", str(e))
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt, history)


# ==============================================================================
# 4. FACTORY
# ==============================================================================

def get_llm_provider() -> BaseLLMProvider:
    """Factory function khởi tạo Provider theo biến môi trường LLM_PROVIDER.

    ⚠️ Nếu người dùng CHỌN gemini/openai nhưng chưa điền API Key, factory buộc phải
       hạ xuống Mock. Trường hợp này PHẢI cảnh báo thật to, nếu không rất dễ nộp bài
       tưởng đang chạy LLM thật mà thực ra là Mock (mất điểm Tiêu chí 2 & 3).
    """
    provider_type = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider_type == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if key and key != "your_gemini_api_key_here":
            return GeminiProvider()
        _warn_fallback("Factory", "LLM_PROVIDER=gemini nhưng GEMINI_API_KEY trong .env vẫn là placeholder")
        return MockOfflineProvider()

    if provider_type == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if key and key != "your_openai_api_key_here":
            return OpenAIProvider()
        _warn_fallback("Factory", "LLM_PROVIDER=openai nhưng OPENAI_API_KEY trong .env vẫn là placeholder")
        return MockOfflineProvider()

    if provider_type != "mock":
        _warn_fallback("Factory", f"LLM_PROVIDER='{provider_type}' không được hỗ trợ (chỉ có gemini/openai/mock)")

    return MockOfflineProvider()
