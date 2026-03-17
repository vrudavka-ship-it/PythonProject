"""
retriever.py — Hybrid Retrieval з Reranking для локальної бази знань.

Цей модуль реалізує три шари пошуку:

  1. Semantic Search (Vector)
     Перетворює запит на ембедінг і знаходить семантично схожі чанки.
     Добре: розуміє синоніми, контекст, переформулювання.
     Погано: може пропустити точні терміни/коди якщо вони семантично "далеко".

  2. BM25 Search (Lexical)
     Класичний алгоритм пошуку за ключовими словами (TF-IDF-подібний).
     Добре: точні збіги термінів, абревіатур, кодів помилок.
     Погано: не розуміє семантику — "automobile" і "car" для нього різні слова.

  3. Ensemble + Reranking
     EnsembleRetriever об'єднує результати обох методів.
     CrossEncoder reranker потім перевпорядковує їх — читає пару
     (запит + документ) РАЗОМ і дає точніший score релевантності.

Аналогія з Java:
  Це як пошукова система з двома індексами (Lucene + векторний),
  і потім результати проходять через ML-модель для re-scoring.
"""

from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_openai import OpenAIEmbeddings
# langchain_classic — це пакет де живуть "класичні" LangChain компоненти:
# EnsembleRetriever, ContextualCompressionRetriever, CrossEncoderReranker.
# Це той самий пакет що у лекції називався "langchain_classic".
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_classic.retrievers.document_compressors.cross_encoder_rerank import CrossEncoderReranker
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever

from config import BASE_DIR, settings


# ── Константи ────────────────────────────────────────────────────────────────

FAISS_INDEX_DIR = BASE_DIR / "faiss_index"

# Скільки кандидатів отримати від кожного retriever перед reranking
# Більше кандидатів → краший recall, але повільніший reranking
RETRIEVER_K = 5

# Скільки фінальних результатів повернути після reranking
RERANKER_TOP_N = 3

# BM25 weight у ensemble: 40% BM25 + 60% Vector
# Якщо запити часто містять точні терміни — підніми BM25 вагу (наприклад 0.5)
BM25_WEIGHT = 0.4
VECTOR_WEIGHT = 0.6

# Назва моделі cross-encoder для reranking
# BAAI/bge-reranker-base — безкоштовна HuggingFace модель (~280MB)
# Завантажується один раз і кешується локально в ~/.cache/huggingface/
RERANKER_MODEL = "BAAI/bge-reranker-base"


# ── Клас HybridRetriever ──────────────────────────────────────────────────────

class HybridRetriever:
    """
    Об'єднує Semantic Search + BM25 + CrossEncoder Reranking в один пайплайн.

    Порядок роботи:
      query → EnsembleRetriever (BM25 + Vector) → top-10 кандидатів
             → CrossEncoder Reranker → top-3 фінальних результати

    Клас — як Java-клас з lazy initialization:
      важкі об'єкти (FAISS, BM25, CrossEncoder) завантажуються один раз
      при першому виклику і потім кешуються в полях об'єкта.
    """

    def __init__(self):
        # None — аналог null в Java. Об'єкти ще не ініціалізовані.
        # Ми використовуємо lazy loading: завантажуємо лише коли потрібно.
        self._vectorstore: FAISS | None = None
        self._all_chunks: list | None = None
        self._retriever: ContextualCompressionRetriever | None = None

    def _load(self) -> None:
        """
        Ледаче (lazy) завантаження всіх компонентів при першому запиті.

        Чому lazy?
        CrossEncoder модель завантажується ~5-10 секунд при першому виклику.
        Якщо завантажувати при старті агента — то навіть для web_search
        ми чекаємо 10 секунд. Lazy loading вирішує це.

        Аналог у Java: double-checked locking або @Lazy Spring beans.
        """
        if self._retriever is not None:
            return  # вже завантажено — нічого не робимо

        if not (FAISS_INDEX_DIR / "index.faiss").exists():
            raise FileNotFoundError(
                f"FAISS index not found at {FAISS_INDEX_DIR}. "
                "Run: python ingest.py"
            )

        print("   [RAG] Loading FAISS index...")
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=settings.openai_api_key,
        )

        # allow_dangerous_deserialization=True — потрібен для pickle десеріалізації
        # Безпечно: ми самі створили цей індекс через ingest.py
        self._vectorstore = FAISS.load_local(
            str(FAISS_INDEX_DIR),
            embeddings,
            allow_dangerous_deserialization=True,
        )

        # ── Retriever 1: Vector (Semantic Search) ─────────────────────────────
        # as_retriever() — обгортає FAISS у стандартний LangChain Retriever інтерфейс
        # search_kwargs={"k": N} — скільки найближчих сусідів повернути
        vector_retriever = self._vectorstore.as_retriever(
            search_kwargs={"k": RETRIEVER_K}
        )

        # ── Retriever 2: BM25 (Lexical Search) ───────────────────────────────
        # BM25 потребує доступу до ВСІХ чанків одразу (він будує інвертований індекс в RAM)
        # docstore._dict — внутрішній dict FAISS де зберігаються тексти чанків
        # .values() — всі Document-об'єкти (text + metadata)
        # Аналог: Map.values() у Java
        print("   [RAG] Building BM25 index...")
        all_chunks = list(self._vectorstore.docstore._dict.values())
        bm25_retriever = BM25Retriever.from_documents(all_chunks)
        bm25_retriever.k = RETRIEVER_K

        # ── EnsembleRetriever: об'єднання BM25 + Vector ───────────────────────
        # Reciprocal Rank Fusion (RRF) — алгоритм злиття ranked lists.
        # weights визначає внесок кожного retriever у фінальний score.
        # Аналог: WeightedVoter у ensemble ML методах.
        ensemble = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[BM25_WEIGHT, VECTOR_WEIGHT],
        )

        # ── CrossEncoder Reranker ─────────────────────────────────────────────
        # CrossEncoder читає пару (query, document) РАЗОМ і дає score релевантності.
        # Bi-Encoder (FAISS) кодує запит і документ ОКРЕМО — швидко але менш точно.
        # CrossEncoder — повільно (O(n) пар), але набагато точніше.
        # Стратегія: EnsembleRetriever дає 10 кандидатів → CrossEncoder вибирає 3 найкращих.
        print(f"   [RAG] Loading CrossEncoder reranker ({RERANKER_MODEL})...")
        print("         (First load may take ~30s to download the model...)")
        reranker_model = HuggingFaceCrossEncoder(model_name=RERANKER_MODEL)
        compressor = CrossEncoderReranker(
            model=reranker_model,
            top_n=RERANKER_TOP_N,
        )

        # ContextualCompressionRetriever = base_retriever + compressor
        # Схема роботи: query → ensemble (10 docs) → cross_encoder reranker (3 docs)
        self._retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=ensemble,
        )
        print("   [RAG] Ready.\n")

    def search(self, query: str) -> str:
        """
        Виконує гібридний пошук і повертає відформатований рядок з результатами.

        Повертає str — щоб tool міг одразу повернути це як результат агенту.
        Формат: нумерований список чанків з метаданими (джерело, сторінка).
        """
        # Lazy load при першому виклику
        self._load()

        # invoke() — стандартний LangChain метод для запуску retriever
        # Повертає list[Document] де кожен Document має .page_content і .metadata
        docs = self._retriever.invoke(query)

        if not docs:
            return "No relevant documents found in the knowledge base."

        # Форматуємо результати в читабельний рядок для агента
        # Аналог: StringBuilder у Java
        parts = []
        for i, doc in enumerate(docs, start=1):
            # metadata зберігає: source (шлях до файлу), page (номер сторінки)
            source = Path(doc.metadata.get("source", "unknown")).name
            page = doc.metadata.get("page", "?")
            # f-string — як String.format() у Java, але читабельніший
            header = f"[Source {i}: {source}, page {page}]"
            parts.append(f"{header}\n{doc.page_content.strip()}")

        return "\n\n---\n\n".join(parts)


# ── Singleton ─────────────────────────────────────────────────────────────────

# Singleton — єдиний екземпляр HybridRetriever для всього процесу.
# Важливо: CrossEncoder модель займає ~500MB RAM — не хочемо завантажувати двічі.
# Аналог: @Singleton або static instance у Java.
_retriever_instance = HybridRetriever()


def hybrid_search(query: str) -> str:
    """
    Публічна функція-фасад для виклику гібридного пошуку.

    Фасад (Facade pattern) — спрощений інтерфейс до складної підсистеми.
    tools.py буде імпортувати саме цю функцію, а не клас напряму.
    """
    return _retriever_instance.search(query)
