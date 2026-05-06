import flet as ft
import random
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ── Flet 0.84+ compatibility patch ──────────────────────────
# Trong Flet >= 0.80, nhiều API cũ bị đổi tên (colors → Colors, icons → Icons, v.v.)
# Patch này đảm bảo app chạy trên cả phiên bản cũ lẫn mới.
if not hasattr(ft, "colors"):
    ft.colors = ft.Colors
if not hasattr(ft, "icons"):
    ft.icons = ft.Icons
# ─────────────────────────────────────────────────────────────

# ============================================================
# LOAD CÂU HỎI TỪ THƯ MỤC questions/
#
# Hỗ trợ 3 định dạng:
#   • .json  — cấu trúc đầy đủ
#   • .txt   — định dạng đơn giản, dễ viết tay
#   • .pdf   — trích xuất text rồi parse như .txt
#
# Yêu cầu thư viện PDF: pip install pdfplumber
# (hoặc pip install pypdf nếu không cài được pdfplumber)
# ============================================================


def _parse_txt(filepath: str) -> tuple[str, list[dict]]:
    """
    Đọc file .txt với định dạng:

        [Tên bộ đề]

        Câu hỏi đầu tiên?
        a. Đáp án A
        b. Đáp án B
        c. Đáp án C
        d. Đáp án D
        => a

        Câu hỏi thứ hai (Đúng/Sai)?
        a. Đúng
        b. Sai
        => b

    Quy tắc:
    - Dòng đầu tiên không trống là tên bộ đề (hoặc dùng [Tên bộ đề] trong ngoặc vuông)
    - Mỗi câu hỏi kết thúc bằng dòng "=> <chữ cái đáp án>" hoặc "=> <nội dung đáp án>"
    - Các options bắt đầu bằng a. / b. / c. / d.  (hoặc A. B. C. D.)
    - Dòng trống dùng để phân cách giữa các câu
    """
    with open(filepath, encoding="utf-8") as f:
        raw = f.read()

    lines = raw.splitlines()
    section_name = os.path.splitext(os.path.basename(filepath))[0]

    # Tìm tên bộ đề từ dòng [Tên] hoặc dòng đầu không trống
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^\[(.+)\]$", stripped)
        if m:
            section_name = m.group(1).strip()
        elif not stripped.startswith("="):
            section_name = stripped
        break

    questions: list[dict] = []
    current_q: str | None = None
    current_opts: list[tuple[str, str]] = []  # [(letter, text), ...]

    opt_re  = re.compile(r"^([a-dA-D])[.)]\s+(.+)$")
    ans_re  = re.compile(r"^=>\s*(.+)$")
    skip_re = re.compile(r"^[=\[#*-]{3,}")  # dòng trang trí / phân cách

    def flush(ans_raw: str):
        nonlocal current_q, current_opts
        if not current_q or not current_opts:
            current_q = None
            current_opts = []
            return
        opt_map = {letter.lower(): text for letter, text in current_opts}
        opts    = [text for _, text in current_opts]
        # ans_raw có thể là chữ cái ("a") hoặc nội dung đầy đủ
        ans_raw_stripped = ans_raw.strip()
        if ans_raw_stripped.lower() in opt_map:
            answer = opt_map[ans_raw_stripped.lower()]
        else:
            # khớp theo nội dung (bỏ qua prefix "a. ")
            ans_clean = re.sub(r"^[a-dA-D][.)]\s*", "", ans_raw_stripped)
            answer = ans_clean if ans_clean in opts else opts[0]
        questions.append({"question": current_q, "options": opts, "answer": answer})
        current_q = None
        current_opts = []

    for line in lines:
        line_s = line.strip()
        if not line_s or skip_re.match(line_s):
            continue

        m_ans = ans_re.match(line_s)
        if m_ans:
            flush(m_ans.group(1))
            continue

        m_opt = opt_re.match(line_s)
        if m_opt:
            if current_q is None:
                continue
            current_opts.append((m_opt.group(1), m_opt.group(2).strip()))
            continue

        # Nếu không phải option / answer → là câu hỏi mới
        # Bỏ qua dòng tên bộ đề (đã lấy rồi) và dòng số câu như "Câu 1:"
        clean = re.sub(r"^(câu\s+\d+\s*[:.]?\s*)", "", line_s, flags=re.IGNORECASE)
        if clean:
            current_q = clean

    return section_name, questions


def _parse_json(filepath: str) -> tuple[str, list[dict]]:
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    section_name = os.path.splitext(os.path.basename(filepath))[0]
    if isinstance(data, list):
        return section_name, data
    section_name = data.get("section", section_name)
    return section_name, data.get("questions", [])


def _extract_pdf_text(filepath: str) -> str:
    """Trích xuất toàn bộ text từ PDF, thử pdfplumber trước rồi fallback pypdf."""
    # Thử pdfplumber (cho kết quả tốt hơn với bảng, cột)
    try:
        import pdfplumber
        lines = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text:
                    lines.append(text)
        return "\n".join(lines)
    except ImportError:
        pass

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except ImportError:
        raise ImportError(
            "Cần cài thư viện PDF:\n"
            "  pip install pdfplumber\n"
            "hoặc\n"
            "  pip install pypdf"
        )


def _parse_pdf(filepath: str) -> tuple[str, list[dict]]:
    """Trích xuất text từ PDF rồi parse như file .txt."""
    raw_text = _extract_pdf_text(filepath)

    # Ghi text ra file tạm để debug nếu cần
    # with open(filepath + ".debug.txt", "w", encoding="utf-8") as f:
    #     f.write(raw_text)

    # Dùng section name từ tên file, _parse_txt sẽ tự đọc dòng đầu
    import tempfile, textwrap
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as tmp:
        tmp.write(raw_text)
        tmp_path = tmp.name

    try:
        section_name, questions = _parse_txt(tmp_path)
    finally:
        os.unlink(tmp_path)

    # Nếu _parse_txt không nhận ra tên bộ đề, dùng tên file PDF
    if not questions:
        return os.path.splitext(os.path.basename(filepath))[0], []

    # Nếu section_name trông giống số trang hoặc rác, dùng tên file
    if len(section_name) > 60 or section_name.isdigit():
        section_name = os.path.splitext(os.path.basename(filepath))[0]

    return section_name, questions


CHUONG_META = {
    1: ("Chương 1", "Đảng ra đời và lãnh đạo giành chính quyền (1930–1945)", "#64B5F6"),
    2: ("Chương 2", "Lãnh đạo kháng chiến, giải phóng dân tộc (1945–1975)", "#81C784"),
    3: ("Chương 3", "Lãnh đạo quá độ lên CNXH và Đổi mới (1975–nay)", "#FFB74D"),
    4: ("Ôn tập", "Bối cảnh xâm lược & phong trào yêu nước (1858–1929)", "#CE93D8"),
    5: ("Ôn tập", "Đảng ra đời & lãnh đạo giành chính quyền (1930–1945)", "#80DEEA"),
    6: ("Ôn tập", "Kháng chiến chống Pháp & chống Mỹ (1945–1975)", "#FFCC80"),
    11: ("Bổ sung C1", "Các mốc sự kiện bổ sung – Chương 1 (1919–1945)", "#F48FB1"),
    12: ("Bổ sung C2", "Các mốc sự kiện bổ sung – Chương 2 (1945–1975)", "#A5D6A7"),
    13: ("Bổ sung C3", "Các mốc sự kiện bổ sung – Chương 3 (1975–nay)", "#FFCC80"),
}


def load_chuong_data(subject_dir: str) -> dict[int, list[dict]]:
    """Đọc file chuong1.json, chuong2.json, bosungc1.json, ... trong subject_dir."""
    result = {}
    import re as _re
    for fname in sorted(os.listdir(subject_dir)):
        if not fname.endswith(".json"):
            continue
        m = _re.match(r"chuong(\d+)\.json", fname, _re.IGNORECASE)
        if m:
            ch_num = int(m.group(1))
        else:
            m = _re.match(r"bosungc(\d+).*\.json", fname, _re.IGNORECASE)
            if m:
                ch_num = 10 + int(m.group(1))  # bosungc1 → key 11, bosungc2 → 12, ...
            else:
                continue
        fpath = os.path.join(subject_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            qs = data if isinstance(data, list) else data.get("questions", [])
            for q in qs:
                q["chuong"] = ch_num
            result.setdefault(ch_num, []).extend(qs)
        except Exception as e:
            print(f"[WARN] Không đọc được {fname}: {e}")
    return result


def load_questions(dir_path: str) -> tuple[list[dict], list[dict]]:
    """Trả về (all_questions, sections)."""
    all_q: list[dict] = []
    sections: list[dict] = []

    if not os.path.isdir(dir_path):
        return all_q, sections

    parsers = {".json": _parse_json, ".txt": _parse_txt, ".pdf": _parse_pdf}

    for fname in sorted(os.listdir(dir_path)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in parsers:
            continue
        # Bỏ qua file hướng dẫn
        if fname.upper().startswith("HUONG_DAN"):
            continue
        fpath = os.path.join(dir_path, fname)
        try:
            section_name, qs = parsers[ext](fpath)
            for q in qs:
                q["section"] = section_name
            if qs:
                all_q.extend(qs)
                sections.append({
                    "key":   section_name,
                    "label": f"{section_name} ({len(qs)} câu)  [{fname}]",
                    "count": len(qs),
                })
        except Exception as e:
            print(f"[WARN] Không đọc được {fname}: {e}")

    return all_q, sections


# ============================================================
# THEME COLORS
# ============================================================
PRIMARY   = "#1565C0"
SECONDARY = "#1E88E5"
BG_DARK   = "#0A1628"
BG_CARD   = "#152032"
BG_CARD2  = "#1E3045"
WHITE     = "#FFFFFF"
GREEN     = "#2E7D32"
GREEN_L   = "#66BB6A"
RED       = "#C62828"
RED_L     = "#EF5350"
YELLOW    = "#F9A825"
YELLOW_L  = "#FFD54F"
GREY      = "#546E7A"
GREY_L    = "#78909C"
LABEL_A   = "#64B5F6"
LABEL_B   = "#81C784"
LABEL_C   = "#FFB74D"
LABEL_D   = "#CE93D8"
ACCENT    = "#00BCD4"

OPT_LETTERS = ["A", "B", "C", "D"]
OPT_COLORS  = [LABEL_A, LABEL_B, LABEL_C, LABEL_D]


# ============================================================
# MAIN APP
# ============================================================
def main(page: ft.Page):
    page.title = "Trắc Nghiệm Lịch Sử Đảng"
    page.bgcolor = BG_DARK
    page.window.width = 900
    page.window.height = 700
    def on_window_event(e):
        if e.data in ("close", "destroy"):
            os._exit(0)
    page.window.on_event = on_window_event
    page.window.prevent_close = False
    page.window.min_width = 700
    page.window.min_height = 500
    page.padding = 0
    page.fonts = {"Roboto": "https://fonts.gstatic.com/s/roboto/v32/KFOmCnqEu92Fr1Mu4mxK.woff2"}

    # Khám phá các thư mục môn học
    base_dir = os.path.dirname(os.path.abspath(__file__))
    subject_dirs = {}
    
    ignore_dirs = {".git", "__pycache__", ".vscode", "assets"}
    for d in os.listdir(base_dir):
        dp = os.path.join(base_dir, d)
        if os.path.isdir(dp) and d not in ignore_dirs and not d.startswith("."):
            valid_files = [f for f in os.listdir(dp) if f.endswith(('.json', '.txt', '.pdf')) and not f.upper().startswith("HUONG_DAN")]
            if valid_files:
                if d == "mangmaytinh":
                    label = "Mạng Máy Tính"
                elif d == "baochi":
                    label = "Báo chí Hán ngữ"
                else:
                    label = d.capitalize()
                subject_dirs[d] = {"path": dp, "label": label}
            
    if not subject_dirs:
        subject_dirs["questions"] = {"path": os.path.join(base_dir, "questions"), "label": "Mạng Máy Tính"}

    initial_subj = "mangmaytinh" if "mangmaytinh" in subject_dirs else sorted(list(subject_dirs.keys()))[0]
    initial_q, initial_s = load_questions(subject_dirs[initial_subj]["path"])
    initial_clo = load_chuong_data(subject_dirs[initial_subj]["path"])

    # ── STATE ──────────────────────────────────────────────
    state = {
        "subject": initial_subj,
        "questions_db": initial_q,
        "sections_db": initial_s,
        "questions": [],
        "current": 0,
        "score": 0,
        "selected": None,
        "answered": False,
        "results": [],          # list of {question, chosen, correct, ok}
        "mode": "all",          # "all" | "A" | "B" | "C"
        "num_questions": 20,
        "clo_data": initial_clo,   # {1: [...], 2: [...], 3: [...], 4: [...]} hoặc {}
        "shuffle": True,
    }

    # ── VIEWS ──────────────────────────────────────────────
    def show_welcome():
        page.clean()
        mode_ref = ft.Ref[ft.RadioGroup]()
        
        def on_subject_change(e):
            new_subj = e.control.value
            if new_subj != state["subject"]:
                state["subject"] = new_subj
                q, s = load_questions(subject_dirs[new_subj]["path"])
                state["questions_db"] = q
                state["sections_db"] = s
                state["clo_data"] = load_chuong_data(subject_dirs[new_subj]["path"])
                show_welcome()

        questions_db = state["questions_db"]
        sections_db = state["sections_db"]

        # Xây danh sách radio động từ SECTIONS
        badge_colors = [LABEL_A, LABEL_B, LABEL_C, "#CE93D8", "#80DEEA", "#FFCC80"]
        BATCH_SEC = 50

        # sec_range_rows: key → {"container": ft.Container, "state": {"value": "all"}}
        sec_range_rows = {}

        radio_col_controls = [
            ft.Radio(
                value="all",
                label=f"Tất cả ({len(questions_db)} câu)",
                label_style=ft.TextStyle(color=WHITE),
            )
        ]

        for i, sec in enumerate(sections_db):
            color = badge_colors[i % len(badge_colors)]
            radio_col_controls.append(
                ft.Radio(
                    value=sec["key"],
                    label=sec["label"],
                    label_style=ft.TextStyle(color=color),
                )
            )
            count = sec["count"]
            if count > BATCH_SEC:
                batch_state = {"value": "all"}
                chip_refs = {}

                range_opts = [("all", f"Tất cả ({count} câu)")]
                for s in range(0, count, BATCH_SEC):
                    e_idx = min(s + BATCH_SEC, count)
                    range_opts.append((str(s), f"Câu {s+1}–{e_idx}"))

                def _make_chip(rk, rl, bs=batch_state, cr=chip_refs, col=color):
                    def _on_click(e, k=rk):
                        bs["value"] = k
                        for ck, chip in cr.items():
                            chip.style = ft.ButtonStyle(
                                bgcolor=col if ck == k else BG_CARD2,
                                color=WHITE if ck == k else GREY_L,
                                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                text_style=ft.TextStyle(size=13),
                                shape=ft.RoundedRectangleBorder(radius=16),
                            )
                            chip.update()
                    chip = ft.ElevatedButton(
                        rl,
                        style=ft.ButtonStyle(
                            bgcolor=col if rk == "all" else BG_CARD2,
                            color=WHITE if rk == "all" else GREY_L,
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                            text_style=ft.TextStyle(size=13),
                            shape=ft.RoundedRectangleBorder(radius=16),
                        ),
                        on_click=_on_click,
                    )
                    cr[rk] = chip
                    return chip

                chips = [_make_chip(rk, rl) for rk, rl in range_opts]
                range_container = ft.Container(
                    visible=False,
                    padding=ft.padding.only(left=32, top=2, bottom=8),
                    content=ft.Column(spacing=4, controls=[
                        ft.Text("Phạm vi câu hỏi:", size=13, color=GREY_L),
                        ft.Row(spacing=6, controls=chips, wrap=True),
                    ]),
                )
                sec_range_rows[sec["key"]] = {"container": range_container, "state": batch_state, "chips": chip_refs}
                radio_col_controls.append(range_container)

        def _on_radio_change(e):
            new_val = e.control.value
            for sk, data in sec_range_rows.items():
                data["container"].visible = (sk == new_val)
                data["container"].update()

        clo_data = state["clo_data"]
        BATCH = 50
        clo_rows: list[dict] = []

        def make_batch_options(count: int):
            opts = [ft.dropdown.Option("all", f"Tất cả  ({count} câu)")]
            for s in range(0, count, BATCH):
                e = min(s + BATCH, count)
                opts.append(ft.dropdown.Option(str(s), f"Câu {s+1} – {e}"))
            return opts

        ch_icons = {1: ft.Icons.HISTORY_EDU, 2: ft.Icons.FLAG, 3: ft.Icons.ACCOUNT_BALANCE, 4: ft.Icons.AUTO_STORIES, 5: ft.Icons.MILITARY_TECH, 6: ft.Icons.EMOJI_EVENTS}

        if clo_data:
            for ch_num, (tag, label, color) in CHUONG_META.items():
                count = len(clo_data.get(ch_num, []))
                if count == 0:
                    continue
                dd = ft.Dropdown(
                    value="all",
                    options=make_batch_options(count),
                    bgcolor=BG_CARD2,
                    color=color,
                    border_color=color,
                    width=200,
                    text_size=15,
                    content_padding=ft.padding.symmetric(horizontal=10, vertical=6),
                )
                selected_ref = {"value": True}
                card_ref = ft.Ref[ft.Container]()

                def make_toggle(ch=ch_num, sr=selected_ref, cr=card_ref, col=color, d=dd):
                    def toggle(e):
                        sr["value"] = not sr["value"]
                        cr.current.border = ft.border.all(2, col if sr["value"] else GREY)
                        cr.current.bgcolor = BG_CARD if sr["value"] else BG_DARK
                        d.disabled = not sr["value"]
                        cr.current.update()
                        d.update()
                    return toggle

                card = ft.Container(
                    ref=card_ref,
                    bgcolor=BG_CARD,
                    border_radius=14,
                    border=ft.border.all(2, color),
                    padding=ft.padding.symmetric(horizontal=16, vertical=12),
                    on_click=make_toggle(),
                    ink=True,
                    content=ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=44, height=44,
                                border_radius=22,
                                bgcolor=f"{color}22",
                                content=ft.Icon(ch_icons.get(ch_num, ft.Icons.BOOK), color=color, size=22),
                                alignment=ft.Alignment(0, 0),
                            ),
                            ft.Column(
                                spacing=2, expand=True,
                                controls=[
                                    ft.Text(tag, size=16, weight=ft.FontWeight.BOLD, color=color),
                                    ft.Text(label, size=13, color=GREY_L),
                                ],
                            ),
                            dd,
                        ],
                    ),
                )
                clo_rows.append({"ch": ch_num, "selected_ref": selected_ref, "dd": dd, "card": card})

        num_files = len(sections_db)
        subtitle = (
            f"Tổng {len(questions_db)} câu từ {num_files} bộ đề"
            if num_files > 0
            else f"Không tìm thấy bộ đề nào trong thư mục {state['subject']}/"
        )
        
        subj_options = []
        for key, val in subject_dirs.items():
            subj_options.append(ft.dropdown.Option(key, val["label"]))

        def handle_start():
            selections = []
            if clo_data:
                selections = [(r["ch"], r["dd"].value) for r in clo_rows if r["selected_ref"]["value"]]
                if not selections:
                    dlg = ft.AlertDialog(
                        title=ft.Text("Chưa chọn chương"),
                        content=ft.Text("Vui lòng tick ít nhất một chương để bắt đầu ôn tập."),
                        actions=[ft.TextButton("OK", on_click=lambda e: (setattr(dlg, "open", False), page.update()))],
                    )
                    page.overlay.append(dlg)
                    dlg.open = True
                    page.update()
                    return
                
            if selections:
                start_quiz_clo(selections)
            else:
                if not questions_db:
                    dlg = ft.AlertDialog(
                        title=ft.Text("Không có câu hỏi"),
                        content=ft.Text("Không tìm thấy câu hỏi nào trong bộ đề này."),
                        actions=[ft.TextButton("OK", on_click=lambda e: (setattr(dlg, "open", False), page.update()))],
                    )
                    page.overlay.append(dlg)
                    dlg.open = True
                    page.update()
                    return
                radio_val = mode_ref.current.value
                batch_val = "all"
                if radio_val in sec_range_rows:
                    batch_val = sec_range_rows[radio_val]["state"]["value"]
                start_quiz(radio_val, 99999, batch_val)

        page.add(
            ft.Container(
                expand=True,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=24,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        ft.Container(height=24),
                        ft.Container(
                            width=90, height=90,
                            border_radius=45,
                            bgcolor=f"{SECONDARY}22",
                            border=ft.border.all(2, SECONDARY),
                            content=ft.Icon(ft.Icons.MENU_BOOK_ROUNDED, size=48, color=SECONDARY),
                            alignment=ft.Alignment(0, 0),
                        ),
                        ft.Text(
                            subject_dirs[state['subject']]["label"].upper(),
                            size=34,
                            weight=ft.FontWeight.BOLD,
                            color=WHITE,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(
                            bgcolor=f"{ACCENT}18",
                            border_radius=20,
                            border=ft.border.all(1, f"{ACCENT}55"),
                            padding=ft.padding.symmetric(horizontal=16, vertical=6),
                            content=ft.Text(subtitle, size=15, color=ACCENT),
                        ),
                        ft.Container(height=8),
                        ft.Container(
                            width=680,
                            padding=ft.padding.all(20),
                            border_radius=16,
                            bgcolor=BG_CARD,
                            content=ft.Column(
                                spacing=16,
                                controls=[
                                    ft.Text("Môn học", size=17, color=WHITE, weight=ft.FontWeight.BOLD),
                                    ft.Dropdown(
                                        value=state["subject"],
                                        options=subj_options,
                                        **( {"on_select": on_subject_change} if "on_select" in getattr(ft.Dropdown.__init__, "__code__").co_varnames else {"on_change": on_subject_change} ),
                                        bgcolor=BG_CARD2,
                                        color=WHITE,
                                        border_color=SECONDARY,
                                        focused_border_color=PRIMARY,
                                    ),
                                    ft.Divider(color=GREY, height=1),
                                    ft.Text("Chọn bộ đề", size=17, color=WHITE, weight=ft.FontWeight.BOLD),
                                    *(
                                        [
                                            ft.Text("Chọn chương & phạm vi câu hỏi:", size=14, color=GREY_L),
                                            ft.Text("Ôn theo chương:", size=14, color=WHITE, weight=ft.FontWeight.W_500),
                                            ft.Column(
                                                spacing=10,
                                                controls=[r["card"] for r in clo_rows],
                                            ),
                                            ft.Container(height=4),
                                            ft.Divider(color=GREY, height=1),
                                            ft.Container(height=2),
                                            ft.Text("Hoặc ôn theo bộ đề (nếu không chọn chương nào):", size=14, color=WHITE, weight=ft.FontWeight.W_500),
                                            ft.Container(
                                                height=220,
                                                content=ft.RadioGroup(
                                                    ref=mode_ref,
                                                    value="all",
                                                    on_change=_on_radio_change,
                                                    content=ft.Column(
                                                        spacing=4,
                                                        controls=radio_col_controls,
                                                        scroll=ft.ScrollMode.AUTO,
                                                    ),
                                                ),
                                            ),
                                        ]
                                        if clo_data else
                                        [
                                            ft.Text("Chọn bộ đề:", size=14, color=GREY_L),
                                            ft.Container(
                                                height=300,
                                                content=ft.RadioGroup(
                                                    ref=mode_ref,
                                                    value="all",
                                                    on_change=_on_radio_change,
                                                    content=ft.Column(
                                                        spacing=4,
                                                        controls=radio_col_controls,
                                                        scroll=ft.ScrollMode.AUTO,
                                                    ),
                                                ),
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            controls=[
                                ft.Checkbox(
                                    label="Xáo trộn câu hỏi",
                                    value=state["shuffle"],
                                    label_style=ft.TextStyle(color=WHITE, size=15),
                                    fill_color={ft.ControlState.SELECTED: SECONDARY, ft.ControlState.DEFAULT: GREY},
                                    check_color=WHITE,
                                    on_change=lambda e: state.update({"shuffle": e.control.value}),
                                ),
                            ],
                        ),
                        ft.ElevatedButton(
                            "  BẮT ĐẦU ÔN TẬP  ",
                            icon=ft.Icons.ROCKET_LAUNCH_ROUNDED,
                            disabled=len(questions_db) == 0,
                            style=ft.ButtonStyle(
                                bgcolor={ft.ControlState.DEFAULT: PRIMARY, ft.ControlState.HOVERED: SECONDARY},
                                color=WHITE,
                                padding=ft.padding.symmetric(horizontal=48, vertical=18),
                                shape=ft.RoundedRectangleBorder(radius=30),
                                text_style=ft.TextStyle(size=19, weight=ft.FontWeight.BOLD, letter_spacing=1),
                                elevation={"": 4, "hovered": 8},
                            ),
                            on_click=lambda _: handle_start(),
                        ),
                        ft.OutlinedButton(
                            "  Thoát  ",
                            icon=ft.Icons.POWER_SETTINGS_NEW_ROUNDED,
                            style=ft.ButtonStyle(
                                color=RED_L,
                                side=ft.BorderSide(1, RED_L),
                                padding=ft.padding.symmetric(horizontal=32, vertical=12),
                                shape=ft.RoundedRectangleBorder(radius=30),
                                text_style=ft.TextStyle(size=15),
                            ),
                            on_click=lambda _: page.window.close(),
                        ),
                        ft.Container(height=24),
                    ],
                ),
            )
        )
        page.update()

    def start_quiz(mode: str, num: int, batch: str = "all"):
        if mode == "chuong":
            pool = state["questions"][:]
        elif mode == "all":
            pool = state["questions_db"][:]
        else:
            pool = [q for q in state["questions_db"] if q["section"] == mode]
        if batch != "all":
            start_idx = int(batch)
            pool = pool[start_idx:start_idx + 50]
        if state["shuffle"]:
            random.shuffle(pool)
        chosen = pool[:min(num, len(pool))]
        state["questions"] = chosen
        state["current"] = 0
        state["score"] = 0
        state["selected"] = None
        state["answered"] = False
        state["results"] = []
        state["mode"] = mode
        state["num_questions"] = len(chosen)
        show_quiz()

    def start_retry_wrong():
        wrong_texts = {r["question"] for r in state["results"] if not r["ok"]}
        pool = [q for q in state["questions"] if q["question"] in wrong_texts]
        if not pool:
            return
        if state["shuffle"]:
            import random as _r
            _r.shuffle(pool)
        state["questions"] = pool
        state["current"] = 0
        state["score"] = 0
        state["selected"] = None
        state["answered"] = False
        state["results"] = []
        state["num_questions"] = len(pool)
        show_quiz()

    def start_quiz_clo(selections: list[tuple]):
        # selections: list of (ch_num, batch_value) e.g. (1, "0") or (1, "all")
        if not selections:
            selections = [(ch, "all") for ch in state["clo_data"].keys()]
        pool = []
        for ch_num, batch_val in selections:
            qs = state["clo_data"].get(ch_num, [])[:]
            if batch_val != "all":
                start = int(batch_val)
                qs = qs[start:start + 50]
            pool.extend(qs)
        if state["shuffle"]:
            random.shuffle(pool)
        state["questions"] = pool
        state["current"] = 0
        state["score"] = 0
        state["selected"] = None
        state["answered"] = False
        state["results"] = []
        state["mode"] = "chuong"
        state["num_questions"] = len(pool)
        show_quiz()

    # ── QUIZ SCREEN ─────────────────────────────────────────
    def show_quiz():
        page.clean()
        q_index = state["current"]
        q = state["questions"][q_index]
        total = state["num_questions"]
        opts = q["options"][:]
        random.shuffle(opts)
        effective_answer = q["answer"]

        state["selected"] = None
        state["answered"] = False

        progress_text = ft.Text(
            f"Câu {q_index + 1} / {total}",
            size=17,
            color=LABEL_A,
            weight=ft.FontWeight.BOLD,
        )
        score_text = ft.Text(
            f"Đúng: {state['score']}",
            size=17,
            color=GREEN,
            weight=ft.FontWeight.BOLD,
        )
        progress_bar = ft.ProgressBar(
            value=(q_index) / total,
            bgcolor=BG_CARD2,
            color=SECONDARY,
            height=6,
        )

        _badge_palette = [LABEL_A, LABEL_B, LABEL_C, "#CE93D8", "#80DEEA", "#FFCC80"]
        _ch_num = q.get("chuong")
        if _ch_num is not None and _ch_num in CHUONG_META:
            _badge_label = CHUONG_META[_ch_num][0]
            _badge_color = CHUONG_META[_ch_num][2]
        else:
            _sec_label = q.get("section", "")
            _sec_keys = [s["key"] for s in state["sections_db"]]
            _idx = _sec_keys.index(_sec_label) if _sec_label in _sec_keys else 0
            _badge_label = _sec_label
            _badge_color = _badge_palette[_idx % len(_badge_palette)]
        section_badge = ft.Container(
            content=ft.Text(_badge_label, size=13, color=BG_DARK, weight=ft.FontWeight.BOLD),
            bgcolor=_badge_color,
            padding=ft.padding.symmetric(horizontal=10, vertical=3),
            border_radius=20,
        )

        question_text = ft.Text(
            q["question"],
            size=20,
            color=WHITE,
            weight=ft.FontWeight.W_500,
        )

        feedback_row = ft.Row(visible=False, controls=[])
        next_btn = ft.ElevatedButton(
            "Câu tiếp theo →",
            visible=False,
            style=ft.ButtonStyle(
                bgcolor=SECONDARY,
                color=WHITE,
                padding=ft.padding.symmetric(horizontal=32, vertical=14),
                shape=ft.RoundedRectangleBorder(radius=24),
                text_style=ft.TextStyle(size=17, weight=ft.FontWeight.BOLD),
            ),
            on_click=lambda _: next_question(),
        )
        skip_btn = ft.OutlinedButton(
            "Bỏ qua →",
            visible=not state["answered"],
            style=ft.ButtonStyle(
                color=GREY_L,
                side=ft.BorderSide(1, GREY),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=24),
                text_style=ft.TextStyle(size=15),
            ),
            on_click=lambda _: next_question(),
        )
        prev_btn = ft.OutlinedButton(
            "← Câu trước",
            visible=q_index > 0,
            style=ft.ButtonStyle(
                color=GREY_L,
                side=ft.BorderSide(1, GREY),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=24),
                text_style=ft.TextStyle(size=15),
            ),
            on_click=lambda _: prev_question(),
        )

        option_buttons = []

        def select_option(chosen: str):
            if state["answered"]:
                return
            state["answered"] = True
            state["selected"] = chosen
            correct = effective_answer
            ok = chosen == correct

            if ok:
                state["score"] += 1

            state["results"].append({
                "question": q["question"],
                "chosen": chosen,
                "correct": correct,
                "ok": ok,
            })

            # Update button colors
            for btn, opt in zip(option_buttons, opts):
                label_text = btn.content.controls[0]
                if opt == correct:
                    btn.bgcolor = "#1B5E20"
                    btn.border = ft.border.all(2.5, GREEN_L)
                    label_text.color = WHITE
                elif opt == chosen and not ok:
                    btn.bgcolor = "#B71C1C"
                    btn.border = ft.border.all(2.5, RED_L)
                    label_text.color = WHITE
                else:
                    btn.bgcolor = BG_CARD2
                    btn.border = ft.border.all(1, BG_CARD2)
                    label_text.color = GREY_L
                btn.update()

            # Feedback
            correct_display = correct
            if ok:
                feedback_row.controls = [
                    ft.Container(
                        bgcolor=f"{GREEN}22", border_radius=10,
                        border=ft.border.all(1, GREEN_L),
                        padding=ft.padding.symmetric(horizontal=14, vertical=8),
                        content=ft.Row(spacing=8, controls=[
                            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=GREEN_L, size=22),
                            ft.Text("Chính xác!", color=GREEN_L, size=17, weight=ft.FontWeight.BOLD),
                        ]),
                    )
                ]
            else:
                feedback_row.controls = [
                    ft.Container(
                        bgcolor=f"{RED}22", border_radius=10,
                        border=ft.border.all(1, RED_L),
                        padding=ft.padding.symmetric(horizontal=14, vertical=8),
                        content=ft.Row(spacing=8, controls=[
                            ft.Icon(ft.Icons.CANCEL_ROUNDED, color=RED_L, size=22),
                            ft.Text("Sai!  Đáp án đúng:", color=RED_L, size=17, weight=ft.FontWeight.BOLD),
                            ft.Text(correct_display, color=YELLOW_L, size=16),
                        ]),
                    )
                ]
            feedback_row.visible = True
            feedback_row.update()
            next_btn.visible = True
            next_btn.update()
            skip_btn.visible = False
            skip_btn.update()

        for idx, opt in enumerate(opts):
            btn = ft.Container(
                bgcolor=BG_CARD,
                border_radius=14,
                padding=ft.padding.symmetric(horizontal=14, vertical=13),
                border=ft.border.all(1.5, f"{GREY}55"),
                content=ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(opt, size=17, color=WHITE, expand=True),
                    ],
                ),
                on_click=lambda e, o=opt: select_option(o),
                ink=True,
                animate=ft.Animation(120, ft.AnimationCurve.EASE_OUT) if hasattr(ft, "Animation") else ft.animation.Animation(120, ft.AnimationCurve.EASE_OUT),
            )
            option_buttons.append(btn)

        def next_question():
            if state["current"] + 1 >= state["num_questions"]:
                show_result()
            else:
                state["current"] += 1
                show_quiz()

        def prev_question():
            if state["current"] > 0:
                # Xóa kết quả câu hiện tại nếu đã trả lời (để tránh tính điểm 2 lần)
                if state["answered"]:
                    last = state["results"].pop() if state["results"] else None
                    if last and last["ok"]:
                        state["score"] = max(0, state["score"] - 1)
                state["current"] -= 1
                show_quiz()

        page.add(
            ft.Container(
                expand=True,
                padding=ft.padding.all(20),
                content=ft.Column(
                    expand=True,
                    spacing=0,
                    controls=[
                        # Header
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Row(controls=[
                                    ft.OutlinedButton(
                                        "Quay về",
                                        icon=ft.Icons.ARROW_BACK,
                                        style=ft.ButtonStyle(
                                            color=GREY,
                                            side=ft.BorderSide(1, GREY),
                                            padding=ft.padding.symmetric(horizontal=12, vertical=6),
                                            shape=ft.RoundedRectangleBorder(radius=20),
                                        ),
                                        on_click=lambda _: show_welcome(),
                                    ),
                                    ft.Container(width=8),
                                    progress_text,
                                ]),
                                score_text,
                            ],
                        ),
                        ft.Container(height=6),
                        progress_bar,
                        ft.Container(height=16),
                        # Card
                        ft.Container(
                            expand=True,
                            bgcolor=BG_CARD,
                            border_radius=18,
                            padding=ft.padding.all(24),
                            content=ft.Column(
                                expand=True,
                                spacing=16,
                                controls=[
                                    ft.Row(controls=[section_badge]),
                                    question_text,
                                    ft.Divider(color=BG_CARD2, height=1),
                                    ft.Column(
                                        spacing=10,
                                        controls=option_buttons,
                                        scroll=ft.ScrollMode.AUTO,
                                        expand=True,
                                    ),
                                    feedback_row,
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        controls=[
                                            prev_btn,
                                            ft.Row(spacing=10, controls=[skip_btn, next_btn]),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )
        )
        page.update()

    # ── RESULT SCREEN ────────────────────────────────────────
    def show_result():
        page.clean()
        total = state["num_questions"]
        score = state["score"]
        pct = score / total * 100
        results = state["results"]

        if pct >= 80:
            grade_color = GREEN
            grade_text = "Xuất sắc! 🎉"
            grade_icon = ft.Icons.STAR_ROUNDED
        elif pct >= 60:
            grade_color = YELLOW
            grade_text = "Khá tốt!"
            grade_icon = ft.Icons.THUMB_UP_ROUNDED
        else:
            grade_color = RED
            grade_text = "Cần ôn tập thêm"
            grade_icon = ft.Icons.MENU_BOOK_ROUNDED

        # Build review list
        review_items = []
        for i, r in enumerate(results):
            icon = ft.Icons.CHECK_CIRCLE if r["ok"] else ft.Icons.CANCEL
            icon_color = GREEN if r["ok"] else RED
            _colors = ft.Colors if hasattr(ft, "Colors") else ft.colors
            bg = _colors.with_opacity(0.07, GREEN) if r["ok"] else _colors.with_opacity(0.07, RED)
            item = ft.Container(
                bgcolor=bg,
                border_radius=10,
                padding=ft.padding.all(12),
                content=ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(icon, color=icon_color, size=18),
                                ft.Text(
                                    f"Câu {i+1}: {r['question'][:80]}{'...' if len(r['question']) > 80 else ''}",
                                    size=15,
                                    color=WHITE,
                                    expand=True,
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.Text("Bạn chọn:", size=14, color=GREY),
                                ft.Text(
                                    r["chosen"],
                                    size=14,
                                    color=GREEN if r["ok"] else RED,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ] if r["ok"] else [
                                ft.Text("Bạn chọn:", size=14, color=GREY),
                                ft.Text(r["chosen"], size=14, color=RED),
                                ft.Text("  |  Đúng:", size=14, color=GREY),
                                ft.Text(r["correct"], size=14, color=GREEN, weight=ft.FontWeight.BOLD),
                            ],
                        ),
                    ],
                ),
            )
            review_items.append(item)

        page.add(
            ft.Container(
                expand=True,
                padding=ft.padding.all(20),
                content=ft.Column(
                    expand=True,
                    spacing=16,
                    controls=[
                        # Score card
                        ft.Container(
                            bgcolor=BG_CARD,
                            border_radius=18,
                            padding=ft.padding.all(24),
                            content=ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=10,
                                controls=[
                                    ft.Icon(grade_icon, size=52, color=grade_color),
                                    ft.Text(grade_text, size=26, color=grade_color, weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        f"{score} / {total}",
                                        size=48,
                                        color=WHITE,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        f"{pct:.0f}% câu đúng",
                                        size=19,
                                        color=LABEL_A,
                                    ),
                                    ft.ProgressBar(
                                        value=pct / 100,
                                        bgcolor=BG_CARD2,
                                        color=grade_color,
                                        height=8,
                                        width=300,
                                    ),
                                ],
                            ),
                        ),
                        # Action buttons
                        ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=12,
                            controls=[
                                ft.OutlinedButton(
                                    "Thi lại",
                                    icon=ft.Icons.REFRESH,
                                    style=ft.ButtonStyle(
                                        color=SECONDARY,
                                        side=ft.BorderSide(1.5, SECONDARY),
                                        padding=ft.padding.symmetric(horizontal=24, vertical=12),
                                        shape=ft.RoundedRectangleBorder(radius=24),
                                    ),
                                    on_click=lambda _: start_quiz(state["mode"], state["num_questions"]),
                                ),
                                *(
                                    [ft.ElevatedButton(
                                        f"Làm lại câu sai ({total - score})",
                                        icon=ft.Icons.REPLAY_CIRCLE_FILLED_ROUNDED,
                                        style=ft.ButtonStyle(
                                            bgcolor=RED,
                                            color=WHITE,
                                            padding=ft.padding.symmetric(horizontal=24, vertical=12),
                                            shape=ft.RoundedRectangleBorder(radius=24),
                                        ),
                                        on_click=lambda _: start_retry_wrong(),
                                    )]
                                    if score < total else []
                                ),
                                ft.ElevatedButton(
                                    "Về trang chủ",
                                    icon=ft.Icons.HOME,
                                    style=ft.ButtonStyle(
                                        bgcolor=PRIMARY,
                                        color=WHITE,
                                        padding=ft.padding.symmetric(horizontal=24, vertical=12),
                                        shape=ft.RoundedRectangleBorder(radius=24),
                                    ),
                                    on_click=lambda _: show_welcome(),
                                ),
                            ],
                        ),
                        # Review
                        ft.Text("Chi tiết kết quả", size=18, color=WHITE, weight=ft.FontWeight.BOLD),
                        ft.Container(
                            expand=True,
                            content=ft.Column(
                                controls=review_items,
                                spacing=8,
                                scroll=ft.ScrollMode.AUTO,
                                expand=True,
                            ),
                        ),
                    ],
                ),
            )
        )
        page.update()

    show_welcome()


if "PORT" in os.environ:
    # Chạy trên Railway → web server cho điện thoại
    port = int(os.environ["PORT"])
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")
else:
    # Chạy local → cửa sổ Flet desktop
    ft.app(target=main)
