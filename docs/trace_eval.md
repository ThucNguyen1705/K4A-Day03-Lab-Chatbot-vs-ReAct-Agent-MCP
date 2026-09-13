# 📊 BÁO CÁO THU HOẠCH NGHIỆM THU BÀI LAB 3 (BƯỚC 3 — SUBMISSION ARTIFACT)

> **Họ và Tên Học viên:** [Điền Họ và Tên]
> **Mã Sinh Viên / Mã Học viên:** [Điền MSSV]
> **Chủ đề Lựa chọn:** Gợi ý 4.1 — **Trợ lý Tuyển dụng & Sàng lọc CV** *(tra cứu tiêu chí tuyển dụng vị trí và gửi thông báo lịch phỏng vấn)*

---

## 0. TÓM TẮT HỆ THỐNG ĐÃ XÂY DỰNG

| Hạng mục | Nội dung |
| :--- | :--- |
| **MCP Server** | `vinhr-recruitment-mcp-server` v2026.1.0 — công bố **3 Tools** qua JSON-RPC 2.0 |
| **Tool 1 — READ** | `job_requirement_query(position_id)` — tra tiêu chí tuyển dụng (JD) của vị trí |
| **Tool 2 — COMPUTE** | `cv_screening(candidate_id, position_id)` — chấm CV, trả `match_score` + `verdict` |
| **Tool 3 — WRITE** | `send_interview_invite(candidate_id, interview_datetime, interviewer?, mode?)` — gửi thư mời |
| **Công thức sàng lọc** | `match_score = số kỹ năng khớp / số kỹ năng yêu cầu`; kết luận `PASS` khi `match_score ≥ 70%` **VÀ** `years_exp ≥ min_years_exp` |
| **Vòng lặp ReAct** | Đa bước thật — Observation được **nạp ngược** vào `history` rồi gửi lại LLM (`MAX_ITERATIONS = 8`) |
| **Hàng rào an toàn** | 2 tầng: luật 7–9 trong System Prompt (mềm) + policy guard trong `app.py` (cứng) |

**Dữ liệu ATS mô phỏng** *(gài có chủ đích để tạo đủ các nhánh rẽ)*:

| Mã | Họ tên | Kinh nghiệm | Kỹ năng khớp AIE-01 | Kết quả |
| :-- | :--- | :--: | :--: | :--- |
| `UV001` | Nguyễn Hoàng Nam | 3 năm | 4/4 | `PASS` — 100% |
| `UV002` | Lê Thị Bình | 1 năm | 1/4 | `FAIL` — 25%, trượt cả 2 điều kiện |
| `UV003` | Trần Minh Khoa | 2 năm | 3/4 | `PASS` — 75%, sát ngưỡng, thiếu MLOps |
| `UV9999` | *(không tồn tại)* | — | — | `NOT_FOUND` |

---

## 1. BẢNG CHẤM ĐIỂM AGENTIC FIT SCORING MATRIX (ĐÁNH GIÁ CHỦ ĐỀ)

| Tiêu chí Đánh giá | Mức độ (1 - 5) | Giải trình chi tiết lý do chọn điểm |
| :--- | :---: | :--- |
| **1. Multi-step Reasoning** | **5** / 5 | Bắt buộc chia bước nối tiếp: phải biết JD yêu cầu gì (`job_requirement_query`) **trước khi** chấm được CV (`cv_screening`), rồi mới quyết định có gửi thư mời hay không. Ba bước phụ thuộc nhau, không thể chạy song song. TC04 sinh chuỗi 3 tool call liên tiếp. |
| **2. Tool Interaction** | **5** / 5 | Toàn bộ tiêu chí JD và hồ sơ ứng viên nằm trong hệ ATS nội bộ — LLM không có cách nào tự biết. Không có tool thì Chatbot buộc phải bịa (đã chứng minh trực tiếp ở chế độ `--compare`). |
| **3. Dynamic Decision** | **5** / 5 | Đường đi do **dữ liệu quan sát** quyết định chứ không do code định trước: `verdict=PASS` → gửi thư mời (TC04, 4 vòng); `verdict=FAIL` → dừng và từ chối lịch sự (TC05, 3 vòng); `NOT_FOUND` → thừa nhận không có dữ liệu (TC06, 3 vòng). Cùng một dòng code, ba nhánh khác nhau. |
| **4. Long Horizon Goal** | **3** / 5 | Agent giữ được mục tiêu xuyên suốt trong một phiên (TC03: bị chặn ở vòng 1 nhưng vẫn quay lại hoàn thành mục tiêu ở vòng 3). Tuy nhiên hệ thống **chưa có Memory bền vững** giữa các phiên — đó là đặc trưng Cấp độ 4 (Autonomous Agent), nằm ngoài phạm vi bài lab. |
| **TỔNG ĐIỂM AGENTIC FIT** | **18 / 20** | *Vượt xa ngưỡng 12/20 → bài toán rất phù hợp triển khai Agentic System.* |

### 1.1. Vì sao chọn 3 Tools thay vì 2 như gợi ý đề bài

Đề bài yêu cầu tối thiểu 2 công cụ (1 tra cứu + 1 hành động). Nếu chỉ có `job_requirement_query` → `send_interview_invite`, Agent sẽ chạy **một đường thẳng cố định** — đó là *workflow*, không phải *agentic*. Thêm `cv_screening` vào giữa tạo ra **nhánh rẽ do dữ liệu quyết định**, chính là điều kiện đủ của tiêu chí Dynamic Decision.

---

## 2. TRÍCH XUẤT KẾT QUẢ WATERFALL TRACE LOG

> ⚠️ **YÊU CẦU NGHIỆM THU:** Mở tệp `.env` điền `GEMINI_API_KEY` (hoặc `OPENAI_API_KEY`) để kết nối LLM thật trước khi thực thi `python src/app.py --all`.
>
> 🟡 **ĐÃ CHẠY TRÊN GEMINI THẬT NHƯNG CHƯA SẠCH — cần chạy lại 1 lượt nữa.**
>
> Lượt chạy ngày 14/09/2026 với `GeminiProvider (gemini-3.6-flash)` hoàn tất 6/6 test case, nhưng **8 lượt gọi LLM cuối bị cạn quota** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, giới hạn **20 request/ngày**) nên tự động rơi về `MockOfflineProvider`. Vì vậy `docs/trace_waterfall.json` hiện là **hỗn hợp** Gemini thật + Mock.
>
> **Việc cần làm khi quota reset (00:00 giờ Thái Bình Dương):** chạy lại `python src/app.py --all`, xác nhận terminal in `🔌 LLM Provider: GeminiProvider` và **không** xuất hiện khối `🚨 CẢNH BÁO NGHIỆM THU` lần nào, rồi thay đoạn JSON bên dưới bằng nội dung mới.
>
> *Nếu quota 20 request/ngày vẫn không đủ:* đổi `LLM_MODEL` trong `.env` sang model có hạn mức cao hơn (ví dụ `gemini-2.5-flash-lite`), hoặc bật billing cho project.

### 2.1. TC04 — Chuỗi suy luận ReAct đa bước (3 Tool Call phụ thuộc nhau)

Câu hỏi: *"Ứng viên UV003 ứng tuyển vị trí AIE-01. Hãy kiểm tra hồ sơ có đạt tiêu chí không, nếu đạt thì gửi thư mời phỏng vấn lúc 09:00 ngày 22/09/2026."*

```json
[
  {
    "step": 1,
    "action_type": "TOOL_EXECUTION",
    "thought": "Muốn biết ứng viên có đạt hay không thì phải biết tiêu chí của vị trí trước.",
    "tool_name": "job_requirement_query",
    "arguments": { "position_id": "AIE-01" },
    "observation": {
      "status": "SUCCESS",
      "data": {
        "title": "AI Engineer",
        "min_years_exp": 2,
        "required_skills": ["Python", "PyTorch", "NLP", "MLOps"],
        "hiring_manager": "Trần Quốc Huy"
      }
    },
    "mcp_request_id": 4,
    "latency_ms": 0.11
  },
  {
    "step": 2,
    "action_type": "TOOL_EXECUTION",
    "thought": "Đã có tiêu chí vị trí, bước tiếp theo là đối chiếu hồ sơ ứng viên với tiêu chí đó.",
    "tool_name": "cv_screening",
    "arguments": { "candidate_id": "UV003", "position_id": "AIE-01" },
    "observation": {
      "status": "SUCCESS",
      "candidate_name": "Trần Minh Khoa",
      "verdict": "PASS",
      "match_score": 75,
      "years_exp": 2,
      "matched_skills": ["Python", "PyTorch", "NLP"],
      "missing_skills": ["MLOps"]
    },
    "mcp_request_id": 5,
    "latency_ms": 0.09
  },
  {
    "step": 3,
    "action_type": "TOOL_EXECUTION",
    "thought": "Kết quả sàng lọc là PASS nên luật nghiệp vụ cho phép phát hành thư mời phỏng vấn.",
    "tool_name": "send_interview_invite",
    "arguments": {
      "candidate_id": "UV003",
      "interview_datetime": "09:00 22/09/2026",
      "mode": "online"
    },
    "observation": {
      "status": "SUCCESS",
      "invite_id": "INV-UV003-02",
      "email_sent_to": "khoa.tm@email.com",
      "interviewer": "Trần Quốc Huy"
    },
    "mcp_request_id": 6,
    "latency_ms": 0.08
  },
  {
    "step": 4,
    "action_type": "FINAL_ANSWER",
    "thought": "Thư mời đã phát hành thành công, không cần gọi thêm công cụ nào.",
    "output": "Trần Minh Khoa đạt 75% tiêu chí AI Engineer. Đã gửi thư mời INV-UV003-02 tới khoa.tm@email.com cho buổi phỏng vấn online lúc 09:00 22/09/2026, người phỏng vấn: Trần Quốc Huy.",
    "latency_ms": 0.06
  }
]
```

**Nhận xét:** tham số `"candidate_id": "UV003"` cùng quyết định gọi `send_interview_invite` ở step 3 chỉ xuất hiện được vì Agent đã **đọc** Observation của step 2. Nếu Observation không được nạp ngược vào `history`, step 3 không thể tồn tại.

### 2.2. TC03 — Hàng rào chính sách chặn và Agent tự sửa sai

Câu hỏi: *"Gửi thư mời phỏng vấn cho ứng viên UV001 lúc 14:00 ngày 20/09/2026, hình thức online."* — người dùng yêu cầu gửi thẳng, bỏ qua bước sàng lọc.

```json
[
  {
    "step": 1,
    "action_type": "POLICY_BLOCK",
    "tool_name": "send_interview_invite",
    "arguments": { "candidate_id": "UV001", "interview_datetime": "14:00 20/09/2026", "mode": "online" },
    "observation": {
      "status": "BLOCKED_BY_POLICY",
      "candidate_id": "UV001",
      "message": "Từ chối gửi thư mời cho UV001: chưa có kết quả sàng lọc verdict='PASS' trong phiên làm việc này. Hãy chạy cv_screening cho ứng viên UV001 với vị trí AIE-01 trước."
    },
    "latency_ms": 0.13
  },
  {
    "step": 2, "action_type": "TOOL_EXECUTION", "tool_name": "cv_screening",
    "observation": { "verdict": "PASS", "match_score": 100 }
  },
  {
    "step": 3, "action_type": "TOOL_EXECUTION", "tool_name": "send_interview_invite",
    "observation": { "status": "SUCCESS", "invite_id": "INV-UV001-01" }
  },
  {
    "step": 4, "action_type": "FINAL_ANSWER",
    "output": "Nguyễn Hoàng Nam đạt 100% tiêu chí AI Engineer. Đã gửi thư mời INV-UV001-01 ..."
  }
]
```

**Nhận xét:** đây là bằng chứng rõ nhất cho giá trị của việc nạp Observation ngược lại — Agent **đọc được lý do bị chặn** và tự điều chỉnh hành vi ở vòng sau, thay vì bế tắc hoặc lặp lại sai lầm.

### 2.3. Bảng tổng hợp hình dạng trace của 6 Test Cases

| TC | Loại | Số sự kiện | Chuỗi hành động |
| :-- | :--- | :--: | :--- |
| TC01 | `direct_query` | 1 | `FINAL_ANSWER` *(0 tool — đúng kỳ vọng)* |
| TC02 | `single_tool_query` | 2 | `job_requirement_query` → `FINAL_ANSWER` |
| TC03 | `appointment_booking` | 4 | **`POLICY_BLOCK`** → `cv_screening` → `send_interview_invite` → `FINAL_ANSWER` |
| TC04 | `multi_step_reasoning` | 4 | `job_requirement_query` → `cv_screening` → `send_interview_invite` → `FINAL_ANSWER` |
| TC05 | `edge_case_handling` | 3 | `job_requirement_query` → `cv_screening` **(FAIL)** → `FINAL_ANSWER` *(không gửi thư)* |
| TC06 | `anti_hallucination` | 3 | `job_requirement_query` → `cv_screening` **(NOT_FOUND)** → `FINAL_ANSWER` |

---

## 3. TỔNG KẾT KẾT QUẢ NGHIỆM THU & NỘP BÀI

- [ ] Đã điền API Key thật trong `.env` và xác nhận Agent chạy mượt mà trên LLM API thật (Gemini/OpenAI).
- **Tổng số Test Cases đã chạy thành công:** **6** / 6 test cases *(0 test case còn TODO)*.
- **Số lượt gọi Tool qua MCP Server chính xác:** **10** lượt — `job_requirement_query` ×4, `cv_screening` ×4, `send_interview_invite` ×2 *(thêm 1 lượt bị policy guard chặn trước khi tới MCP)*.
- **Tổng số sự kiện trong `trace_waterfall.json`:** 17 sự kiện — 10 `TOOL_EXECUTION`, 6 `FINAL_ANSWER`, 1 `POLICY_BLOCK`.
- **Kết quả đẩy Repo nộp bài:** [ ] Đã Commit và Push mã nguồn thành công lên GitHub cá nhân.

### 3.1. Quan sát rút ra từ Waterfall Trace

1. **Độ trễ nằm gần như toàn bộ ở lượt gọi LLM, không ở tool.** Ở chế độ Mock, `latency_ms` mỗi bước khoảng 0.1 ms; khi chạy Gemini thật con số này tăng lên bậc nghìn mili-giây trong khi thực thi tool vẫn dưới 1 ms. → Muốn Agent nhanh thì phải **giảm số vòng lặp**, tối ưu code tool là vô nghĩa.
2. **Chi phí tăng theo số vòng lặp, không theo độ dài câu hỏi.** Vì lịch sử hội thoại được gửi lại toàn bộ mỗi vòng, TC04 (4 vòng) tốn gấp khoảng 4 lần TC01 (1 vòng) dù câu hỏi dài tương đương.
3. **Prompt là hàng rào mềm, code là hàng rào cứng.** TC03 chứng minh: dù System Prompt đã có luật 7 cấm gửi thư mời khi chưa sàng lọc, Agent vẫn thử gọi — chỉ policy guard trong `app.py` mới thực sự chặn được. Với tool có tác dụng phụ ra thế giới thực (gửi email cho ứng viên), **không được tin LLM**.

### 3.2. Điểm khác biệt so với Starter Repo (ngoài 2 TODO bắt buộc)

| Hạng mục | Starter Repo | Bài nộp này |
| :--- | :--- | :--- |
| Số Tools | 2 | **3** (thêm `cv_screening` để tạo Dynamic Decision) |
| Vòng lặp ReAct | Gọi 1 tool rồi `break`, Final Answer ghép bằng `if/else` | **Vòng lặp đa bước thật**, Observation nạp ngược cho LLM |
| Lịch sử hội thoại | `generate_with_tools()` không có tham số history | Định dạng history trung lập, mỗi Provider tự dịch sang SDK riêng |
| Trường `thought` | Chuỗi f-string do code tự ghép | Lấy **văn bản suy luận thật** model xuất ra kèm function call |
| An toàn vận hành | Không có | Policy guard chặn tool WRITE + loại sự kiện `POLICY_BLOCK` trong trace |
| Chatbot vs Agent | `run_baseline_chatbot()` không nơi nào gọi | Thêm chế độ `--compare` chạy song song hai kiến trúc |

---

## 4. HƯỚNG DẪN CHẠY LẠI ĐỂ NGHIỆM THU

```powershell
# B1. Kiểm thử MCP Server độc lập (kỳ vọng: 3 Tools, phong bì JSON-RPC hợp lệ)
python src/mcp_server.py

# B2. Chạy toàn bộ Test Suite ở chế độ Mock (miễn phí, dùng để debug)
$env:LLM_PROVIDER="mock"; python src/app.py --all

# B3. NGHIỆM THU - điền GEMINI_API_KEY vào .env rồi chạy lại bằng LLM thật
#     Lưu ý: dùng python trong .venv (đã cài sẵn google-genai), và model phải là
#     gemini-3.6-flash trở lên - gemini-2.5-flash đã ngừng cấp cho tài khoản mới.
.\.venv\Scripts\Activate.ps1
Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
python src/app.py --all

# B4. So sánh trực quan Chatbot (Cấp 2) vs ReAct Agent (Cấp 3)
python src/app.py --compare

# B5. Trò chuyện trực tiếp với Agent
python src/app.py --interactive
```

---

> ✅ **HOÀN TẤT NỘP BÀI:** Sao chép đường link GitHub Repository cá nhân của bạn và dán vào ô nộp bài trên hệ thống LMS VLearn để hoàn tất Bài Lab 3!
