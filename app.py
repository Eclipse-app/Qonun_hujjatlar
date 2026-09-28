import json, random, time, pathlib, html, re, datetime as dt
import streamlit as st
import streamlit.components.v1 as components
import os
import requests

try:
    from bs4 import BeautifulSoup  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - graceful fallback when dependency is absent
    class BeautifulSoup:  # minimal fallback used only for safe no-op parsing
        def __init__(self, *args, **kwargs):
            self.text = ""

        def __iter__(self):
            return iter(())

        def __getitem__(self, key):
            return []

        def decompose(self):
            pass

        def get_text(self, *args, **kwargs):
            return ""

st.set_page_config(page_title="HujjatUstasi", page_icon="⚖️", layout="wide")
B = pathlib.Path(__file__).parent
DOCS = json.loads((B / "documents.json").read_text(encoding="utf-8"))
PF = B / "progress.json"
TUR = {"VM": "Vazirlar Mahkamasi qarori", "AV": "Adliya vazirligi buyrug'i", "PQ": "Prezident qarori",
       "PF": "Prezident farmoni", "BQ": "Bojxona qo'mitasi qarori", "BK": "Bojxona kodeksi", "Q": "Qonun"}
COL = {"Vazirlar Mahkamasi qarori": "#6366f1", "Adliya vazirligi buyrug'i": "#0ea5e9", "Prezident qarori": "#f59e0b",
       "Prezident farmoni": "#ef4444", "Bojxona qo'mitasi qarori": "#10b981", "Bojxona kodeksi": "#8b5cf6", "Qonun": "#ec4899"}
for d in DOCS:
    r = d["raqam"]
    d["tur"] = TUR["Q"] if (r[0] == "O" and "RQ" in r) else TUR.get(r[:2].upper(), "Boshqa")
    d["yil"] = int(d["sana"][-4:]) if d["sana"][-4:].isdigit() else 0
    d["key"] = r + "|" + d["sana"]
    d["nom"] = f"{d['mazmun']}"
COL.setdefault("Boshqa", "#64748b")
BYK = {d["key"]: d for d in DOCS}

# ---------- TAHLIL FUNKSIYALARI ----------
AF = B / "analysis.json"
MODEL = "claude-sonnet-5"
ORGAN = {
    "Qonun": ("Oliy Majlis Qonunchilik palatasi / Prezident imzosi", "Eng yuqori kuch (Konstitutsiyadan keyin)"),
    "Prezident farmoni": ("O'zbekiston Respublikasi Prezidenti", "Qonundan quyi, hukumat qarorlaridan yuqori"),
    "Prezident qarori": ("O'zbekiston Respublikasi Prezidenti", "Farmon bilan bir darajada, aniq chora-tadbirlar uchun"),
    "Vazirlar Mahkamasi qarori": ("O'zbekiston Respublikasi Vazirlar Mahkamasi", "Prezident hujjatlaridan quyi"),
    "Adliya vazirligi buyrug'i": ("Vazirlik/idora buyrug'i (Adliya vazirligida ro'yxatdan o'tgan)", "Idoraviy me'yoriy hujjat, eng quyi daraja"),
    "Bojxona qo'mitasi qarori": ("Davlat bojxona qo'mitasi", "Idoraviy hujjat"),
    "Bojxona kodeksi": ("Kodeks (qonun kuchiga ega)", "Qonun darajasida"),
}

def info(d):
    o, k = ORGAN.get(d["tur"], ("—", "—"))
    return {"Qabul qilgan organ": o, "Yuridik kuchi": k, "Qabul qilingan": d["sana"],
            "Hujjat yoshi": f"{2026 - d['yil']} yil" if d["yil"] else "—"}

def fetch_text(url, limit=45000):
    if not url or "/pdfs/" in url: return None
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        s = BeautifulSoup(r.text, "html.parser")
        for t in s(["script", "style", "nav", "header", "footer"]): t.decompose()
        txt = re.sub(r"\s+", " ", s.get_text(" ")).strip()
        return txt[:limit] if len(txt) > 500 else None
    except Exception:
        return None

def _claude(key, prompt, max_tokens=2500):
    import anthropic
    c = anthropic.Anthropic(api_key=key)
    m = c.messages.create(model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in m.content if b.type == "text")

def analyze(d, key, text=None):
    text = text or fetch_text(d["link"])
    src = f"HUJJAT MATNI:\n{text}" if text else "Hujjat matni olinmadi. Faqat quyidagi ma'lumotlarga tayan va buni 'ogohlantirish' maydonida ayt."
    p = f"""Sen O'zbekiston bojxona va tashqi savdo huquqi bo'yicha ekspertsan. Quyidagi hujjatni tahlil qil.
Hujjat: {d['tur']} {d['raqam']}, {d['sana']}. Qisqa mazmuni (foydalanuvchi yozgan): {d['mazmun']}
{src}
Faqat matnda bor narsaga tayan, o'ylab topma. Faqat JSON qaytar (izohsiz, ``` belgisiz), kalitlar:
"nima_haqida" (2-3 jumla), "maqsad", "asosiy_qoidalar" (5-8 ta punkt, aniq raqam/muddat/stavkalar bilan),
"kimlarga_tegishli", "amaliy_ahamiyat" (bojxona amaliyotida nima o'zgaradi), "muhim_raqamlar_muddatlar" (ro'yxat),
"boglangan_hujjatlar" (matnda tilga olingan), "xavf_va_nuanslar", "yodlash_maslahati" (qisqa mnemonika), "ogohlantirish" (matn olinmagan bo'lsa yoki noaniq joylar)"""
    raw = _claude(key, p).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    return json.loads(raw)

def load(): return json.loads(AF.read_text(encoding="utf-8")) if AF.exists() else {}
def store(k, v): a = load(); a[k] = v; AF.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")

def relevant(q, docs, an, n=6):
    w = {x for x in re.findall(r"\w{4,}", q.lower())}
    def sc(d):
        t = (d["mazmun"] + " " + json.dumps(an.get(d["key"], {}), ensure_ascii=False)).lower()
        return sum(x[:5] in t for x in w)
    return [d for d in sorted(docs, key=sc, reverse=True)[:n] if sc(d) > 0]

def suggest(q, docs, an, key):
    ctx = ""
    for d in docs:
        a = an.get(d["key"])
        ctx += f"\n### {d['raqam']} ({d['sana']}) {d['mazmun']}\n" + (json.dumps(a, ensure_ascii=False) if a else (fetch_text(d["link"], 12000) or "matn yo'q")) + "\n"
    p = f"""Sen O'zbekiston bojxona va tashqi savdo huquqi bo'yicha maslahatchisan. Quyidagi hujjatlar asosida savolga javob ber.
SAVOL/VAZIYAT: {q}
HUJJATLAR:{ctx}
Javobni o'zbek tilida, shu bo'limlar bilan ber: 1) Qaysi hujjatlar qo'llanadi va nega (raqami bilan), 2) Amaliy qadamlar,
3) Hujjatlardagi bo'shliq yoki o'zaro nomuvofiqliklar, 4) Takomillashtirish bo'yicha aniq takliflar, 5) Xavflar.
Har bir fikrni qaysi hujjatga asoslanganingni ko'rsat. Bilmagan narsangni 'aniqlashtirish kerak' deb yoz. Oxirida: bu yuridik maslahat emas, rasmiy matnni lex.uz'da tekshiring."""
    return _claude(key, p, 3500)

# ---------- holat ----------
S = st.session_state
if "P" not in S:
    S.P = json.loads(PF.read_text()) if PF.exists() else {}
    S.P = {"box": {}, "fav": [], "notes": {}, "xp": 0, "hist": [], "days": {}, **S.P}
    S.update(score=0, streak=0, q=None, qid=0, card=0, flip=False, t0=None, ex=None, page="🏠 Bosh sahifa")
P = S.P
today = str(dt.date.today())

def save(): PF.write_text(json.dumps(P, ensure_ascii=False))
def box(d): return P["box"].get(d["key"], 0)
def learned(d): return box(d) >= 4
def short(t, n=80): return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"
def level(): return P["xp"] // 150 + 1
TITLES = ["Yangi boshlovchi", "Izlanuvchi", "Bilimdon", "Tajribali", "Mutaxassis", "Ekspert", "Usta", "Afsona"]

def answer(ok, d, mult=1):
    S.streak = S.streak + 1 if ok else 0
    if ok: pts = (10 + min(S.streak, 8) * 2) * mult; S.score += pts; P["xp"] += pts
    P["box"][d["key"]] = min(box(d) + 1, 5) if ok else 1
    P["days"][today] = P["days"].get(today, 0) + 1
    save()

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif}
#MainMenu,footer{visibility:hidden}.block-container{padding-top:1.5rem;max-width:1200px}
.hero{background:linear-gradient(135deg,#4f46e5,#7c3aed 55%,#ec4899);color:#fff;border-radius:22px;padding:28px 32px;margin-bottom:18px;
box-shadow:0 10px 30px rgba(79,70,229,.35)}.hero h1{margin:0;font-size:2rem;font-weight:800;color:#fff}.hero p{margin:6px 0 0;opacity:.9}
.card{border:1px solid rgba(128,128,128,.25);border-left:6px solid var(--c);border-radius:16px;padding:14px 16px;margin:8px 0;
background:rgba(128,128,128,.06);transition:.2s}.card:hover{transform:translateY(-3px);box-shadow:0 8px 22px rgba(0,0,0,.15)}
.tag{background:var(--c);color:#fff;border-radius:20px;padding:2px 10px;font-size:.72rem;font-weight:600}
.meta{opacity:.65;font-size:.8rem;margin-left:8px}.no{font-size:1.15rem;font-weight:800;margin:6px 0 2px}.tx{opacity:.9;font-size:.93rem}
.stat{border-radius:18px;padding:16px;text-align:center;background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.25)}
.stat b{display:block;font-size:1.8rem}.stat span{opacity:.7;font-size:.8rem}
.flash{min-height:230px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;border-radius:24px;
padding:30px;background:linear-gradient(135deg,rgba(99,102,241,.18),rgba(236,72,153,.15));border:1px solid rgba(128,128,128,.3);font-size:1.35rem;font-weight:600}
.q{font-size:1.25rem;font-weight:700;padding:18px;border-radius:16px;background:rgba(99,102,241,.1);margin-bottom:12px}
.stButton>button{border-radius:12px;font-weight:600}
</style>""", unsafe_allow_html=True)

def card(d):
    fl = ("⭐ " if d["key"] in P["fav"] else "") + ("✅ " if learned(d) else "")
    return (f"<div class='card' style='--c:{COL[d['tur']]}'><span class='tag'>{d['tur']}</span><span class='meta'>{d['sana']}</span>"
            f"<div class='no'>{fl}{html.escape(d['raqam'])}</div><div class='tx'>{html.escape(d['mazmun'])}</div></div>")

def linkbtn(d, k=""):
    if d["link"]: st.link_button("Lex.uz'da ochish ↗", d["link"], use_container_width=True)
    else: st.caption("Havola yo'q")

# ---------- yon panel ----------
PAGES = ["🏠 Bosh sahifa", "📖 Ro'yxat", "🃏 Flashcards", "🎮 O'yinlar", "📊 Statistika", "🔍 Tahlil", "💡 Takliflar"]
st.sidebar.title("⚖️ HujjatUstasi")
S.page = st.sidebar.radio("Bo'lim", PAGES, index=PAGES.index(S.page))
st.sidebar.markdown(f"**{level()}-daraja · {TITLES[min(level() - 1, 7)]}**")
st.sidebar.progress((P["xp"] % 150) / 150, text=f"{P['xp']} XP")
lc = sum(learned(d) for d in DOCS)
st.sidebar.progress(lc / len(DOCS), text=f"O'zlashtirildi {lc}/{len(DOCS)}")
st.sidebar.metric("Sessiya ball", S.score, f"🔥 {S.streak} seriya")

# ---------- savol generatori ----------
MODES = {"Nom → Raqam": ("nom", "raqam"), "Raqam → Nom": ("raqam", "nom"), "Raqam → Sana": ("raqam", "sana"), "Nom → Tur": ("nom", "tur")}
def fmt(d, f): return short(d[f], 75) if f == "nom" else d[f]
def gen(mode, pool=None):
    a, b = MODES[mode]
    pool = pool or DOCS
    d = random.choice(pool)
    ok = fmt(d, b)
    ds = list({fmt(x, b) for x in DOCS if fmt(x, b) != ok})
    op = random.sample(ds, min(3, len(ds))) + [ok]; random.shuffle(op)
    lab = {"nom": "Hujjat nomi", "raqam": "Hujjat raqami", "sana": "Sanasi", "tur": "Turi"}
    return dict(d=d, q=f"<b>{lab[a]}:</b> {html.escape(d[a])}<br><small>Toping → {lab[b]}</small>", ok=ok, op=op, done=None)

def weak_pool(): return [d for d in DOCS if box(d) < 3] or DOCS

def quiz(prefix, modes, pool=None, mult=1, nxt=True):
    if S.q is None: S.q = gen(random.choice(modes), pool); S.qid += 1
    q = S.q
    st.markdown(f"<div class='q'>{q['q']}</div>", unsafe_allow_html=True)
    cols = st.columns(2)
    for i, o in enumerate(q["op"]):
        if cols[i % 2].button(o, key=f"{prefix}{S.qid}{i}", use_container_width=True, disabled=q["done"] is not None):
            q["done"] = o; answer(o == q["ok"], q["d"], mult); st.rerun()
    if q["done"] is None: return False
    st.success("✅ To'g'ri!") if q["done"] == q["ok"] else st.error(f"❌ To'g'ri javob: {q['ok']}")
    st.markdown(card(q["d"]), unsafe_allow_html=True)
    return True

# ================= BOSH SAHIFA =================
if S.page == PAGES[0]:
    st.markdown("<div class='hero'><h1>⚖️ HujjatUstasi</h1><p>Normativ-huquqiy hujjatlarni o'ynab, oson va tez yodlang</p></div>", unsafe_allow_html=True)
    n = P["days"].get(today, 0)
    c = st.columns(4)
    for col, (v, l) in zip(c, [(len(DOCS), "Jami hujjat"), (lc, "O'zlashtirilgan"), (f"{n}/20", "Bugungi maqsad"), (level(), "Daraja")]):
        col.markdown(f"<div class='stat'><b>{v}</b><span>{l}</span></div>", unsafe_allow_html=True)
    st.progress(min(n / 20, 1.0), text="Kunlik maqsad: 20 ta javob")
    a, b = st.columns(2)
    dd = random.Random(today).choice(DOCS)
    with a:
        st.subheader("📅 Kunlik hujjat"); st.markdown(card(dd), unsafe_allow_html=True); linkbtn(dd)
    with b:
        st.subheader("🚀 Tez boshlash")
        for lbl, pg in [("🃏 Qiynalgan hujjatlarni takrorlash", 2), ("🎮 O'yin o'ynash", 3), ("📖 Hujjatlar ro'yxati", 1)]:
            if st.button(lbl, use_container_width=True, key=lbl): S.page = PAGES[pg]; st.rerun()
        if st.button("🎲 Tasodifiy hujjat", use_container_width=True):
            r = random.choice(DOCS); st.markdown(card(r), unsafe_allow_html=True); linkbtn(r)

# ================= RO'YXAT =================
elif S.page == PAGES[1]:
    st.title("📖 Hujjatlar kutubxonasi")
    c = st.columns([3, 2, 2])
    qs = c[0].text_input("🔎 Qidiruv", placeholder="raqam, nom, yil: valyuta, VM-55, 2025")
    tu = c[1].multiselect("Turi", sorted({d["tur"] for d in DOCS}))
    srt = c[2].selectbox("Saralash", ["Raqam bo'yicha", "Yangi → eski", "Eski → yangi", "Qiyinlari birinchi"])
    y0, y1 = min(d["yil"] for d in DOCS), max(d["yil"] for d in DOCS)
    yr = st.slider("Qabul qilingan yil", y0, y1, (y0, y1))
    f = st.columns(3)
    fav, hard, nol = f[0].toggle("⭐ Sevimlilar"), f[1].toggle("😅 Qiyinlari"), f[2].toggle("🔗 Havolasizlar")
    res = [d for d in DOCS if (not qs or qs.lower() in (d["raqam"] + d["mazmun"] + d["sana"]).lower()) and (not tu or d["tur"] in tu)
           and yr[0] <= d["yil"] <= yr[1] and (not fav or d["key"] in P["fav"]) and (not hard or box(d) < 3) and (not nol or not d["link"])]
    res.sort(key={"Yangi → eski": lambda d: -d["yil"], "Eski → yangi": lambda d: d["yil"], "Qiyinlari birinchi": box}.get(srt, lambda d: 0))
    pages = max(1, -(-len(res) // 12))
    pg = st.number_input(f"Sahifa (jami {len(res)} ta hujjat, {pages} sahifa)", 1, pages, 1) - 1
    cols = st.columns(2)
    for i, d in enumerate(res[pg * 12:(pg + 1) * 12]):
        with cols[i % 2]:
            st.markdown(card(d), unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            with b1: linkbtn(d)
            if b2.button("★ Sevimli" if d["key"] not in P["fav"] else "☆ Olib tashlash", key="f" + d["key"], use_container_width=True):
                P["fav"].remove(d["key"]) if d["key"] in P["fav"] else P["fav"].append(d["key"]); save(); st.rerun()
            with st.expander("📝 Mening eslatmam (mnemonika)"):
                t = st.text_area("Eslatma", P["notes"].get(d["key"], ""), key="n" + d["key"], label_visibility="collapsed")
                if t != P["notes"].get(d["key"], ""): P["notes"][d["key"]] = t; save()

# ================= FLASHCARDS =================
elif S.page == PAGES[2]:
    st.title("🃏 Flashcards (Leytner takrorlash tizimi)")
    m = st.radio("Yo'nalish", ["Nom → Raqam", "Raqam → Nom"], horizontal=True)
    if "cd" not in S: S.cd = None
    if S.cd is None:
        S.cd = random.choices(DOCS, weights=[6 - box(d) for d in DOCS])[0]; S.flip = False
    d = S.cd
    front, back = (d["nom"], d["raqam"]) if m == "Nom → Raqam" else (d["raqam"], d["nom"])
    txt = f"{html.escape(back)}<br><small style='opacity:.7'>{d['tur']} · {d['sana']}</small>" if S.flip else html.escape(front)
    st.markdown(f"<div class='flash'>{txt}</div>", unsafe_allow_html=True)
    st.caption(f"Bilim darajasi: {'🟩' * box(d)}{'⬜' * (5 - box(d))}")
    c = st.columns(5)
    if c[0].button("🔄 Aylantirish", use_container_width=True): S.flip = not S.flip; st.rerun()
    if c[1].button("✅ Bilaman", use_container_width=True): answer(True, d); S.cd = None; st.rerun()
    if c[2].button("😅 Qiyin", use_container_width=True): answer(False, d); S.cd = None; st.rerun()
    if c[3].button("⏭ O'tkazish", use_container_width=True): S.cd = None; st.rerun()
    with c[4]: linkbtn(d)
    components.html(f"<button onclick=\"var u=new SpeechSynthesisUtterance({json.dumps(d['nom'])});u.lang='ru-RU';speechSynthesis.speak(u)\" "
                    "style='padding:8px 16px;border-radius:10px;border:1px solid #888;cursor:pointer'>🔊 Ovozli o'qish</button>", height=50)
    if P["notes"].get(d["key"]): st.info("📝 " + P["notes"][d["key"]])

# ================= O'YINLAR =================
elif S.page == PAGES[3]:
    st.title("🎮 O'yinlar")
    t = st.tabs(["❓ Viktorina", "✍️ Yozma", "🔗 Juftlash", "⏱ Vaqtga qarshi", "🎓 Imtihon", "🎯 Xatolar ustida"])
    with t[0]:
        ms = st.multiselect("Savol turlari", list(MODES), default=list(MODES)[:2]) or list(MODES)
        if quiz("v", ms) and st.button("Keyingi ➡️", type="primary", key="nv"): S.q = None; st.rerun()
    with t[1]:
        if "w" not in S: S.w = random.choice(DOCS); S.wr = None
        d = S.w
        st.markdown(f"<div class='q'><b>Hujjat nomi:</b> {html.escape(d['nom'])}<br><small>Uning raqamini yozing (masalan VM-55)</small></div>", unsafe_allow_html=True)
        ans = st.text_input("Raqam", key="wi" + str(S.get("wn", 0)))
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("ʻ", "").replace("‘", "").replace("'", ""))
        if st.button("Tekshirish", type="primary") and ans:
            ok = norm(ans) == norm(d["raqam"]); answer(ok, d, 2)
            st.success("✅ To'g'ri! +2x ball") if ok else st.error(f"❌ To'g'ri javob: {d['raqam']}")
            st.markdown(card(d), unsafe_allow_html=True)
        if st.button("Keyingi ➡️", key="nw"): S.w = random.choice(DOCS); S.wn = S.get("wn", 0) + 1; st.rerun()
    with t[2]:
        rev = st.radio("Yo'nalish", ["Nom → Raqam", "Raqam → Nom"], horizontal=True)
        if "pairs" not in S: S.pairs = random.sample(DOCS, 6); S.pk = 0
        L, R = ("nom", "raqam") if rev == "Nom → Raqam" else ("raqam", "nom")
        opts = [fmt(d, R) for d in S.pairs]; random.Random(S.pk).shuffle(opts)
        sel = {}
        for d in S.pairs:
            a, b = st.columns([1, 1])
            a.markdown(f"**{fmt(d, L)}**")
            sel[d["key"]] = b.selectbox("j", ["—"] + opts, key=f"m{S.pk}{d['key']}", label_visibility="collapsed")
        c = st.columns(2)
        if c[0].button("Tekshirish", type="primary"):
            n = 0
            for d in S.pairs:
                ok = sel[d["key"]] == fmt(d, R); n += ok; answer(ok, d)
                st.write(("✅ " if ok else f"❌ → {fmt(d, R)} | ") + fmt(d, L))
            st.success(f"Natija: {n}/6")
        if c[1].button("🔄 Yangi to'plam"): del S["pairs"]; st.rerun()
    with t[3]:
        if S.t0 is None:
            st.info("60 soniyada iloji boricha ko'p to'g'ri javob bering. Ball ×2!")
            if st.button("▶️ Boshlash", type="primary"): S.t0 = time.time(); S.s0 = S.score; S.q = None; st.rerun()
        else:
            @st.fragment(run_every=1)
            def timer():
                left = 60 - (time.time() - S.t0)
                if left <= 0: st.rerun()
                st.progress(max(left, 0) / 60, text=f"⏳ {int(left)} soniya")
            timer()
            if 60 - (time.time() - S.t0) <= 0:
                st.balloons(); pts = S.score - S.s0; st.success(f"Vaqt tugadi! Ball: {pts}")
                P["hist"].append({"sana": today, "rejim": "Vaqtga qarshi", "ball": pts}); save(); S.t0 = None; S.q = None
            elif quiz("t", list(MODES), mult=2): 
                if st.button("Keyingi ➡️", type="primary", key="nt"): S.q = None; st.rerun()
    with t[4]:
        N = st.select_slider("Savollar soni", [10, 20, 30, 50], 20)
        if S.ex is None:
            if st.button("🎓 Imtihonni boshlash", type="primary"):
                S.ex = dict(qs=[gen(random.choice(list(MODES))) for _ in range(N)], i=0, ok=0, bad=[]); st.rerun()
        else:
            e = S.ex
            if e["i"] >= len(e["qs"]):
                pc = round(100 * e["ok"] / len(e["qs"])); st.metric("Natija", f"{pc}%", f"{e['ok']}/{len(e['qs'])}")
                st.success("A'lo! 🏆") if pc >= 85 else st.warning("Yana takrorlang 💪")
                for d in e["bad"]: st.markdown(card(d), unsafe_allow_html=True)
                P["hist"].append({"sana": today, "rejim": "Imtihon", "ball": pc}); save()
                if st.button("Yangi imtihon"): S.ex = None; st.rerun()
            else:
                q = e["qs"][e["i"]]; st.progress(e["i"] / len(e["qs"]), text=f"Savol {e['i'] + 1}/{len(e['qs'])}")
                st.markdown(f"<div class='q'>{q['q']}</div>", unsafe_allow_html=True)
                for i, o in enumerate(q["op"]):
                    if st.button(o, key=f"e{e['i']}{i}", use_container_width=True):
                        ok = o == q["ok"]; e["ok"] += ok; answer(ok, q["d"])
                        if not ok: e["bad"].append(q["d"])
                        e["i"] += 1; st.rerun()
    with t[5]:
        st.caption("Faqat 3-qutidan past (qiynalgan) hujjatlar chiqadi")
        if quiz("w2", list(MODES), weak_pool()) and st.button("Keyingi ➡️", type="primary", key="nx"): S.q = None; st.rerun()

# ================= STATISTIKA =================
elif S.page == PAGES[4]:
    st.title("📊 Statistika va yutuqlar")
    c = st.columns(4)
    for col, (v, l) in zip(c, [(P["xp"], "Jami XP"), (level(), "Daraja"), (len(P["fav"]), "Sevimlilar"), (sum(P["days"].values()), "Jami javoblar")]):
        col.markdown(f"<div class='stat'><b>{v}</b><span>{l}</span></div>", unsafe_allow_html=True)
    a, b = st.columns(2)
    with a:
        st.subheader("Tur bo'yicha o'zlashtirish, %")
        st.bar_chart({t: round(100 * sum(learned(d) for d in DOCS if d["tur"] == t) / sum(d["tur"] == t for d in DOCS)) for t in COL if any(d["tur"] == t for d in DOCS)})
    with b:
        st.subheader("Yillar bo'yicha hujjatlar soni")
        yc = {}
        for d in DOCS: yc[str(d["yil"])] = yc.get(str(d["yil"]), 0) + 1
        st.bar_chart(dict(sorted(yc.items())))
    st.subheader("🏅 Yutuqlar")
    bd = [(lc >= 10, "🥉 10 ta hujjat"), (lc >= 30, "🥈 30 ta hujjat"), (lc >= 60, "🥇 60 ta hujjat"), (lc >= len(DOCS), "🏆 Hammasi!"),
          (P["xp"] >= 1000, "💎 1000 XP"), (any(h["ball"] >= 90 for h in P["hist"] if h["rejim"] == "Imtihon"), "🎓 Imtihon 90%+"), (len(P["days"]) >= 7, "📆 7 kun faol")]
    st.write(" · ".join(("✅ " if o else "🔒 ") + n for o, n in bd))
    st.subheader("😅 Eng qiyin 10 ta hujjat")
    for d in sorted(DOCS, key=box)[:10]: st.markdown(card(d), unsafe_allow_html=True)
    if P["hist"]: st.subheader("Natijalar tarixi"); st.dataframe(P["hist"][::-1], use_container_width=True)
    st.download_button("⬇️ Progressni yuklab olish", json.dumps(P, ensure_ascii=False), "progress.json")
    if st.button("🗑 Progressni tozalash"): PF.unlink(missing_ok=True); del S["P"]; st.rerun()

# ================= TAHLIL =================
elif S.page == PAGES[5]:
    st.title("🔍 Hujjat tahlili")
    KEY = os.environ.get("ANTHROPIC_API_KEY") or st.sidebar.text_input("Anthropic API kaliti", type="password")
    AN = load()
    d = st.selectbox("Hujjatni tanlang", DOCS, format_func=lambda x: f"{x['raqam']} — {short(x['mazmun'], 70)}")
    st.markdown(card(d), unsafe_allow_html=True); linkbtn(d)
    for k, v in info(d).items(): st.write(f"**{k}:** {v}")
    a = AN.get(d["key"])
    if not a:
        st.info("Chuqur tahlil hali yo'q. U hujjatning lex.uz'dagi matniga asoslanib tayyorlanadi.")
        man = st.text_area("Matn olinmasa, hujjat matnini shu yerga qo'ying (ixtiyoriy)")
        if st.button("🧠 Chuqur tahlil qilish", type="primary"):
            if not KEY: st.error("Yon panelda API kalitini kiriting.")
            else:
                with st.spinner("Hujjat o'qilmoqda..."):
                    try: store(d["key"], analyze(d, KEY, man or None)); st.rerun()
                    except Exception as e: st.error(f"Xato: {e}")
    else:
        if a.get("ogohlantirish"): st.warning(a["ogohlantirish"])
        L = {"nima_haqida": "📌 Nima haqida", "maqsad": "🎯 Maqsadi", "asosiy_qoidalar": "📋 Asosiy qoidalar", "kimlarga_tegishli": "👥 Kimlarga tegishli",
             "amaliy_ahamiyat": "🛠 Amaliy ahamiyati", "muhim_raqamlar_muddatlar": "🔢 Muhim raqam va muddatlar", "boglangan_hujjatlar": "🔗 Bog'liq hujjatlar",
             "xavf_va_nuanslar": "⚠️ Xavf va nuanslar", "yodlash_maslahati": "🧠 Yodlash maslahati"}
        for k, t in L.items():
            v = a.get(k)
            if v: st.subheader(t); [st.write("• " + str(x)) for x in v] if isinstance(v, list) else st.write(v)
        if st.button("🔄 Qayta tahlil qilish") and KEY: store(d["key"], analyze(d, KEY)); st.rerun()
    st.caption(f"Tahlil qilingan hujjatlar: {len(AN)}/{len(DOCS)}")
    if st.button("⚙️ Qolgan hujjatlarni ketma-ket tahlil qilish (uzoq davom etadi)") and KEY:
        todo = [x for x in DOCS if x["key"] not in AN]; bar = st.progress(0)
        for i, x in enumerate(todo, 1):
            try: store(x["key"], analyze(x, KEY))
            except Exception as e: st.warning(f"{x['raqam']}: {e}")
            bar.progress(i / len(todo), text=f"{i}/{len(todo)} — {x['raqam']}")
        st.rerun()

# ================= TAKLIFLAR =================
else:
    st.title("💡 Takliflar va huquqiy tahlil")
    KEY = os.environ.get("ANTHROPIC_API_KEY") or st.sidebar.text_input("Anthropic API kaliti", type="password")
    AN = load()
    q = st.text_area("Vaziyat, muammo yoki mavzuni yozing", placeholder="Masalan: jismoniy shaxs 6 oyda ikkinchi marta avtomobil ehtiyot qismlarini olib kirmoqchi. Qanday tartib va bojlar qo'llanadi? Qonunchilikda qanday bo'shliqlar bor?")
    auto = relevant(q, DOCS, AN) if q else []
    sel = st.multiselect("Tahlilga olinadigan hujjatlar (avtomatik tanlanadi, o'zgartirishingiz mumkin)", DOCS, default=auto, format_func=lambda x: f"{x['raqam']} — {short(x['mazmun'], 60)}")
    st.caption(f"Chuqur tahlili tayyor hujjatlar: {sum(x['key'] in AN for x in sel)}/{len(sel)} — tahlil qancha ko'p bo'lsa, javob shuncha aniq.")
    if st.button("💡 Takliflar tayyorlash", type="primary", disabled=not (q and sel)):
        if not KEY: st.error("Yon panelda API kalitini kiriting.")
        else:
            with st.spinner("Hujjatlar tahlil qilinmoqda..."):
                try: st.markdown(suggest(q, sel, AN, KEY))
                except Exception as e: st.error(f"Xato: {e}")
    for x in sel: st.markdown(card(x), unsafe_allow_html=True)
