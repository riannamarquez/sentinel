"""Local .env configuration and exported-variable precedence."""
import os
from unittest.mock import patch

from sentinel.api.app import create_app


def test_app_loads_dotenv_before_reading_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('SENTINEL_DB=from-file.db\nSENTINEL_LLM_MODE=fixture\nGEMINI_API_KEY="local-test-key"\n')
    with patch.dict(os.environ, {}, clear=True):
        app = create_app()
        assert app.state.store.path == 'from-file.db'
        assert os.environ['GEMINI_API_KEY'] == 'local-test-key'
        assert app.state.adapter is None


def test_exported_variables_override_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('SENTINEL_DB=from-file.db\nSENTINEL_LLM_MODE=live\nGEMINI_API_KEY=file-key\n')
    with patch.dict(os.environ, {'SENTINEL_DB': 'exported.db', 'SENTINEL_LLM_MODE': 'fixture',
                                 'GEMINI_API_KEY': 'exported-key'}, clear=True):
        app = create_app()
        assert app.state.store.path == 'exported.db'
        assert app.state.adapter is None
        assert os.environ['GEMINI_API_KEY'] == 'exported-key'


def test_app_runs_without_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch.dict(os.environ, {}, clear=True):
        app = create_app()
        assert app.state.store.path == 'sentinel.db'
        assert app.state.adapter is None
