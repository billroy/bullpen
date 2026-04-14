"""Regression checks for left-pane project overflow menu wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_leftpane_projects_header_uses_menu_button_with_add_and_new_options():
    text = _read("static/components/LeftPane.js")
    assert "@click=\"toggleProjectMenu\">...</button>" in text
    assert "class=\"project-menu-item\" @click=\"promptAddProject\">Add Project</button>" in text
    assert "class=\"project-menu-item\" @click=\"promptNewProject\">New Project</button>" in text


def test_leftpane_empty_project_hint_tooltip_is_wired():
    text = _read("static/components/LeftPane.js")
    assert "v-if=\"showEmptyProjectHint\" class=\"project-menu-tooltip\"" in text
    assert "Open the menu to add or create your first project." in text
    assert "emptyProjectHintInitialized" in text
    assert "this.showEmptyProjectHint = list.length === 0;" in text
    assert "this.showEmptyProjectHint = false;" in text


def test_leftpane_projects_header_remains_visible_in_empty_state():
    text = _read("static/components/LeftPane.js")
    assert "v-if=\"projects\" class=\"left-pane-section\" :class=\"{ 'project-add-only': projects.length <= 1 }\"" in text
    assert "<h3>Projects</h3>" in text
    assert "v-if=\"projects.length > 1\" class=\"project-list\"" in text


def test_leftpane_emits_new_project_and_registers_menu_dismiss_listener():
    text = _read("static/components/LeftPane.js")
    assert "document.addEventListener('click', this.onGlobalClick);" in text
    assert "document.removeEventListener('click', this.onGlobalClick);" in text
    assert "this.$emit('new-project', path.trim());" in text


def test_switching_projects_joins_project_socket_room():
    text = _read("static/app.js")
    assert "function switchWorkspace(wsId)" in text
    assert "socket.emit('project:join', { workspaceId: wsId });" in text


def test_project_menu_styles_exist():
    text = _read("static/style.css")
    assert ".project-menu-tooltip {" in text
    assert ".project-menu-tooltip::after {" in text
    assert ".project-menu {" in text
    assert ".project-menu-item {" in text


def test_project_remove_button_wiring_exists():
    text = _read("static/components/LeftPane.js")
    assert "class=\"btn-icon project-remove-btn\"" in text
    assert "@click.stop=\"confirmRemoveProject(p)\"" in text
    assert "this.$emit('remove-project', project.id);" in text


def test_project_remove_button_styles_exist():
    text = _read("static/style.css")
    assert ".project-remove-btn {" in text
    assert ".project-item:hover .project-remove-btn" in text
