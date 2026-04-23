"""Regression checks for the Docker deploy script."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_deploy_docker_requires_explicit_project_path_from_repo_root():
    text = _read("deploy-docker.sh")
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    assert 'if [[ "$(abs_path "$PWD")" == "$SCRIPT_DIR" ]]; then' in text
    assert 'Project path to mount into /workspace (required): ' in text
    assert "Type . if you intentionally want to mount the Bullpen repo itself." in text


def test_deploy_docker_hides_unavailable_projects_in_container():
    text = _read("deploy-docker.sh")
    assert '-e "BULLPEN_HIDE_UNAVAILABLE_PROJECTS=1"' in text


def test_docker_compose_hides_unavailable_projects_in_container():
    text = _read("docker-compose.yml")
    assert 'BULLPEN_HIDE_UNAVAILABLE_PROJECTS: "1"' in text
