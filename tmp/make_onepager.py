"""Generate a pretty one-page PDF summary of Bullpen."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame, KeepInFrame
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER


OUT_PATH = "/Users/bill/aistuff/bullpen/docs/one-pager.pdf"

# Palette — slate + accent teal/amber, dark-mode-feel header
NAVY = HexColor("#0F172A")      # deep slate
SLATE = HexColor("#334155")
LIGHT = HexColor("#F8FAFC")
BORDER = HexColor("#E2E8F0")
TEAL = HexColor("#14B8A6")
AMBER = HexColor("#F59E0B")
INDIGO = HexColor("#6366F1")
ROSE = HexColor("#F43F5E")
MUTED = HexColor("#64748B")
SOFT_TEAL = HexColor("#CCFBF1")
SOFT_AMBER = HexColor("#FEF3C7")
SOFT_INDIGO = HexColor("#E0E7FF")
SOFT_ROSE = HexColor("#FFE4E6")


def draw_page(c: canvas.Canvas):
    W, H = letter
    margin = 0.4 * inch

    # Background
    c.setFillColor(LIGHT)
    c.rect(0, 0, W, H, stroke=0, fill=1)

    # === HEADER BANNER ===
    banner_h = 1.1 * inch
    c.setFillColor(NAVY)
    c.rect(0, H - banner_h, W, banner_h, stroke=0, fill=1)

    # Accent stripe under header
    c.setFillColor(TEAL)
    c.rect(0, H - banner_h - 4, W, 4, stroke=0, fill=1)

    # Logo "mark" — stylized B badge
    badge_x = margin + 0.08 * inch
    badge_y = H - banner_h + 0.22 * inch
    badge_w = 0.62 * inch
    badge_h = 0.62 * inch
    c.setFillColor(TEAL)
    c.roundRect(badge_x, badge_y, badge_w, badge_h, 8, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(badge_x + badge_w / 2, badge_y + 0.14 * inch, "B")

    # Title
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(margin + 0.9 * inch, H - 0.55 * inch, "Bullpen")
    c.setFillColor(HexColor("#94A3B8"))
    c.setFont("Helvetica", 11)
    c.drawString(margin + 0.9 * inch, H - 0.78 * inch,
                 "An AI agent team manager — configure workers, assign tickets, and ship.")

    # Top-right tag
    tag_txt = "One-page overview"
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(HexColor("#CBD5E1"))
    c.drawRightString(W - margin, H - 0.5 * inch, tag_txt)
    c.setFont("Helvetica", 8)
    c.drawRightString(W - margin, H - 0.68 * inch, "MIT License  ·  Python · Flask · Vue 3")

    # === BODY AREA ===
    body_top = H - banner_h - 0.25 * inch
    body_bottom = 0.55 * inch

    # --- Intro paragraph ---
    styles_body = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.5, leading=13,
        textColor=SLATE, alignment=TA_LEFT,
    )
    intro_text = (
        "<b>Bullpen</b> orchestrates teams of CLI-based AI coding agents "
        "(Claude, Codex, Gemini) on a visual Kanban board. Create tickets, drag "
        "them onto configured workers, and watch agents execute autonomously "
        "with live output streaming, retry logic, auto-commits, and optional "
        "pull requests. A built-in MCP server lets agents manage their own tickets."
    )
    p = Paragraph(intro_text, styles_body)
    frame = Frame(margin, body_top - 0.75 * inch, W - 2 * margin, 0.75 * inch,
                  showBoundary=0, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    frame.addFromList([p], c)

    # --- Feature cards (2x2 grid) ---
    cards_top = body_top - 0.95 * inch
    card_gap = 0.12 * inch
    card_w = (W - 2 * margin - card_gap) / 2
    card_h = 1.55 * inch

    cards = [
        {
            "title": "Kanban + Worker Grid",
            "color": TEAL, "soft": SOFT_TEAL,
            "lines": [
                "Drag-and-drop tickets across customizable columns",
                "Configurable grid of AI agent slots",
                "Switchable list view with filters & search",
                "Right-click worker actions, focus mode, live output",
            ],
        },
        {
            "title": "Multi-Agent Execution",
            "color": AMBER, "soft": SOFT_AMBER,
            "lines": [
                "Claude, Codex, and Gemini adapters",
                "Streaming subprocess output in real time",
                "Retry with backoff; Blocked state on failure",
                "25 built-in worker profiles; custom prompts",
            ],
        },
        {
            "title": "Git-Native Workflow",
            "color": INDIGO, "soft": SOFT_INDIGO,
            "lines": [
                "Auto-commit agent output on success",
                "Auto-open pull requests",
                "Isolated git worktrees per task",
                "Commits tab with full diff viewer",
            ],
        },
        {
            "title": "Live Chat + MCP",
            "color": ROSE, "soft": SOFT_ROSE,
            "lines": [
                "Interactive chat tabs per provider",
                "MCP stdio server for ticket tools",
                "Chat transcripts logged to tickets",
                "Per-ticket token consumption tracking",
            ],
        },
    ]

    def draw_card(x, y, w, h, card):
        # Card background
        c.setFillColor(white)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.6)
        c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
        # Accent bar on left
        c.setFillColor(card["color"])
        c.roundRect(x, y, 0.12 * inch, h, 3, stroke=0, fill=1)
        # Soft tint chip behind title
        c.setFillColor(card["soft"])
        chip_w = 0.3 * inch
        c.circle(x + 0.33 * inch, y + h - 0.28 * inch, 0.09 * inch, stroke=0, fill=1)
        c.setFillColor(card["color"])
        c.circle(x + 0.33 * inch, y + h - 0.28 * inch, 0.045 * inch, stroke=0, fill=1)
        # Title
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(x + 0.5 * inch, y + h - 0.31 * inch, card["title"])
        # Bullet lines
        c.setFont("Helvetica", 8.8)
        c.setFillColor(SLATE)
        line_y = y + h - 0.58 * inch
        for line in card["lines"]:
            c.setFillColor(card["color"])
            c.circle(x + 0.28 * inch, line_y + 3, 1.6, stroke=0, fill=1)
            c.setFillColor(SLATE)
            c.drawString(x + 0.42 * inch, line_y, line)
            line_y -= 0.21 * inch

    # Row 1
    draw_card(margin, cards_top - card_h, card_w, card_h, cards[0])
    draw_card(margin + card_w + card_gap, cards_top - card_h, card_w, card_h, cards[1])
    # Row 2
    row2_y = cards_top - card_h - card_gap - card_h
    draw_card(margin, row2_y, card_w, card_h, cards[2])
    draw_card(margin + card_w + card_gap, row2_y, card_w, card_h, cards[3])

    # --- Architecture / Stack strip ---
    strip_y = row2_y - 0.18 * inch - 0.75 * inch
    c.setFillColor(NAVY)
    c.roundRect(margin, strip_y, W - 2 * margin, 0.75 * inch, 6, stroke=0, fill=1)
    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin + 0.2 * inch, strip_y + 0.52 * inch, "Architecture")
    c.setFillColor(white)
    c.setFont("Helvetica", 9)
    col1_x = margin + 0.2 * inch
    col2_x = margin + 2.6 * inch
    col3_x = margin + 5.1 * inch
    c.drawString(col1_x, strip_y + 0.3 * inch, "Backend: Flask + Flask-SocketIO")
    c.drawString(col1_x, strip_y + 0.12 * inch, "Frontend: Vue 3 via CDN (no build)")
    c.drawString(col2_x, strip_y + 0.3 * inch, "Storage: flat files in .bullpen/")
    c.drawString(col2_x, strip_y + 0.12 * inch, "Transport: Socket.IO + REST")
    c.drawString(col3_x, strip_y + 0.3 * inch, "MCP: stdio JSON-RPC server")
    c.drawString(col3_x, strip_y + 0.12 * inch, "Tests: 465+ passing (pytest)")

    # --- Quick Start box ---
    qs_y = strip_y - 0.18 * inch - 0.85 * inch
    c.setFillColor(white)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.roundRect(margin, qs_y, W - 2 * margin, 0.85 * inch, 6, stroke=1, fill=1)
    # Left label column
    c.setFillColor(AMBER)
    c.roundRect(margin, qs_y, 0.12 * inch, 0.85 * inch, 3, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 0.25 * inch, qs_y + 0.6 * inch, "Quick Start")
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(margin + 0.25 * inch, qs_y + 0.43 * inch,
                 "Runs locally on :5000")
    c.drawString(margin + 0.25 * inch, qs_y + 0.28 * inch,
                 "Opens your browser")
    # Code block
    code_x = margin + 1.9 * inch
    code_w = W - margin - code_x - 0.2 * inch
    c.setFillColor(HexColor("#0B1220"))
    c.roundRect(code_x, qs_y + 0.1 * inch, code_w, 0.65 * inch, 4, stroke=0, fill=1)
    c.setFillColor(HexColor("#94E3D1"))
    c.setFont("Courier-Bold", 8.5)
    c.drawString(code_x + 0.15 * inch, qs_y + 0.55 * inch,
                 "$ pip install -r requirements.txt")
    c.drawString(code_x + 0.15 * inch, qs_y + 0.38 * inch,
                 "$ python3 bullpen.py --workspace /path/to/project")
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Courier", 7.5)
    c.drawString(code_x + 0.15 * inch, qs_y + 0.2 * inch,
                 "# authenticate Claude / Codex / Gemini CLIs first")

    # --- Footer ---
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawString(margin, 0.3 * inch,
                 "github.com/billroy/bullpen  ·  Cross-platform: macOS · Linux · Windows")
    c.drawRightString(W - margin, 0.3 * inch,
                      "Deploy: Docker · DigitalOcean · Fly.io Sprite")
    # Thin bottom accent
    c.setFillColor(TEAL)
    c.rect(0, 0, W, 3, stroke=0, fill=1)


def main():
    c = canvas.Canvas(OUT_PATH, pagesize=letter)
    c.setTitle("Bullpen — One-Page Summary")
    c.setAuthor("Bullpen")
    c.setSubject("AI agent team manager — overview")
    draw_page(c)
    c.showPage()
    c.save()
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
