"""Lightweight bilingual RAG pipeline.
Retrieval: character n-gram TF-IDF (works reasonably for English and Malayalam).
Generation: grounded extractive answer assembled only from retrieved college records.
No external API key is required. This is intentionally safer than an ungrounded LLM demo.
"""
import re
import sqlite3
from pathlib import Path
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "college.db"
_vectorizer = None
_matrix = None
_chunks = []


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def extract_pdf_text(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is missing. Run: pip install -r requirements.txt") from exc
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def chunk_text(text, max_chars=850, overlap=120):
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            # Prefer to end at a sentence or line boundary.
            boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end), text.rfind("।", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def index_all_sources():
    global _vectorizer, _matrix, _chunks
    items = []
    try:
        with connect() as conn:
            for row in conn.execute("SELECT category,question_en,question_ml,answer_en,answer_ml,source FROM faqs"):
                items.append({
                    "text": f"Category: {row['category']}\nQuestion: {row['question_en']}\nMalayalam question: {row['question_ml']}\nAnswer: {row['answer_en']}\nMalayalam answer: {row['answer_ml']}",
                    "source": row["source"],
                    "kind": "FAQ"
                })
            for row in conn.execute("SELECT title,body,published_on,source FROM notices"):
                items.append({
                    "text": f"Notice: {row['title']}\nDate: {row['published_on']}\nDetails: {row['body']}",
                    "source": row["source"],
                    "kind": "Notice"
                })
            for row in conn.execute("SELECT original_name,content FROM documents"):
                for chunk in chunk_text(row["content"]):
                    items.append({"text": chunk, "source": row["original_name"], "kind": "Document"})
    except sqlite3.OperationalError:
        # During first app startup the database may not exist yet.
        pass

    _chunks = items
    if items:
        _vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1, sublinear_tf=True)
        _matrix = _vectorizer.fit_transform([x["text"] for x in items])
    else:
        _vectorizer, _matrix = None, None


def detect_language(text, requested="auto"):
    if requested in ("en", "ml"):
        return requested
    # Malayalam Unicode block.
    return "ml" if re.search(r"[\u0D00-\u0D7F]", text) else "en"


def _fallback(language):
    if language == "ml":
        return ("ഈ ചോദ്യത്തിന് സ്ഥിരീകരിച്ച കോളേജ് വിവരങ്ങൾ അറിവുശേഖരത്തിൽ കണ്ടെത്താനായില്ല. "
                "ദയവായി ഔദ്യോഗിക കോളേജ് അറിയിപ്പോ ബന്ധപ്പെട്ട ഡിപ്പാർട്ട്മെന്റ് ഓഫീസോ പരിശോധിക്കുക.")
    return ("I couldn't find a verified answer in the current college knowledge base. "
            "Please check the official college notice or contact the relevant department office.")


def answer_question(question, requested_language="auto"):
    language = detect_language(question, requested_language)
    if not _chunks or _vectorizer is None or _matrix is None:
        return {"answer": _fallback(language), "language": language, "sources": [], "confidence": 0.0}

    query_vec = _vectorizer.transform([question])
    scores = cosine_similarity(query_vec, _matrix).ravel()
    best = scores.argsort()[::-1][:3]
    selected = [(int(i), float(scores[i])) for i in best if scores[i] >= 0.08]
    if not selected:
        return {"answer": _fallback(language), "language": language, "sources": [], "confidence": 0.0}

    # Keep the response grounded in retrieved text. Use a direct extractive response.
    snippets = []
    sources = []
    seen_sources = set()
    for i, score in selected:
        item = _chunks[i]
        text = re.sub(r"\s+", " ", item["text"]).strip()
        if len(text) > 750:
            text = text[:747].rsplit(" ", 1)[0] + "..."
        snippets.append(text)
        label = f"{item['kind']}: {item['source']}"
        if label not in seen_sources:
            sources.append(label)
            seen_sources.add(label)

    if language == "ml":
        intro = "ലഭ്യമായ കോളേജ് അറിവുശേഖരത്തിൽ നിന്നുള്ള ബന്ധപ്പെട്ട വിവരം:"
        caveat = " ഇത് ലഭ്യമായ രേഖകളിൽ നിന്നുള്ള വിവരമാണ്; ഔദ്യോഗിക തീയതികളും മാറ്റങ്ങളും കോളേജ് അറിയിപ്പിലൂടെ സ്ഥിരീകരിക്കുക."
    else:
        intro = "Here is the most relevant information from the college knowledge base:"
        caveat = " This answer is based on the currently indexed records. Confirm official dates and changes against the latest college notice."

    answer = intro + "\n\n" + "\n\n".join(f"• {s}" for s in snippets) + "\n\n" + caveat
    return {
        "answer": answer,
        "language": language,
        "sources": sources,
        "confidence": round(min(0.99, max(s for _, s in selected)), 3)
    }
