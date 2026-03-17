"""
ingest.py — Pipeline для завантаження документів у векторну базу даних.

Запуск: python ingest.py
Що відбувається:
  1. Читаємо всі PDF з директорії ./data/
  2. Ріжемо на чанки (RecursiveCharacterTextSplitter)
  3. Генеруємо ембедінги через OpenAI API
  4. Зберігаємо в FAISS-індекс на диску
  5. Зберігаємо список проіндексованих файлів → при повторному запуску
     індексуємо лише нові/змінені файли (incremental update)

Аналогія з Java:
  Цей скрипт — як ETL-пайплайн: Extract (PDF) → Transform (chunks) → Load (FAISS).
  FAISS-індекс — це як бінарний серіалізований об'єкт на диску (ObjectOutputStream).
"""

import json
import os
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import BASE_DIR, settings


# ── Константи ────────────────────────────────────────────────────────────────

# Path — зручний об'єкт для роботи зі шляхами, аналог java.nio.file.Path
DATA_DIR = BASE_DIR / "data"

# Директорія де зберігатиметься FAISS-індекс (два файли: index.faiss + index.pkl)
FAISS_INDEX_DIR = BASE_DIR / "faiss_index"

# JSON-файл де ми трекаємо вже проіндексовані файли.
# Структура: {"filename.pdf": {"size": 12345, "mtime": 1710000000.0, "chunks": 42}}
# size + mtime — як checksum: якщо змінився розмір або дата — файл треба переіндексувати.
INGESTED_FILES_TRACKER = FAISS_INDEX_DIR / "ingested_files.json"

# Параметри чанкування
# chunk_size=500 — максимальна кількість символів в одному чанку
# chunk_overlap=100 — перекриття між сусідніми чанками (щоб не втратити контекст на межі)
# Аналогія: уяви що ти читаєш книгу і між сторінками є 100 символів повтору —
# щоб речення на межі сторінок не обривалося.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


# ── Допоміжні функції ─────────────────────────────────────────────────────────

def _load_tracker() -> dict:
    """
    Завантажує трекер вже проіндексованих файлів з диску.

    Якщо файл не існує (перший запуск) — повертає порожній dict.
    dict — це як HashMap<String, Map<String, Object>> у Java.
    """
    if INGESTED_FILES_TRACKER.exists():
        return json.loads(INGESTED_FILES_TRACKER.read_text(encoding="utf-8"))
    return {}


def _save_tracker(tracker: dict) -> None:
    """
    Зберігає трекер на диск у форматі JSON.

    json.dumps з indent=2 — читабельний JSON, як Jackson ObjectMapper
    з SerializationFeature.INDENT_OUTPUT у Java.
    """
    INGESTED_FILES_TRACKER.write_text(
        json.dumps(tracker, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _file_changed(filepath: Path, tracker: dict) -> bool:
    """
    Перевіряє чи змінився файл з моменту останнього індексування.

    Порівнюємо розмір (size) і дату модифікації (mtime) — як легкий checksum.
    Якщо файлу немає в трекері або він змінився — повертаємо True (треба індексувати).

    filepath.stat() — аналог File.lastModified() і File.length() у Java.
    """
    stat = filepath.stat()
    key = filepath.name

    if key not in tracker:
        return True  # файл новий — треба індексувати

    saved = tracker[key]
    # Порівнюємо розмір і час модифікації
    return saved.get("size") != stat.st_size or saved.get("mtime") != stat.st_mtime


def _load_pdf(filepath: Path) -> list:
    """
    Завантажує PDF і повертає список Document-об'єктів (по одному на сторінку).

    PyPDFLoader — аналог Apache PDFBox у Java-світі.
    Document — це як DTO: text (page_content) + metadata (page, source).
    """
    loader = PyPDFLoader(str(filepath))
    return loader.load()


def _split_into_chunks(documents: list) -> list:
    """
    Розбиває документи на чанки за допомогою RecursiveCharacterTextSplitter.

    Як працює Recursive splitter:
      Намагається розділити по "\n\n" (абзаци) → якщо чанк все одно великий,
      ділить по "\n" → потім по ". " → потім по " " → і нарешті по символах.
      Такий підхід зберігає смислові межі тексту.

    Аналогія: це як StringUtils.split, але розумний — спочатку намагається
    розрізати по абзацах, і лише якщо не виходить — по реченнях.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # separators — пріоритетний список роздільників (зліва найважливіший)
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(documents)


# ── Основна логіка ────────────────────────────────────────────────────────────

def ingest():
    """
    Головна функція ingestion pipeline.

    Алгоритм:
    1. Знаходимо всі PDF у ./data/
    2. Порівнюємо з трекером — беремо лише нові/змінені файли
    3. Завантажуємо і ріжемо на чанки
    4. Якщо FAISS-індекс вже є — дозавантажуємо (add_documents)
       Якщо ні — створюємо новий (from_documents)
    5. Зберігаємо індекс і оновлюємо трекер
    """
    print("🔍 Scanning data directory...")

    # glob("*.pdf") — знаходить усі PDF файли в директорії
    # В Java — аналог: Files.walk(dataDir).filter(p -> p.endsWith(".pdf"))
    pdf_files = list(DATA_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"⚠️  No PDF files found in {DATA_DIR}")
        return

    print(f"📁 Found {len(pdf_files)} PDF file(s): {[f.name for f in pdf_files]}")

    # Завантажуємо трекер — знаємо які файли вже проіндексовані
    tracker = _load_tracker()

    # Фільтруємо — лишаємо лише нові або змінені файли
    # list comprehension з умовою — як stream().filter().collect() у Java
    new_files = [f for f in pdf_files if _file_changed(f, tracker)]

    if not new_files:
        print("✅ All files are already indexed. Nothing to do.")
        print(f"   Use: rm -rf {FAISS_INDEX_DIR} to force full re-index.")
        return

    print(f"\n📄 Files to index: {[f.name for f in new_files]}")

    # ── Крок 1: завантаження і чанкування ────────────────────────────────────
    all_chunks = []

    for filepath in new_files:
        print(f"\n  ⏳ Loading: {filepath.name}")
        documents = _load_pdf(filepath)
        print(f"     Loaded {len(documents)} page(s)")

        chunks = _split_into_chunks(documents)
        print(f"     Split into {len(chunks)} chunk(s)")

        all_chunks.extend(chunks)

        # Оновлюємо трекер для цього файлу
        stat = filepath.stat()
        tracker[filepath.name] = {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "chunks": len(chunks),
        }

    print(f"\n✂️  Total new chunks: {len(all_chunks)}")

    # ── Крок 2: ембедінги і збереження в FAISS ───────────────────────────────
    print("\n🔑 Initializing OpenAI Embeddings (text-embedding-3-small)...")

    # OpenAIEmbeddings — клієнт до OpenAI Embeddings API
    # text-embedding-3-small: 1536-вимірний вектор, дешевший за large
    # У Java аналог: REST-клієнт що перетворює рядок на float[]
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=settings.openai_api_key,
    )

    # Перевіряємо чи вже є існуючий індекс на диску
    index_exists = (FAISS_INDEX_DIR / "index.faiss").exists()

    if index_exists:
        # Incremental update — завантажуємо існуючий індекс і додаємо нові чанки
        print("📂 Loading existing FAISS index...")
        # allow_dangerous_deserialization=True потрібен бо FAISS використовує pickle
        # (бінарна серіалізація Python — як Java ObjectInputStream)
        # Це безпечно поки ми самі створили цей індекс
        vectorstore = FAISS.load_local(
            str(FAISS_INDEX_DIR),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        print(f"   Adding {len(all_chunks)} new chunk(s) to existing index...")
        # add_documents — дозаписує нові вектори без перебудови всього індексу
        vectorstore.add_documents(all_chunks)
    else:
        # Перший запуск — створюємо індекс з нуля
        print(f"🔨 Building new FAISS index from {len(all_chunks)} chunk(s)...")
        print("   (This calls OpenAI Embeddings API — may take a moment...)")
        # from_documents — бере список Document, генерує ембедінги і будує індекс
        vectorstore = FAISS.from_documents(all_chunks, embeddings)

    # ── Крок 3: збереження на диск ───────────────────────────────────────────
    FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # save_local — зберігає два файли:
    #   index.faiss — бінарний FAISS-індекс (самі вектори)
    #   index.pkl   — metadata (тексти чанків і їх метадані)
    vectorstore.save_local(str(FAISS_INDEX_DIR))
    print(f"\n💾 FAISS index saved to: {FAISS_INDEX_DIR}/")

    # Зберігаємо оновлений трекер
    _save_tracker(tracker)
    print(f"📋 Tracker updated: {INGESTED_FILES_TRACKER}")

    # Підсумок
    print("\n✅ Ingestion complete!")
    print(f"   Indexed files: {list(tracker.keys())}")
    total_chunks = sum(v["chunks"] for v in tracker.values())
    print(f"   Total chunks in index: {total_chunks}")


if __name__ == "__main__":
    # __name__ == "__main__" — стандартна перевірка: скрипт запущено напряму,
    # а не імпортовано. Аналог public static void main(String[] args) у Java.
    ingest()
