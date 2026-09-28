# Research: Chroma and Langchain for metadata, cosine distance and e5 prefixes

Researched 2026-09-28 for issue #5 (feeds open questions D16–D18 in [open-questions.md](../open-questions.md)). Facts are from source code at the tagged release, official docs, PyPI and the Hugging Face model repo. Terminology is defined in [CONTEXT.md](../../CONTEXT.md).

## Package versions

| Package | Latest on PyPI (2026-09-28) | Locked in `uv.lock` | Notes |
|---|---|---|---|
| `chromadb` | 1.5.9 (2026-05-05) | 1.5.9 | [PyPI](https://pypi.org/project/chromadb/), [releases](https://github.com/chroma-core/chroma/releases) |
| `langchain-chroma` | 1.1.0 (2025-12-12) | 1.1.0 | requires `chromadb>=1.3.5,<2`, `langchain-core>=1.1.3,<2` ([PyPI](https://pypi.org/project/langchain-chroma/)) |
| `langchain-huggingface` | 1.2.2 (2026-04-16) | 1.2.2 | the `[full]` extra pins `sentence-transformers>=5.2.0,<6` ([PyPI](https://pypi.org/project/langchain-huggingface/)) |
| `sentence-transformers` | 6.1.0 (2026-09-18) | 6.0.1 | requires `transformers>=5,<6`, `torch>=2.2` ([PyPI](https://pypi.org/project/sentence-transformers/)) |
| `langchain-core` | 1.6.5 | 1.6.3 | |

`langchain-chroma` and `langchain-huggingface` are the current integration packages (the classes in `langchain_community` are the older copies).

**Version tension:** the project locks `sentence-transformers` 6.0.1, but `langchain-huggingface[full]` asks for `<6`. The project installs `langchain-huggingface` without the extra, so nothing blocks it. `HuggingFaceEmbeddings` only calls `SentenceTransformer(...)` and `.encode(...)`, and the [v5→v6 migration guide](https://sbert.net/docs/migration_guide.html) lists no change to `encode`'s `prompt`, `prompt_name` or `normalize_embeddings` arguments. Still, check it with a smoke test.

## 1. Can Chroma metadata hold lists?

**Yes, since `chromadb` 1.5.0.** Lists are rejected in 1.4.0 and accepted in 1.5.0 and 1.5.9 (`validate_metadata` in [`chromadb/api/types.py` @1.5.9](https://github.com/chroma-core/chroma/blob/1.5.9/chromadb/api/types.py); the 1.4.0 docstring says "strings, ints, floats, bools, or SparseVectors", and 1.5.0 adds "or lists thereof").

Rules ([metadata filtering docs](https://docs.trychroma.com/docs/querying-collections/metadata-filtering) and the 1.5.9 validator):
- elements must be `str`, `int`, `float` or `bool`, all of the **same type**
- **empty lists are rejected** (`Expected metadata list value for key '…' to be non-empty`)
- **no nested lists, and no dicts** (a list of objects is not allowed)
- filter with `$contains` / `$not_contains`, passing a scalar of the element type

**langchain-chroma passes lists through unchanged.** `add_texts` hands `metadatas` straight to `collection.upsert(...)`. The only handling is a `ValueError` catch that appends a hint to use `filter_complex_metadata` ([vectorstores.py @langchain-chroma==1.1.0](https://github.com/langchain-ai/langchain/blob/langchain-chroma%3D%3D1.1.0/libs/partners/chroma/langchain_chroma/vectorstores.py)). That hint is out of date now that Chroma accepts lists.

**Known bug (open):** `delete_collection` on a persistent client leaves list-valued metadata behind, and a new collection can inherit it ([issue #7594](https://github.com/chroma-core/chroma/issues/7594), fix PR [#7595](https://github.com/chroma-core/chroma/pull/7595) still open on 2026-08-16). Deleting the whole persist directory instead of calling `delete_collection` avoids it.

What this means for the Chunk metadata in the design:
- `screenshots` (list of str) and `versions` (list of str) fit, **except when empty**. A page without Screenshots would fail, so the field must be left out or replaced by a sentinel.
- `page_links` (list of `{title, page_file}`) does **not** fit as-is. Store it as two parallel string lists, as a JSON string, or not at all in Chroma.

## 2. Cosine distance on a collection

**Current API: collection configuration** ([Configure docs](https://docs.trychroma.com/docs/collections/configure)):

```python
configuration={"hnsw": {"space": "cosine"}}
```

- The values are `l2` (default), `cosine` and `ip`. Local (single-node) Chroma uses HNSW; SPANN is for distributed Chroma and Chroma Cloud.
- If no space is set, it falls back to the embedding function's `default_space()`, or to `l2` when there is no embedding function. langchain-chroma always passes `embedding_function=None` to Chroma, so the fallback is **`l2`** (`populate_create_hnsw_defaults` in [collection_configuration.py @1.5.9](https://github.com/chroma-core/chroma/blob/1.5.9/chromadb/api/collection_configuration.py)).
- **`space` can't be changed after the collection is created.** `UpdateHNSWConfiguration` only allows `ef_search`, `num_threads` and similar settings.
- **Legacy `metadata={"hnsw:space": "cosine"}` still works.** 1.5.9 keeps a mapping from `hnsw:*` metadata keys to the new configuration, and its release notes include "[BUG] preserve legacy hnsw: metadata keys". When both are given, the configuration wins.

Formulas (Configure docs):
- cosine: `d = 1 − cos(A, B)`
- l2 is **squared** L2: `d = Σ(Aᵢ − Bᵢ)²`
- ip: `d = 1 − A·B`

**In langchain-chroma 1.1.0**, `Chroma(..., collection_configuration={"hnsw": {"space": "cosine"}})` is passed to `get_or_create_collection(configuration=...)`. The `collection_metadata=` argument is also still there. The docstring of `_select_relevance_score_fn` says the metric "must be provided in `collection_configuration`". The method reads `self._collection.configuration["hnsw"]["space"]` (or `spann`). I did not check with a run whether a collection created only through legacy metadata reports `space` in `.configuration`, so passing `collection_configuration` is the path that is sure to work.

### What score Langchain returns

- **`similarity_search_with_score`** returns Chroma's raw **distance**, where lower is better. With cosine that is `1 − cos_sim`, in the range [0, 2].
- **`similarity_search_with_relevance_scores`** maps distance to relevance with a function chosen by space ([langchain_core/vectorstores/base.py](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/vectorstores/base.py)):
  - cosine → `1 − distance`, which is exactly the **cosine similarity**
  - l2 → `1 − distance/√2`, which is wrong for Chroma's *squared* L2 on unit vectors (d ∈ [0, 4]) and can go negative
  - ip → `1 − distance` if distance > 0, else `−distance`
  - any other value raises `ValueError`, unless you pass `relevance_score_fn=` to the constructor
  - if a score falls outside [0, 1], core only logs a warning; `score_threshold` filters on the relevance score
- With e5, cosine similarities normally fall between **0.7 and 1.0** because of the low training temperature ([model card](https://huggingface.co/intfloat/multilingual-e5-base)). The card says relative order matters, not absolute values. A fixed "not in the Manual" threshold would have to be set within that narrow band.

## 3. e5 prefixes and normalisation

Facts from the model card and the repo at [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base) (last modified 2026-04-02, sha `d1287505…`):
- Use `query: ` for questions and `passage: ` for passages in asymmetric retrieval. The card's example calls `model.encode(texts, normalize_embeddings=True)`.
- The model is XLM-R base: 12 layers, 768 dimensions, `max_seq_length` 512 (`sentence_bert_config.json`). Longer inputs are **silently truncated**.
- `modules.json` is `Transformer → Pooling → Normalize`, so **sentence-transformers already L2-normalises the output**. `normalize_embeddings=True` changes nothing, but it is cheap insurance.
- The repo has **no `config_sentence_transformers.json`**, so it defines no built-in `query` / `passage` prompts. You must supply them yourself.

`HuggingFaceEmbeddings` in 1.2.2 ([huggingface.py @langchain-huggingface==1.2.2](https://github.com/langchain-ai/langchain/blob/langchain-huggingface%3D%3D1.2.2/libs/partners/huggingface/langchain_huggingface/embeddings/huggingface.py)):
- `model_kwargs` go to `SentenceTransformer(model_name, cache_folder=…, **model_kwargs)`, for example `prompts` and `default_prompt_name`.
- `encode_kwargs` go to `encode(...)` in `embed_documents`, for example `prompt`, `prompt_name`, `normalize_embeddings` and `batch_size`.
- `query_encode_kwargs` are used by `embed_query` **instead of** `encode_kwargs`, not merged with them, whenever they are non-empty. Anything the query also needs, such as normalisation, must be repeated there.
- It replaces `\n` with a space in every text before encoding.
- With `multi_process=True`, the `encode_kwargs` are **not** passed on, so the prefixes would be lost.

The sentence-transformers [prompt templates](https://sbert.net/examples/sentence_transformer/applications/computing-embeddings/README.html) docs:
- `SentenceTransformer(..., prompts={"query": "query: ", "passage": "passage: "})`, then `encode(..., prompt_name="query")`
- or `encode(..., prompt="query: ")` directly
- the docs name e5 as an example model that needs `query: ` / `passage: `

The options, all using real public APIs:

**A. Only `HuggingFaceEmbeddings` configuration** (no custom class):
```python
HuggingFaceEmbeddings(
    model_name="intfloat/multilingual-e5-base",
    encode_kwargs={"prompt": "passage: ", "normalize_embeddings": True},
    query_encode_kwargs={"prompt": "query: ", "normalize_embeddings": True},
)
```
(Or put `prompts=` in `model_kwargs` and use `prompt_name`.) The prefix is added inside sentence-transformers, so the text stored in Chroma stays clean.

**B. A small `Embeddings` subclass** (`embed_documents` / `embed_query` add the prefix, then delegate). This takes a few more lines, but the prefix rule is explicit, easy to unit-test without the model, and doesn't depend on the kwargs semantics above.

## Implications for the embed decisions (facts and options, not decisions)

- **D16:** "Chroma metadata only holds single values" is **no longer true** from `chromadb` 1.5.0, and the project already pins `>=1.5.9`.
  - Lists of strings work, including `$contains` filtering (useful later for `versions`).
  - **Empty lists and lists of dicts are not accepted**, so `page_links` as `{title, page_file}` objects and empty `screenshots` still need handling.
  - Two options: (a) keep scalars only in Chroma and look up the chunked JSON by `chunk_id`, as recommended; or (b) store non-empty string lists directly and flatten or omit `page_links`.
- **D17 (cosine):** pass `collection_configuration={"hnsw": {"space": "cosine"}}` when the collection is created.
  - Without it the space is `l2`, and Langchain's relevance scores are then miscalibrated.
  - With cosine, `similarity_search_with_relevance_scores` gives cosine similarity directly. For e5 that usually falls between 0.7 and 1.0, which suits a debug-panel score. A "not covered" threshold would need tuning in that band.
  - `similarity_search_with_score` gives `1 − similarity`.
- **D17 (prefixes):** both option A (kwargs, no custom code) and option B (a thin wrapper) work.
  - With A, `query_encode_kwargs` replaces `encode_kwargs` for queries, so both need `normalize_embeddings`.
  - Avoid `multi_process=True` in either case.
  - Normalisation is already built into the model; the flag is redundant.
- **D18:** deleting the store folder on every rebuild also sidesteps the open `delete_collection` array-metadata bug and the fact that `space` can't be changed on an existing collection.
- **D13 (token check):** the 512-token limit is enforced by silent truncation. The `passage: ` prefix counts towards the 512 tokens, so a token check should include it.
- **Versions:** consider pinning `sentence-transformers<6` or smoke-testing 6.x, because `langchain-huggingface`'s own extra caps it at `<6`.
