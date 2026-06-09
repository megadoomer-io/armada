"""Tests for error handling — retry logic and state recovery."""

import pathlib

import pytest
import yaml

import armada.errors.retry as retry_mod
import armada.errors.state as state_mod


class TestRetry:
    @pytest.mark.unit
    def test_succeeds_first_try(self) -> None:
        result = retry_mod.with_retry(lambda: 42, operation_name="test")
        assert result == 42

    @pytest.mark.unit
    def test_succeeds_after_retries(self) -> None:
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise TimeoutError("timeout")
            return "ok"

        config = retry_mod.RetryConfig(max_attempts=3, base_delay=0.01, max_delay=0.1)
        result = retry_mod.with_retry(flaky, config=config, operation_name="flaky")
        assert result == "ok"
        assert attempts["count"] == 3

    @pytest.mark.unit
    def test_exhausted_raises(self) -> None:
        config = retry_mod.RetryConfig(max_attempts=2, base_delay=0.01)

        with pytest.raises(retry_mod.RetriesExhausted) as exc_info:
            retry_mod.with_retry(
                lambda: (_ for _ in ()).throw(TimeoutError("always fails")),
                config=config,
            )
        assert exc_info.value.attempts == 2
        assert isinstance(exc_info.value.last_error, TimeoutError)

    @pytest.mark.unit
    def test_non_retryable_exception_propagates(self) -> None:
        config = retry_mod.RetryConfig(max_attempts=3, base_delay=0.01)

        with pytest.raises(ValueError, match="not retryable"):
            retry_mod.with_retry(
                lambda: (_ for _ in ()).throw(ValueError("not retryable")),
                config=config,
            )

    @pytest.mark.unit
    def test_custom_retryable_exceptions(self) -> None:
        config = retry_mod.RetryConfig(
            max_attempts=2,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        )
        attempts = {"count": 0}

        def fail_then_succeed() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ValueError("retry me")
            return "recovered"

        result = retry_mod.with_retry(fail_then_succeed, config=config)
        assert result == "recovered"


class TestStateRecovery:
    @pytest.mark.unit
    def test_valid_file_returns_data(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        data = {"source": "james", "grains": []}
        state_file.write_text(yaml.dump(data))

        result = state_mod.recover_state_file(state_file)
        assert result is not None
        assert result["source"] == "james"

    @pytest.mark.unit
    def test_missing_file_returns_none(self, tmp_path: pathlib.Path) -> None:
        result = state_mod.recover_state_file(tmp_path / "nonexistent.yaml")
        assert result is None

    @pytest.mark.unit
    def test_malformed_file_with_backup(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        state_file.write_text("{{invalid yaml::")

        backup = tmp_path / "test.yaml.bak"
        backup_data = {"source": "james", "grains": [{"id": "saved"}]}
        backup.write_text(yaml.dump(backup_data))

        result = state_mod.recover_state_file(state_file)
        assert result is not None
        assert result["source"] == "james"
        # Original file should be restored from backup
        restored = yaml.safe_load(state_file.read_text())
        assert restored["source"] == "james"

    @pytest.mark.unit
    def test_malformed_file_no_backup(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        state_file.write_text("{{invalid yaml::")

        result = state_mod.recover_state_file(state_file)
        assert result is None
        # Original should be moved to .corrupt-*
        assert not state_file.exists()
        corrupt_files = list(tmp_path.glob("test.corrupt-*"))
        assert len(corrupt_files) == 1

    @pytest.mark.unit
    def test_malformed_file_and_backup(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        state_file.write_text("{{bad}}")

        backup = tmp_path / "test.yaml.bak"
        backup.write_text("{{also bad}}")

        result = state_mod.recover_state_file(state_file)
        assert result is None
        corrupt_files = list(tmp_path.glob("test.corrupt-*"))
        assert len(corrupt_files) == 1


class TestSaveWithBackup:
    @pytest.mark.unit
    def test_creates_new_file(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        state_mod.save_with_backup({"source": "james"}, state_file)

        assert state_file.exists()
        data = yaml.safe_load(state_file.read_text())
        assert data["source"] == "james"
        assert not (tmp_path / "test.yaml.bak").exists()

    @pytest.mark.unit
    def test_creates_backup_on_overwrite(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        state_file.write_text(yaml.dump({"source": "old"}))

        state_mod.save_with_backup({"source": "new"}, state_file)

        current = yaml.safe_load(state_file.read_text())
        assert current["source"] == "new"

        backup = yaml.safe_load((tmp_path / "test.yaml.bak").read_text())
        assert backup["source"] == "old"

    @pytest.mark.unit
    def test_atomic_write(self, tmp_path: pathlib.Path) -> None:
        state_file = tmp_path / "test.yaml"
        state_mod.save_with_backup({"key": "value"}, state_file)
        # tmp file should not remain
        assert not (tmp_path / "test.tmp").exists()
        assert state_file.exists()
