import streamlit as st
import requests
import google.generativeai as genai
from datetime import datetime
import json

# ── ページ設定 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="こうかん日記 📔",
    page_icon="📔",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif !important; }
.stButton > button {
    border-radius: 24px !important;
    font-size: 17px !important;
    font-weight: 700 !important;
    padding: 12px 20px !important;
}
.stTextArea > div > textarea {
    font-size: 18px !important;
    line-height: 1.9 !important;
    border-radius: 14px !important;
    font-family: 'Noto Sans JP', sans-serif !important;
}
.stTextInput > div > input {
    font-size: 24px !important;
    letter-spacing: 10px !important;
    text-align: center !important;
    border-radius: 14px !important;
}
</style>
""", unsafe_allow_html=True)

# ── 定数 ────────────────────────────────────────────────────────────────────
MOODS = [
    ("😊", "うれしい"), ("😄", "たのしい"), ("😐", "ふつう"),
    ("😢", "かなしい"), ("😠", "むかむか"), ("😴", "つかれた"),
]
STAMPS = ["❤️", "⭐", "🌸", "🎉", "🌈", "🍀", "🎵", "🦋", "🌟", "🐣", "👏", "💪"]

def fmt_date(iso_str):
    if not iso_str:
        return ""
    try:
        d = datetime.fromisoformat(iso_str[:10])
        days = ["月", "火", "水", "木", "金", "土", "日"]
        return f"{d.year}年{d.month}月{d.day}日（{days[d.weekday()]}）"
    except Exception:
        return iso_str[:10]

# ── Notion API 直接呼び出し ──────────────────────────────────────────────────
NOTION_API = "https://api.notion.com/v1"
NOTION_VER  = "2022-06-28"

def notion_headers():
    return {
        "Authorization":  f"Bearer {st.secrets['NOTION_TOKEN']}",
        "Content-Type":   "application/json",
        "Notion-Version": NOTION_VER,
    }

def _rt(text: str):
    return [{"text": {"content": text[:2000]}}]

def fetch_entries():
    db_id = st.secrets["NOTION_DB_ID"]
    resp = requests.post(
        f"{NOTION_API}/databases/{db_id}/query",
        headers=notion_headers(),
        json={"sorts": [{"property": "日付", "direction": "descending"}]},
    )
    resp.raise_for_status()
    entries = []
    for page in resp.json()["results"]:
        p = page["properties"]

        def get_rt(key):
            arr = p.get(key, {}).get("rich_text", [])
            return arr[0]["text"]["content"] if arr else ""

        entries.append({
            "id":             page["id"],
            "date":           (p.get("日付", {}).get("date") or {}).get("start", ""),
            "author":         (p.get("作者", {}).get("select") or {}).get("name", ""),
            "mood":           get_rt("気持ち"),
            "text":           get_rt("内容"),
            "parent_comment": get_rt("親のコメント"),
            "stamps":         json.loads(get_rt("スタンプ") or "[]"),
        })
    return entries

def add_entry(author: str, mood: str, text: str):
    db_id = st.secrets["NOTION_DB_ID"]
    now   = datetime.now()
    requests.post(
        f"{NOTION_API}/pages",
        headers=notion_headers(),
        json={
            "parent": {"database_id": db_id},
            "properties": {
                "名前":         {"title":     _rt(f"{now.strftime('%Y/%m/%d')} {author}")},
                "日付":         {"date":      {"start": now.isoformat()}},
                "作者":         {"select":    {"name": author}},
                "気持ち":       {"rich_text": _rt(mood)},
                "内容":         {"rich_text": _rt(text)},
                "親のコメント": {"rich_text": _rt("")},
                "スタンプ":     {"rich_text": _rt("[]")},
            },
        },
    ).raise_for_status()

def save_reply(page_id: str, comment: str, stamps: list):
    requests.patch(
        f"{NOTION_API}/pages/{page_id}",
        headers=notion_headers(),
        json={
            "properties": {
                "親のコメント": {"rich_text": _rt(comment)},
                "スタンプ":     {"rich_text": _rt(json.dumps(stamps, ensure_ascii=False))},
            }
        },
    ).raise_for_status()

# ── Gemini ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_model():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model_name = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash-preview-04-17")
    return genai.GenerativeModel(model_name)

# ── セッション状態の初期化 ────────────────────────────────────────────────
_defaults = {
    "screen":        "home",   # home / pin / list / write / view
    "mode":          None,     # "child" / "parent"
    "current_entry": None,
    "entries_cache": None,
    "selected_mood": "",
    "ai_active":     False,
    "ai_history":    [],       # [{"role": "assistant"/"user", "content": str}]
    "ai_draft":      "",
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

def go(screen: str):
    st.session_state.screen = screen
    st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# ホーム画面
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.screen == "home":
    st.markdown("""
    <div style='text-align:center; padding:56px 0 28px'>
      <div style='font-size:84px; filter:drop-shadow(0 6px 12px rgba(0,0,0,0.12))'>📔</div>
      <h1 style='font-size:28px; letter-spacing:4px; color:#3D2B1F; margin:10px 0 4px'>こうかん日記</h1>
      <p style='color:#bbb; font-size:15px; margin:0'>きょうのことを かこう！</p>
    </div>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        if st.button("👧  こどもモード", use_container_width=True):
            st.session_state.mode = "child"
            st.session_state.entries_cache = None
            go("list")

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("👨‍👩‍👧  おやモード", use_container_width=True):
            st.session_state.mode = "parent"
            go("pin")

# ════════════════════════════════════════════════════════════════════════════
# PIN 画面
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "pin":
    st.markdown("""
    <div style='text-align:center; padding:32px 0 8px'>
      <div style='font-size:56px'>🔒</div>
      <h2 style='color:#3D2B1F'>あんしょうばんごう</h2>
      <p style='color:#aaa; font-size:15px'>4けたのばんごうを入れてね</p>
    </div>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        pin = st.text_input(
            "", type="password", max_chars=4,
            placeholder="••••", label_visibility="collapsed",
        )
        st.markdown("<br>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("← もどる", use_container_width=True):
                go("home")
        with col_b:
            if st.button("→ はいる", use_container_width=True):
                correct = st.secrets.get("PARENT_PIN", "1234")
                if pin == correct:
                    st.session_state.entries_cache = None
                    go("list")
                else:
                    st.error("❌ まちがいだよ！もういちど")

# ════════════════════════════════════════════════════════════════════════════
# 一覧画面
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "list":
    mode = st.session_state.mode

    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown("## 📔 こうかん日記")
    with col2:
        if st.button("もどる"):
            st.session_state.entries_cache = None
            go("home")

    if st.button("✏️  日記を書く", use_container_width=True):
        st.session_state.selected_mood = ""
        st.session_state.ai_active     = False
        st.session_state.ai_history    = []
        st.session_state.ai_draft      = ""
        # テキストエリアのキーをリセット
        if "write_text_field" in st.session_state:
            del st.session_state["write_text_field"]
        go("write")

    st.markdown("---")

    # エントリ読み込み（キャッシュあれば再利用）
    if st.session_state.entries_cache is None:
        with st.spinner("よみこみ中... 📖"):
            try:
                st.session_state.entries_cache = fetch_entries()
            except Exception as e:
                st.error(f"Notionの読み込みに失敗しました: {e}")
                st.stop()

    entries = st.session_state.entries_cache

    if not entries:
        st.markdown("""
        <div style='text-align:center; color:#ccc; padding:56px 20px'>
          <div style='font-size:56px'>📝</div>
          <p style='font-size:17px; margin-top:12px; line-height:1.8'>
            まだ日記がないよ！<br>はじめて書いてみよう
          </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for e in entries:
            border      = "#FF8FAB" if e["author"] == "child" else "#6BCB77"
            author_lbl  = "👧 こども" if e["author"] == "child" else "👨‍👩‍👧 おや"
            preview     = (e["text"][:30] + "…") if len(e["text"]) > 30 else e["text"]
            stamps_str  = " ".join(e["stamps"]) if e["stamps"] else ""
            reply_badge = "&nbsp;💚 <b>へんじあり</b>" if e["parent_comment"] else ""

            st.markdown(f"""
            <div style='background:#fff; border-radius:16px; padding:16px 18px; margin:8px 0;
                        box-shadow:0 2px 10px rgba(0,0,0,0.07); border-left:5px solid {border}'>
              <div style='font-size:12px; color:#bbb; margin-bottom:4px'>
                {fmt_date(e["date"])} &nbsp;·&nbsp; {author_lbl}
              </div>
              <div style='font-size:18px; font-weight:700; margin:2px 0'>
                {e["mood"]} {preview or "（なし）"}
              </div>
              <div style='font-size:20px; margin-top:4px'>
                {stamps_str}{reply_badge}
              </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("よむ →", key=f"read_{e['id']}"):
                st.session_state.current_entry = dict(e)
                go("view")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 さいしんにする", use_container_width=True):
        st.session_state.entries_cache = None
        st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# 書く画面
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "write":
    mode = st.session_state.mode

    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown("## ✏️ 日記を書く")
    with col2:
        if st.button("もどる"):
            go("list")

    # ─ 気持ち選択 ─────────────────────────────────────────────────────────
    st.markdown("### きょうのきもち 🌈")
    mood_cols = st.columns(6)
    for i, (emoji, label) in enumerate(MOODS):
        with mood_cols[i]:
            is_selected = st.session_state.selected_mood == emoji
            btn_label   = f"{emoji}\n{label}"
            if st.button(btn_label, key=f"mood_{emoji}"):
                st.session_state.selected_mood = "" if is_selected else emoji
                st.rerun()

    if st.session_state.selected_mood:
        st.success(f"えらんだきもち：{st.session_state.selected_mood}")

    st.markdown("---")

    # ─ AI チャット中 ──────────────────────────────────────────────────────
    if st.session_state.ai_active:
        st.markdown("### 🤖 きもちをことばにしよう")
        st.caption("AIといっしょに、きょうのことをことばにしよう ✨")
        st.markdown("---")

        # 会話履歴を表示
        for msg in st.session_state.ai_history:
            if msg["role"] == "assistant":
                st.markdown(
                    f"<div style='background:#FFF0F5; border-radius:12px; padding:12px 16px; "
                    f"margin:8px 0; font-size:17px'>🤖 {msg['content']}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='background:#F0FFF4; border-radius:12px; padding:12px 16px; "
                    f"margin:8px 0; font-size:17px; text-align:right'>👧 {msg['content']}</div>",
                    unsafe_allow_html=True,
                )

        # 4往復以上したらまとめボタンを表示
        user_turns = sum(1 for m in st.session_state.ai_history if m["role"] == "user")
        if user_turns >= 4:
            if st.button("📝 まとめてもらう！", use_container_width=True):
                with st.spinner("まとめ中... ✨"):
                    history_text = "\n".join(
                        f"{'AI' if m['role'] == 'assistant' else 'こども'}: {m['content']}"
                        for m in st.session_state.ai_history
                    )
                    prompt = f"""以下のAIと子ども（8歳）の会話をもとに、子どもが書いたような自然な日記文を作ってください。

会話:
{history_text}

条件:
- ひらがな・カタカナを中心に、やさしい言葉で
- 3〜5文程度
- 「きょう〜」で始める
- 子どもらしい表現を使う
- 「」や解説は一切不要。日記の文章だけ出力してください"""
                    resp = get_model().generate_content(prompt)
                    st.session_state.ai_draft  = resp.text.strip()
                    st.session_state.ai_active = False
                    st.rerun()

        user_input = st.text_input(
            "こたえてね →",
            key="ai_input_field",
            label_visibility="collapsed",
            placeholder="ここに書いてね...",
        )
        col_send, col_stop = st.columns(2)
        with col_send:
            if st.button("おくる ▶", use_container_width=True) and user_input.strip():
                st.session_state.ai_history.append(
                    {"role": "user", "content": user_input.strip()}
                )
                with st.spinner("かんがえてる..."):
                    history_text = "\n".join(
                        f"{'AI' if m['role'] == 'assistant' else 'こども'}: {m['content']}"
                        for m in st.session_state.ai_history
                    )
                    prompt = f"""あなたは小学2年生（8歳）の子どもが日記を書くのを助けるやさしいAIです。

これまでの会話:
{history_text}

次の質問をしてください。
ルール: ひらがな・カタカナ中心、短い文（2文以内）、絵文字1つ、質問は1つだけ。"""
                    resp = get_model().generate_content(prompt)
                    st.session_state.ai_history.append(
                        {"role": "assistant", "content": resp.text.strip()}
                    )
                st.rerun()
        with col_stop:
            if st.button("やめる ✕", use_container_width=True):
                st.session_state.ai_active = False
                st.rerun()

    # ─ AI ドラフト確認 ────────────────────────────────────────────────────
    elif st.session_state.ai_draft:
        st.markdown("### 🤖 AIがまとめてくれたよ！")
        st.markdown(
            f"<div style='background:#FFF8E1; border-radius:14px; padding:18px; "
            f"font-size:18px; line-height:2; white-space:pre-wrap'>{st.session_state.ai_draft}</div>",
            unsafe_allow_html=True,
        )
        col_use, col_redo = st.columns(2)
        with col_use:
            if st.button("✅ このぶんをつかう", use_container_width=True):
                st.session_state["write_text_field"] = st.session_state.ai_draft
                st.session_state.ai_draft = ""
                st.rerun()
        with col_redo:
            if st.button("✏️ じぶんでかきなおす", use_container_width=True):
                st.session_state.ai_draft = ""
                st.rerun()

    # ─ 通常テキスト入力 ────────────────────────────────────────────────────
    else:
        st.markdown("### きょうのできごと 📝")
        placeholder_text = (
            "きょうはどんなことがあったかな？\nたのしかったこと、あったことを書こう！"
            if mode == "child"
            else "コメントや返事を書こう…"
        )
        st.text_area(
            "",
            key="write_text_field",
            placeholder=placeholder_text,
            height=160,
            label_visibility="collapsed",
        )

        if mode == "child":
            if st.button("🤖  きもちをたすけて！", use_container_width=True):
                seed = st.session_state.get("write_text_field", "").strip()
                intro = f"子どもが「{seed}」と書いていた。" if seed else "子どもはまだ何も書いていない。"
                with st.spinner("AIが準備中... 🌟"):
                    prompt = f"""あなたは小学2年生（8歳）の子どもが日記を書くのを助けるやさしいAIです。
{intro}
子どもが気持ちを言葉にできるよう、やさしく最初の質問をしてください。

ルール:
- ひらがな・カタカナ中心。むずかしい漢字は使わない
- 短い文で話しかける（2文以内）
- 絵文字を1つ使う
- 質問は1つだけ
- 子どもの気持ちを否定しない"""
                    resp = get_model().generate_content(prompt)
                    st.session_state.ai_history = [
                        {"role": "assistant", "content": resp.text.strip()}
                    ]
                    st.session_state.ai_active = True
                st.rerun()

        st.markdown("---")
        if st.button("📔  ほぞんする", use_container_width=True):
            final_text = st.session_state.get("write_text_field", "").strip()
            if not st.session_state.selected_mood and not final_text:
                st.error("きもちか、できごとを書いてね！")
            else:
                with st.spinner("ほぞん中... 💾"):
                    try:
                        add_entry(
                            author=mode,
                            mood=st.session_state.selected_mood,
                            text=final_text,
                        )
                    except Exception as e:
                        st.error(f"ほぞんに失敗しました: {e}")
                        st.stop()
                st.session_state.entries_cache = None
                st.success("📔 ほぞんできたよ！")
                go("list")

# ════════════════════════════════════════════════════════════════════════════
# 見る画面
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "view":
    entry = st.session_state.current_entry
    mode  = st.session_state.mode

    if st.button("← もどる"):
        go("list")

    author_lbl = "👧 こどもが書いた" if entry["author"] == "child" else "👨‍👩‍👧 おやが書いた"
    st.markdown(f"## {fmt_date(entry['date'])}")
    st.caption(author_lbl)

    if entry["mood"]:
        st.markdown(
            f"<div style='text-align:center; font-size:72px; margin:16px 0'>{entry['mood']}</div>",
            unsafe_allow_html=True,
        )

    if entry["text"]:
        st.markdown(
            f"<div style='background:#fff; border-radius:16px; padding:20px; margin:12px 0; "
            f"box-shadow:0 2px 10px rgba(0,0,0,0.07); font-size:18px; line-height:2; "
            f"white-space:pre-wrap'>{entry['text']}</div>",
            unsafe_allow_html=True,
        )

    if entry["stamps"]:
        st.markdown("**💌 リアクション**")
        st.markdown(
            f"<div style='font-size:34px; margin:8px 0'>{' '.join(entry['stamps'])}</div>",
            unsafe_allow_html=True,
        )

    if entry["parent_comment"]:
        st.markdown(
            f"<div style='background:#F0FFF4; border-radius:16px; padding:18px; margin:16px 0; "
            f"border-left:4px solid #6BCB77'>"
            f"<div style='color:#6BCB77; font-weight:700; margin-bottom:8px; font-size:14px'>💚 おやより</div>"
            f"<div style='font-size:17px; line-height:1.9; white-space:pre-wrap'>{entry['parent_comment']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif entry["author"] == "child" and mode == "child":
        st.caption("おやからのへんじを まってね 💌")

    # ─ 親の返事セクション ─────────────────────────────────────────────────
    if mode == "parent" and entry["author"] == "child":
        st.markdown("---")
        st.markdown("### 💌 へんじをする")

        st.markdown("**スタンプをおくる**")
        stamp_cols = st.columns(6)
        for i, s in enumerate(STAMPS):
            with stamp_cols[i % 6]:
                if st.button(s, key=f"stamp_{i}"):
                    new_stamps = entry["stamps"] + [s]
                    save_reply(entry["id"], entry["parent_comment"], new_stamps)
                    st.session_state.current_entry["stamps"] = new_stamps
                    st.session_state.entries_cache = None
                    st.rerun()

        st.markdown("**コメントを書く**")
        comment = st.text_area(
            "",
            value=entry["parent_comment"],
            placeholder="コメントを書こう…",
            height=110,
            label_visibility="collapsed",
            key="parent_comment_field",
        )
        if st.button("💚  コメントをほぞんする", use_container_width=True):
            with st.spinner("ほぞん中..."):
                save_reply(entry["id"], comment, entry["stamps"])
            st.session_state.current_entry["parent_comment"] = comment
            st.session_state.entries_cache = None
            st.success("✅ ほぞんしました！")
            st.rerun()
