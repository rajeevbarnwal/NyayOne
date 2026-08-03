import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def basic_auth(email: str, token: str) -> str:
    encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def api_request(url: str, headers: dict, method: str = "GET", data: dict | None = None) -> tuple[int, object]:
    payload_bytes = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, headers=headers, data=payload_bytes, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body) if body else {}
        except Exception:
            return exc.code, body


def make_adf_comment(text: str) -> dict:
    paragraphs = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        paragraphs.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": line}]
        })
    return {
        "body": {
            "type": "doc",
            "version": 1,
            "content": paragraphs
        }
    }


def update_ticket(base_url: str, headers: dict, issue_key: str, comment_text: str) -> None:
    print(f"--- Updating Jira Ticket: {issue_key} ---")
    
    # 1. Fetch issue details
    status, payload = api_request(f"{base_url}/rest/api/3/issue/{issue_key}", headers)
    if status == 200:
        summary = payload.get("fields", {}).get("summary", "")
        curr_status = payload.get("fields", {}).get("status", {}).get("name", "")
        print(f"[{issue_key}] Summary: '{summary}' | Current Status: '{curr_status}'")
    else:
        print(f"Failed to fetch {issue_key}: HTTP {status} - {payload}")
        return

    # 2. Add Comment
    comment_payload = make_adf_comment(comment_text)
    c_status, c_resp = api_request(f"{base_url}/rest/api/3/issue/{issue_key}/comment", headers, method="POST", data=comment_payload)
    if c_status in {200, 201}:
        print(f"[{issue_key}] Comment posted successfully!")
    else:
        print(f"[{issue_key}] Failed to post comment: HTTP {c_status} - {c_resp}")

    # 3. Check transitions
    t_status, t_payload = api_request(f"{base_url}/rest/api/3/issue/{issue_key}/transitions", headers)
    if t_status == 200 and isinstance(t_payload, dict):
        transitions = t_payload.get("transitions", [])
        print(f"Available transitions for {issue_key}: {[t['name'] + ' (id:' + t['id'] + ')' for t in transitions]}")
        done_trans = next((t for t in transitions if "done" in t.get("name", "").lower() or t.get("name", "").lower() in {"resolve", "resolved", "complete", "completed", "in progress"}), None)
        if done_trans:
            trans_id = done_trans["id"]
            trans_name = done_trans["name"]
            tr_status, tr_resp = api_request(f"{base_url}/rest/api/3/issue/{issue_key}/transitions", headers, method="POST", data={"transition": {"id": trans_id}})
            if tr_status in {200, 204}:
                print(f"[{issue_key}] Successfully transitioned status to '{trans_name}'!")
            else:
                print(f"[{issue_key}] Transition result: HTTP {tr_status}")
    print()


def main():
    load_dotenv()
    base_url = os.getenv("JIRA_BASE_URL", "https://legalsaathi.atlassian.net").rstrip("/")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_API_TOKEN", "")

    if not email or not token:
        print("Error: JIRA_EMAIL or JIRA_API_TOKEN missing in .env")
        return

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": basic_auth(email, token),
    }

    # SAATHI-60 Comment
    saathi_60_comment = (
        "✅ RESOLUTION UPDATE (SAATHI-60):\n"
        "1. S-04 Inline OTP Input Field Fix:\n"
        "   - Added inline OTP state and rendered 6-digit OTP text box inline on S-04 with 'Verify OTP & Sign In' button.\n"
        "   - Verified with Vitest suite (65 test files, 649 tests passed).\n"
        "   - Commit: 6abda6b (fix(S-04): implement inline OTP verification text box)\n\n"
        "2. Student Profile Greeting & Session Resolution Fix:\n"
        "   - Updated login_service.py session_claims to accept 'otp_verified' or 'active' registrations.\n"
        "   - Updated recovery_service.py to set active status and last_seen_at timestamp on AuthSession.\n"
        "   - Updated auth_student.py RecoveryRef Pydantic schema to accept optional new_password parameter.\n"
        "   - Commit: c17e055 (fix(S-06): resolve RecoveryRef payload schema and AuthSession last_seen_at constraint)\n"
        "   - Verified S-14 greeting now displays actual user name ('Good evening, Sumit.')."
    )

    # SAATHI-62 Comment
    saathi_62_comment = (
        "✅ RESOLUTION UPDATE (SAATHI-62):\n"
        "1. 3-Step Account Recovery & Password Reset Flow (Screen S-06):\n"
        "   - Refactored V34PasswordReset into a 3-step wizard (Mobile Input -> 6-digit OTP Verification -> Set New Password & Auto-Login).\n"
        "   - Backend /api/v1/auth/student/recovery/complete updated to return active AuthSession cookie upon password update.\n"
        "   - Verified full end-to-end flow with browser subagent: verified recovery code, updated password, and auto-logged in directly to S-14 Student Dashboard.\n"
        "   - Commit: 1f0621b (feat(S-06): implement 3-step password reset and auto-login)\n"
        "   - Automated Vitest Suite: 65 test files passed (649 tests passed)."
    )

    update_ticket(base_url, headers, "SAATHI-60", saathi_60_comment)
    update_ticket(base_url, headers, "SAATHI-62", saathi_62_comment)


if __name__ == "__main__":
    main()
