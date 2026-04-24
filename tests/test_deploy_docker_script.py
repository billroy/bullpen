"""Regression checks for the Docker deploy script."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_deploy_docker_offers_local_project_option_from_repo_root():
    text = _read("deploy-docker.sh")
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    assert 'LOCAL_PROJECT_PATH_DEFAULT="$(dirname "$SCRIPT_DIR")/$(basename "$SCRIPT_DIR")-project"' in text
    assert 'if [[ "$(abs_path "$PWD")" == "$SCRIPT_DIR" ]]; then' in text
    assert 'Create or use local project directory ${LOCAL_PROJECT_PATH_DEFAULT}?' in text
    assert 'mkdir -p "$LOCAL_PROJECT_PATH_DEFAULT"' in text
    assert 'Project path to mount into /workspace (required): ' in text
    assert "Type . if you intentionally want to mount the Bullpen repo itself." in text


def test_deploy_docker_hides_unavailable_projects_in_container():
    text = _read("deploy-docker.sh")
    assert '-e "BULLPEN_HIDE_UNAVAILABLE_PROJECTS=1"' in text


def test_deploy_docker_syncs_github_cli_auth_into_persistent_home():
    text = _read("deploy-docker.sh")
    assert "sync_dir_if_exists()" in text
    assert 'sync_dir_if_exists "$HOME/.config/gh" "$DOCKER_HOME/.config/gh"' in text


def test_docker_entrypoint_sets_up_git_for_copied_github_cli_auth():
    text = _read("deploy/docker/entrypoint.sh")
    assert '[[ -f "$HOME/.config/gh/hosts.yml" ]]' in text
    assert "gh auth setup-git" in text


def test_docker_compose_hides_unavailable_projects_in_container():
    text = _read("docker-compose.yml")
    assert 'BULLPEN_HIDE_UNAVAILABLE_PROJECTS: "1"' in text
