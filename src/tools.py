"""
🛠️ TOOL DEFINITIONS & EXECUTION BACKEND
Mã nguồn chứa danh sách Tool Schemas (JSON Schema) và Execution Layer phục vụ cho MCP Server.

📌 ĐỀ TÀI: Trợ lý Tuyển dụng & Sàng lọc CV (Gợi ý 4.1)
   - job_requirement_query  : Tra cứu tiêu chí tuyển dụng (JD) của một vị trí   [READ]
   - cv_screening           : Chấm mức độ phù hợp của CV so với JD              [COMPUTE]
   - send_interview_invite  : Gửi thông báo lịch phỏng vấn cho ứng viên         [WRITE - có tác dụng phụ]
"""

import json
from typing import Dict, Any, List

# ==============================================================================
# 1. KHAI BÁO TOOL SCHEMAS CHUẨN NATIVE JSON SCHEMA (TASK 1.2)
# ==============================================================================
# 💡 Lưu ý thiết kế: LLM KHÔNG đọc code Python, nó chỉ đọc đúng đoạn JSON Schema
#    dưới đây. Vì vậy trường "description" chính là prompt engineering, không phải
#    comment cho người đọc. Mọi ví dụ định dạng ID ('AIE-01', 'UV003') được đưa vào
#    description để LLM trích xuất tham số đúng chuẩn.

TOOLS_SCHEMA = [
    # --------------------------------------------------------------------------
    # Tool 1 [READ]: Tra cứu tiêu chí tuyển dụng của vị trí
    # --------------------------------------------------------------------------
    {
        "name": "job_requirement_query",
        "description": (
            "Tra cứu tiêu chí tuyển dụng (Job Description) của một vị trí đang mở: "
            "số năm kinh nghiệm tối thiểu, danh sách kỹ năng bắt buộc, trình độ học vấn, "
            "dải lương và cán bộ quản lý tuyển dụng. "
            "Dùng công cụ này TRƯỚC KHI đánh giá bất kỳ ứng viên nào."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "position_id": {
                    "type": "string",
                    "description": "Mã vị trí tuyển dụng cần tra cứu (ví dụ: 'AIE-01', 'DSA-02', 'MLE-03')"
                }
            },
            "required": ["position_id"]
        }
    },

    # --------------------------------------------------------------------------
    # Tool 2 [COMPUTE]: Sàng lọc CV ứng viên theo tiêu chí vị trí
    # --------------------------------------------------------------------------
    {
        "name": "cv_screening",
        "description": (
            "Chấm điểm mức độ phù hợp của CV ứng viên so với tiêu chí tuyển dụng của một vị trí. "
            "Trả về match_score (%), danh sách kỹ năng đã khớp (matched_skills), kỹ năng còn thiếu "
            "(missing_skills) và kết luận verdict là 'PASS' hoặc 'FAIL'. "
            "Bắt buộc phải chạy công cụ này trước khi gửi thư mời phỏng vấn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "description": "Mã hồ sơ ứng viên cần sàng lọc (ví dụ: 'UV001', 'UV002', 'UV003')"
                },
                "position_id": {
                    "type": "string",
                    "description": "Mã vị trí tuyển dụng dùng làm chuẩn đối chiếu (ví dụ: 'AIE-01')"
                }
            },
            "required": ["candidate_id", "position_id"]
        }
    },

    # --------------------------------------------------------------------------
    # Tool 3 [WRITE]: Gửi thông báo lịch phỏng vấn
    # ⚠️ Đây là công cụ DUY NHẤT có tác dụng phụ ra thế giới thực (gửi email).
    #    Gửi nhầm cho ứng viên chưa đạt là sự cố nghiệp vụ, không phải lỗi hiển thị.
    # --------------------------------------------------------------------------
    {
        "name": "send_interview_invite",
        "description": (
            "Gửi email thông báo lịch phỏng vấn cho ứng viên. "
            "CẢNH BÁO: đây là hành động có tác dụng phụ thật (gửi thư tới ứng viên), "
            "CHỈ được gọi sau khi cv_screening đã trả về verdict = 'PASS' cho chính ứng viên đó."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "description": "Mã hồ sơ ứng viên nhận thư mời (ví dụ: 'UV003')"
                },
                "interview_datetime": {
                    "type": "string",
                    "description": "Thời gian phỏng vấn theo định dạng 'HH:MM DD/MM/YYYY' (ví dụ: '09:00 22/09/2026')"
                },
                "interviewer": {
                    "type": "string",
                    "description": "Tên người phỏng vấn. Nếu không được cung cấp, hệ thống tự lấy cán bộ quản lý tuyển dụng của vị trí."
                },
                "mode": {
                    "type": "string",
                    "enum": ["online", "onsite"],
                    "description": "Hình thức phỏng vấn: 'online' (trực tuyến) hoặc 'onsite' (tại văn phòng). Mặc định là 'online'."
                }
            },
            "required": ["candidate_id", "interview_datetime"]
        }
    }
]

# ==============================================================================
# 2. MÔ PHỎNG DỮ LIỆU ATS (APPLICANT TRACKING SYSTEM)
# ==============================================================================
# 💡 Dữ liệu được gài có chủ đích để tạo đủ 3 nhánh rẽ phục vụ Dynamic Decision:
#    UV001 -> đạt rõ ràng  | UV002 -> trượt (2 lý do)  | UV003 -> đạt sát ngưỡng

MOCK_JOB_REQUIREMENTS = {
    "AIE-01": {
        "title": "AI Engineer",
        "department": "Khối Công nghệ - Trung tâm AI",
        "min_years_exp": 2,
        "required_skills": ["Python", "PyTorch", "NLP", "MLOps"],
        "preferred_skills": ["Docker", "Kubernetes", "LangChain"],
        "education": "Tốt nghiệp Đại học chuyên ngành CNTT / Khoa học máy tính hoặc tương đương",
        "salary_range": "25.000.000 - 40.000.000 VND",
        "headcount": 3,
        "hiring_manager": "Trần Quốc Huy"
    },
    "DSA-02": {
        "title": "Data Analyst",
        "department": "Khối Kinh doanh - Phòng Phân tích dữ liệu",
        "min_years_exp": 1,
        "required_skills": ["SQL", "Python", "Power BI"],
        "preferred_skills": ["Excel nâng cao", "Airflow"],
        "education": "Tốt nghiệp Đại học chuyên ngành Kinh tế / Toán / CNTT",
        "salary_range": "15.000.000 - 25.000.000 VND",
        "headcount": 2,
        "hiring_manager": "Phạm Thu Hà"
    },
    "MLE-03": {
        "title": "Machine Learning Engineer",
        "department": "Khối Công nghệ - Trung tâm AI",
        "min_years_exp": 3,
        "required_skills": ["Python", "TensorFlow", "MLOps", "Kubernetes"],
        "preferred_skills": ["Spark", "Feature Store"],
        "education": "Thạc sĩ hoặc Đại học loại Giỏi chuyên ngành CNTT",
        "salary_range": "35.000.000 - 55.000.000 VND",
        "headcount": 1,
        "hiring_manager": "Trần Quốc Huy"
    }
}

MOCK_CANDIDATES = {
    "UV001": {
        "full_name": "Nguyễn Hoàng Nam",
        "email": "nam.nh@email.com",
        "phone": "0901234567",
        "position_applied": "AIE-01",
        "years_exp": 3,
        "skills": ["Python", "PyTorch", "NLP", "MLOps", "Docker"],
        "education": "Đại học Bách Khoa Hà Nội - Khoa học máy tính",
        "cv_summary": "3 năm phát triển mô hình NLP cho sản phẩm chatbot, có kinh nghiệm triển khai MLOps."
    },
    "UV002": {
        "full_name": "Lê Thị Bình",
        "email": "binh.lt@email.com",
        "phone": "0912345678",
        "position_applied": "AIE-01",
        "years_exp": 1,
        "skills": ["Python", "Excel", "SQL"],
        "education": "Đại học Kinh tế Quốc dân - Hệ thống thông tin quản lý",
        "cv_summary": "1 năm làm phân tích dữ liệu báo cáo kinh doanh, mới bắt đầu tìm hiểu Machine Learning."
    },
    "UV003": {
        "full_name": "Trần Minh Khoa",
        "email": "khoa.tm@email.com",
        "phone": "0923456789",
        "position_applied": "AIE-01",
        "years_exp": 2,
        "skills": ["Python", "PyTorch", "NLP", "Docker"],
        "education": "Đại học Công nghệ - ĐHQG Hà Nội - Trí tuệ nhân tạo",
        "cv_summary": "2 năm nghiên cứu mô hình ngôn ngữ, chưa có kinh nghiệm vận hành MLOps sản xuất."
    }
}

# Bộ đếm mô phỏng số thư mời đã phát hành (dùng sinh invite_id)
_INVITE_COUNTER = {"count": 0}

# Ngưỡng đạt của quy trình sàng lọc
PASS_SCORE_THRESHOLD = 70


# ==============================================================================
# 3. HÀM THỰC THI TOOL (EXECUTION LAYER)
# ==============================================================================

def _normalize(skills: List[str]) -> Dict[str, str]:
    """Chuẩn hóa danh sách kỹ năng về lowercase để so khớp, giữ lại bản gốc để hiển thị"""
    return {s.strip().lower(): s.strip() for s in skills}


def execute_job_requirement_query(position_id: str) -> str:
    """[READ] Tra cứu tiêu chí tuyển dụng của một vị trí"""
    pid = str(position_id).strip().upper()
    job = MOCK_JOB_REQUIREMENTS.get(pid)

    if not job:
        return json.dumps({
            "status": "NOT_FOUND",
            "position_id": pid,
            "message": f"Không tìm thấy vị trí tuyển dụng có mã '{pid}'. Các mã hiện có: {', '.join(MOCK_JOB_REQUIREMENTS.keys())}."
        }, ensure_ascii=False)

    return json.dumps({
        "status": "SUCCESS",
        "position_id": pid,
        "data": job
    }, ensure_ascii=False)


def execute_cv_screening(candidate_id: str, position_id: str) -> str:
    """[COMPUTE] Chấm mức độ phù hợp của CV ứng viên so với tiêu chí vị trí"""
    cid = str(candidate_id).strip().upper()
    pid = str(position_id).strip().upper()

    candidate = MOCK_CANDIDATES.get(cid)
    job = MOCK_JOB_REQUIREMENTS.get(pid)

    if not candidate:
        return json.dumps({
            "status": "NOT_FOUND",
            "candidate_id": cid,
            "message": f"Không tìm thấy ứng viên có mã '{cid}' trong hệ thống ATS."
        }, ensure_ascii=False)

    if not job:
        return json.dumps({
            "status": "NOT_FOUND",
            "position_id": pid,
            "message": f"Không tìm thấy vị trí tuyển dụng có mã '{pid}'."
        }, ensure_ascii=False)

    required = _normalize(job["required_skills"])
    owned = _normalize(candidate["skills"])

    matched_keys = [k for k in required if k in owned]
    missing_keys = [k for k in required if k not in owned]

    matched_skills = [required[k] for k in matched_keys]
    missing_skills = [required[k] for k in missing_keys]

    # match_score = số kỹ năng khớp / số kỹ năng yêu cầu (làm tròn về %)
    match_score = round(len(matched_keys) / len(required) * 100) if required else 0

    exp_ok = candidate["years_exp"] >= job["min_years_exp"]
    skill_ok = match_score >= PASS_SCORE_THRESHOLD
    verdict = "PASS" if (exp_ok and skill_ok) else "FAIL"

    reasons = []
    if not exp_ok:
        reasons.append(
            f"Kinh nghiệm {candidate['years_exp']} năm chưa đạt yêu cầu tối thiểu {job['min_years_exp']} năm"
        )
    if not skill_ok:
        reasons.append(
            f"Mức độ khớp kỹ năng {match_score}% chưa đạt ngưỡng {PASS_SCORE_THRESHOLD}% "
            f"(thiếu: {', '.join(missing_skills)})"
        )

    return json.dumps({
        "status": "SUCCESS",
        "candidate_id": cid,
        "position_id": pid,
        "candidate_name": candidate["full_name"],
        "position_title": job["title"],
        "verdict": verdict,
        "match_score": match_score,
        "years_exp": candidate["years_exp"],
        "min_years_exp": job["min_years_exp"],
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "reason": "; ".join(reasons) if reasons
                  else f"Đáp ứng {match_score}% kỹ năng bắt buộc và đủ số năm kinh nghiệm yêu cầu"
    }, ensure_ascii=False)


def execute_send_interview_invite(candidate_id: str,
                                  interview_datetime: str,
                                  interviewer: str = None,
                                  mode: str = "online") -> str:
    """
    [WRITE] Gửi thông báo lịch phỏng vấn.

    ⚠️ HÀNG RÀO CỨNG TẦNG TOOL: tool có tác dụng phụ phải TỰ phòng vệ,
       không được tin tưởng hoàn toàn vào việc LLM đã tuân thủ prompt.
    """
    cid = str(candidate_id).strip().upper()
    candidate = MOCK_CANDIDATES.get(cid)

    if not candidate:
        return json.dumps({
            "status": "NOT_FOUND",
            "candidate_id": cid,
            "message": f"Không tìm thấy ứng viên có mã '{cid}'. Đã HỦY thao tác gửi thư mời để tránh gửi nhầm."
        }, ensure_ascii=False)

    if not interview_datetime or not str(interview_datetime).strip():
        return json.dumps({
            "status": "INVALID_ARGUMENT",
            "candidate_id": cid,
            "message": "Thiếu thời gian phỏng vấn (interview_datetime). Không thể phát hành thư mời."
        }, ensure_ascii=False)

    normalized_mode = str(mode).strip().lower() if mode else "online"
    if normalized_mode not in ("online", "onsite"):
        normalized_mode = "online"

    # Nếu LLM không cung cấp người phỏng vấn -> lấy hiring manager của vị trí ứng tuyển
    if not interviewer:
        job = MOCK_JOB_REQUIREMENTS.get(candidate.get("position_applied", ""))
        interviewer = job["hiring_manager"] if job else "Bộ phận Tuyển dụng"

    _INVITE_COUNTER["count"] += 1
    invite_id = f"INV-{cid}-{_INVITE_COUNTER['count']:02d}"

    return json.dumps({
        "status": "SUCCESS",
        "invite_id": invite_id,
        "candidate_id": cid,
        "candidate_name": candidate["full_name"],
        "email_sent_to": candidate["email"],
        "interview_datetime": interview_datetime,
        "interviewer": interviewer,
        "mode": normalized_mode,
        "message": (
            f"Đã gửi thư mời phỏng vấn {invite_id} tới {candidate['full_name']} "
            f"({candidate['email']}) lúc {interview_datetime}, hình thức {normalized_mode}, "
            f"người phỏng vấn: {interviewer}."
        )
    }, ensure_ascii=False)


# ==============================================================================
# 4. ROUTER & DISPATCHER
# ==============================================================================

TOOL_ROUTER = {
    "job_requirement_query": execute_job_requirement_query,
    "cv_screening": execute_cv_screening,
    "send_interview_invite": execute_send_interview_invite
}


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Hàm trung chuyển thực thi tool"""
    if tool_name in TOOL_ROUTER:
        try:
            return TOOL_ROUTER[tool_name](**arguments)
        except Exception as e:
            return json.dumps({"status": "EXECUTION_ERROR", "error": str(e)}, ensure_ascii=False)
    return json.dumps({
        "status": "UNKNOWN_TOOL",
        "error": f"Tool '{tool_name}' không tồn tại! Các tool hợp lệ: {', '.join(TOOL_ROUTER.keys())}"
    }, ensure_ascii=False)
