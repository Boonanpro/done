"""外部ドメインを「代理ログインで接続」する前の準備状況を診断する（レジストラ非依存）。

第三者ユーザーは『メールのアプリパスワード未作成』『SMS転送APK未導入』『2FA未設定』
などが普通。本モジュールは、接続したいドメインに対して
  1. どのレジストラか（registrar_detect）
  2. ダンが代理ログインに使える認証情報が保存済みか
  3. 2FAコードを自動で受け取れるチャネル（メールIMAP / SMS転送APK）が準備済みか
を診断し、**未設定の項目は「何を・どうやれば次回から全自動になるか」を案内**として返す。

設計方針:
- 認証情報やOTPチャネルが無くても落とさず、"未準備" として案内を返す（オンボーディング前提）。
- 自動化できない壁（iPhoneのSMS等）は最後の保険＝ワンタイム手動入力にフォールバックする想定。
- ここは「診断と案内」まで。実際の代理ログイン+DNS操作は per-registrar の実装（③）が担う。

使い方:
    from app.tools.publish_site.registrar_onboarding import connect_readiness
    report = await connect_readiness(user_id, "example.com", email="me@gmail.com")
"""
from __future__ import annotations

from typing import Any, Optional

from app.tools.publish_site.registrar_detect import detect_registrar


async def _has_credential(user_id: str, registrar: dict[str, Any]) -> bool:
    """そのレジストラのログイン情報が保存済みか（login_url ドメイン照合 → key 名で再確認）。"""
    try:
        from app.services.credentials_service import CredentialsService

        svc = CredentialsService()
        login_url = registrar.get("login_url") or ""
        if login_url:
            cred = await svc.find_credential_by_url(user_id, login_url)
            if cred:
                return True
        key = registrar.get("registrar_key") or ""
        if key and key != "unknown":
            return bool(await svc.get_credential(user_id, key))
    except Exception:  # noqa: BLE001
        pass
    return False


async def _email_otp_ready(user_id: str, email: Optional[str]) -> tuple[bool, dict[str, Any]]:
    """メールOTPを自動読取できる状態か（IMAPアプリパスワード保存済みか）。"""
    if not email:
        return False, {"reason": "メールアドレス未指定"}
    try:
        from app.services.otp_service import OTPService, app_password_guidance

        ready = await OTPService().has_imap_access(user_id, email)
        if ready:
            return True, {}
        return False, app_password_guidance(email)
    except Exception as e:  # noqa: BLE001
        return False, {"reason": f"判定不可: {e}"}


async def _sms_otp_ready(user_id: str) -> tuple[bool, dict[str, Any]]:
    """SMS OTP を自動転送できる状態か（dan-mobile APK 登録済み＆有効か）。Android限定。"""
    try:
        from app.services.otp_service import OTPService

        status = await OTPService().get_apk_otp_device_status(user_id)
        if status.get("enabled"):
            return True, {"device_name": status.get("device_name")}
        return False, {}
    except Exception as e:  # noqa: BLE001
        return False, {"reason": f"判定不可: {e}"}


async def connect_readiness(
    user_id: str,
    domain: str,
    email: Optional[str] = None,
) -> dict[str, Any]:
    """外部ドメイン接続の準備状況レポートを返す。

    Returns dict:
        domain, registrar : registrar_detect の結果
        path  : "api" | "browser" | "manual"
        ready : 今すぐ代理ログイン接続を試せるか（browser パスのみ意味を持つ）
        needs : [{id, title, why, how, done}] 未充足の準備項目（案内付き）
        channels : {email: {...}, sms: {...}} 2FA受け取りチャネルの準備状況
    """
    registrar = await detect_registrar(domain)
    path = registrar.get("automation", "manual")

    report: dict[str, Any] = {
        "domain": registrar["domain"],
        "registrar": registrar,
        "path": path,
        "ready": False,
        "needs": [],
        "channels": {},
    }

    # API パス（うちのトークンで直接DNS）：ログイン情報も2FAも不要。
    if path == "api":
        report["ready"] = True
        report["summary"] = (
            f"{registrar['label']} はダンがAPIで直接設定できます。"
            "ログイン情報の入力は不要です。"
        )
        return report

    # manual パス（自動化未対応レジストラ）：手動レコード設定を案内。
    if path == "manual":
        report["summary"] = (
            f"{registrar['label']} は自動ログイン未対応です。"
            "DNSレコードを手動で設定する案内に切り替えます。"
        )
        report["needs"].append({
            "id": "manual_dns",
            "title": "DNSレコードを手動設定",
            "why": "このレジストラはダンの代理ログイン対象外のため",
            "how": "接続時にダンが表示する A / CNAME レコードを、ご自身の管理画面に貼り付けてください",
            "done": False,
        })
        return report

    # browser パス（代理ログイン）：認証情報＋2FAチャネルの準備を診断。
    has_cred = await _has_credential(user_id, registrar)
    email_ready, email_guide = await _email_otp_ready(user_id, email)
    sms_ready, sms_info = await _sms_otp_ready(user_id)

    report["channels"] = {
        "email": {"ready": email_ready, **({"guidance": email_guide} if not email_ready else {})},
        "sms": {"ready": sms_ready, **sms_info},
    }

    needs: list[dict[str, Any]] = []
    needs.append({
        "id": "credential",
        "title": f"{registrar['label']} のログイン情報",
        "why": "ダンが代わりにログインしてDNSを設定するため",
        "how": (
            f"{registrar['label']} のログインID・パスワードを登録してください"
            f"（ログイン画面: {registrar['login_url']}）。"
            "忘れている場合は、ダンがパスワード再設定を代行案内します。"
        ),
        "done": has_cred,
    })
    # 2FAの自動受け取りは「どちらか1つ」準備できていれば手動入力を避けられる。
    otp_auto = email_ready or sms_ready
    needs.append({
        "id": "otp_channel",
        "title": "ログイン時の確認コードの自動受け取り",
        "why": "2段階認証のコードをダンが自動で読み取り、手入力を不要にするため",
        "how": (
            "次のどちらかを設定すると全自動になります：(A) Gmail等のIMAPアプリパスワードを登録"
            "（メールに届くコード用）／(B) dan-mobile APK を入れて『SMS OTP転送』をオン"
            "（SMSに届くコード用・Android限定）。未設定でも、接続時に届いたコードを1回だけ"
            "入力する方法で接続自体は可能です。"
        ),
        "done": otp_auto,
        "fallback": "manual_paste",
    })

    report["needs"] = needs
    report["ready"] = has_cred  # 認証情報があれば接続着手可（2FAは手動入力で補える）
    missing = [n["title"] for n in needs if not n["done"]]
    if report["ready"] and otp_auto:
        report["summary"] = f"{registrar['label']} に代理ログインして接続できます（全自動）。"
    elif report["ready"]:
        report["summary"] = (
            f"{registrar['label']} に接続できます。確認コードは届いたものを1回だけ入力してください"
            "（自動受け取りを設定すると次回から不要になります）。"
        )
    else:
        report["summary"] = "接続前に次の準備が必要です: " + " / ".join(missing)
    return report
