from __future__ import annotations

from pathlib import Path


ADMIN_HTML = Path(__file__).resolve().parents[1] / "webapp" / "admin.html"


def test_admin_overview_has_operator_command_center():
    html = ADMIN_HTML.read_text(encoding="utf-8")

    assert 'id="autoRefreshSelect"' in html
    assert 'id="lastUpdated"' in html
    assert 'id="copyReportBtn"' in html
    assert 'id="quickActions"' in html
    assert 'id="insightList"' in html
    assert "buildOperatorInsights" in html
    assert "copyOpsReport" in html


def test_admin_audit_workspace_exposes_filters():
    html = ADMIN_HTML.read_text(encoding="utf-8")

    assert 'id="auditSearch"' in html
    assert 'id="auditResultFilter"' in html
    assert 'id="auditActionFilter"' in html
    assert 'id="auditReset"' in html
    assert "loadAudit(" in html
    assert "auditFilters" in html
