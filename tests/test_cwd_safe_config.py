"""cwd非依存の設定読み込みに対する回帰テスト。

ダンのCLIは D:\\dan-workspace (= リポジトリ外) を cwd として動く
(app/agent/cli_runner.py CLI_WORKSPACE。開発者向け CLAUDE.md の混入を
防ぐための意図的な分離)。過去 (2026-06-11) に app/config.py の env_file が
cwd相対 (".env") だったため、MCPサブプロセスが .env を見失い
TWOCAPTCHA_API_KEY が空になって solve_captcha が動かず、ダンが
「APIキーをくれ」とユーザーに丸投げする事故が起きた (PR#202で修正)。

このテストは「.env を読む全経路が cwd ではなく __file__ 基準で
解決される」ことを固定し、同種の回帰を起動前/CIで捕まえる。
関連メモリ: project_cwd_separation_invariant / project_captcha_autonomy_gap
"""
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"


def _read_env_value(key: str):
    """repo/.env から key の値を直読みする (無ければ None)。"""
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


@pytest.fixture
def chdir_outside_repo(tmp_path, monkeypatch):
    """cwd を D:\\dan-workspace 相当の「リポジトリ外」ディレクトリへ移す。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_config_env_file_is_absolute_repo_path():
    """app/config.py の env_file は cwd相対ではなく repo/.env の絶対パス。

    これが ".env" のような相対値に戻ると captcha鍵バグが再発する。
    """
    from app.config import Settings

    env_file = Settings.Config.env_file
    p = Path(env_file)
    assert p.is_absolute(), f"env_file は絶対パスであるべき: {env_file!r}"
    assert p == ENV_PATH, f"env_file は repo/.env を指すべき: {p}"


def test_mcp_server_dotenv_path_is_absolute_repo_path():
    """MCPサブプロセスの .env 補完経路 (PROJECT_ROOT) も repo基準の絶対パス。"""
    mcp = pytest.importorskip("app.mcp_server")
    root = Path(mcp.PROJECT_ROOT)
    assert root.is_absolute(), f"PROJECT_ROOT は絶対パスであるべき: {root}"
    assert (root / ".env") == ENV_PATH, f"PROJECT_ROOT/.env は repo/.env を指すべき: {root / '.env'}"


@pytest.mark.skipif(not ENV_PATH.exists(), reason=".env が無い (CI 等)")
def test_settings_load_key_from_foreign_cwd(chdir_outside_repo, monkeypatch):
    """リポジトリ外 cwd から Settings() を作っても .env の鍵が読める。

    TWOCAPTCHA_API_KEY を代表に使う (通常シェル環境変数には無いので
    env_file 経由でしか入らない = ファイル読込経路を実際に検証できる)。
    """
    expected = _read_env_value("TWOCAPTCHA_API_KEY")
    if not expected:
        pytest.skip("TWOCAPTCHA_API_KEY が .env に未設定")
    # os.environ ではなく env_file 経由で読まれることを検証するため環境変数を除去
    monkeypatch.delenv("TWOCAPTCHA_API_KEY", raising=False)
    from app.config import Settings

    s = Settings()
    assert s.TWOCAPTCHA_API_KEY == expected


def test_streaming_flag_is_cwd_independent(chdir_outside_repo, monkeypatch):
    """_dotenv_streaming_flag() がリポジトリ外 cwd でも .env を読めて、
    repo cwd と同じ結果を返す (= cwd非依存)。"""
    ss = pytest.importorskip("app.agent.streaming_session")
    # 環境変数が結果を支配しないよう除去し、.env 読込経路だけを比較する
    monkeypatch.delenv("DAN_STREAMING_INPUT", raising=False)

    ss._DOTENV_FLAG_CACHE = None
    foreign = ss._dotenv_streaming_flag()  # chdir_outside_repo 適用済みの cwd

    monkeypatch.chdir(REPO_ROOT)
    ss._DOTENV_FLAG_CACHE = None
    repo = ss._dotenv_streaming_flag()

    ss._DOTENV_FLAG_CACHE = None  # 後続テストへ状態を漏らさない
    assert foreign == repo
