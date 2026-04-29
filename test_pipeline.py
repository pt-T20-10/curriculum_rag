# # test_pipeline.py
# """
# Pipeline test script for crawl + RAG context quality verification.

# Tests the following components in order:
#     Step 0 — Clear ChromaDB
#     Step 1 — Ingestion (crawl + chunk + filter + embed)
#     Step 2 — ChromaDB stats (domain distribution, chunk count)
#     Step 3 — Researcher retrieval quality (heuristic + LLM filter)
#     Step 4 — ContextRetrievalAgent enrichment (tool calls + raw chunk collection)

# Usage:
#     python test_pipeline.py
#     python test_pipeline.py --topic "Yoga cơ bản" --query "yoga breathing poses"
# """

# import sys
# import shutil
# import argparse
# sys.path.insert(0, ".")

# from src.config import setup_directories
# setup_directories()

# # ═══════════════════════════════════════════════════════════
# # CLI arguments — override defaults below if needed
# # ═══════════════════════════════════════════════════════════
# parser = argparse.ArgumentParser(description="Test pipeline for crawl + RAG quality")
# parser.add_argument("--topic", default=None, help="Topic to ingest")
# parser.add_argument("--content-type", default=None, 
#                     choices=["scholarly", "technical", "practical", "lifestyle"],
#                     help="Force content type (auto-detected if not provided)")
# args = parser.parse_args()

# # ── Test configuration with auto-query selection ──────────────
# # If --topic provided, use it; otherwise use default scholarly topic
# TEST_TOPIC = args.topic or "Triết học Phương Tây"

# # Query mapping per content_type — auto-select based on validator result
# QUERY_PRESETS = {
#     "scholarly": {
#         "rag_query": "ancient Greek philosophy Socrates Plato",
#         "tool_query": "Western philosophy epistemology rationalism",
#     },
#     "technical": {
#         "rag_query": "supervised learning classification algorithms",
#         "tool_query": "gradient descent optimization neural network",
#     },
#     "practical": {
#         "rag_query": "basic Japanese cooking techniques step by step",
#         "tool_query": "sushi ramen dashi miso soup preparation",
#     },
#     "lifestyle": {
#         "rag_query": "beginner yoga poses breathing techniques",
#         "tool_query": "yoga health benefits meditation mindfulness",
#     },
# }

# # ─────────────────────────────────────────────────────────────
# # STEP 0: Clear ChromaDB
# # ─────────────────────────────────────────────────────────────
# print("=" * 60)
# print("STEP 0: CLEAR CHROMADB")
# print("=" * 60)
# shutil.rmtree("data/chroma_db", ignore_errors=True)
# print("✓ ChromaDB cleared")

# # ─────────────────────────────────────────────────────────────
# # STEP 1: Ingestion
# # ─────────────────────────────────────────────────────────────
# print("\n" + "=" * 60)
# print(f"STEP 1: INGESTION — topic: '{TEST_TOPIC}'")
# print("=" * 60)

# from src.agents.validator import validate_topic
# from src.agents.query_expansion import QueryExpansionAgent
# from src.ingestion.search_engine import search_web
# from src.ingestion.url_filter import filter_and_classify_urls
# from src.ingestion.crawler import ingest_dynamic_data

# # Validate — get content_type
# validation   = validate_topic(TEST_TOPIC)
# content_type = validation.get("content_type", "technical")

# # Override with --content-type if provided
# if args.content_type:
#     content_type = args.content_type
#     print(f"Content type overridden: {content_type}")
    
# # Auto-select queries based on content_type
# query_preset = QUERY_PRESETS.get(content_type, QUERY_PRESETS["technical"])
# RAG_QUERY = query_preset["rag_query"]
# TOOL_QUERY = query_preset["tool_query"]

# print(f"Validator  : valid={validation.get('valid')} | content_type={content_type}")
# print(f"Auto-selected queries for content_type='{content_type}':")
# print(f"  RAG_QUERY  : {RAG_QUERY}")
# print(f"  TOOL_QUERY : {TOOL_QUERY}")

# # Expand queries
# qe      = QueryExpansionAgent()
# queries = qe.expand_query_bilingual(TEST_TOPIC, content_type=content_type)
# print(f"VI queries : {queries['vi']}")
# print(f"EN queries : {queries['en']}")
# # Search
# all_results: list[dict] = []
# for q in queries["vi"]:
#     results = search_web(q, max_results=20, region="vn-vn")
#     all_results.extend(results)
# for q in queries["en"]:
#     results = search_web(q, max_results=20, region="us-en")
#     all_results.extend(results)

# for r in all_results:
#     r["_topic"] = TEST_TOPIC

# all_urls = [r["href"] for r in all_results]
# print(f"\nTotal URLs from search : {len(all_urls)}")

# # Filter + classify
# clean_links = filter_and_classify_urls(
#     all_urls,
#     scored_results=all_results,
#     topic=TEST_TOPIC,
#     content_type=content_type,
# )
# print(f"Clean links after filter : {len(clean_links)}")

# # Ingest
# success = ingest_dynamic_data(TEST_TOPIC, clean_links, content_type=content_type)
# print(f"Ingestion success : {success}")

# # ─────────────────────────────────────────────────────────────
# # STEP 1.5: CLASSIFICATION VERIFICATION
# # ─────────────────────────────────────────────────────────────
# print("\n" + "=" * 60)
# print("STEP 1.5: CLASSIFICATION VERIFICATION")
# print("=" * 60)

# from src.ingestion.crawler import classify_page, _PAGE_EDUCATIONAL, _PAGE_NAVIGATION, _PAGE_JUNK
# from src.ingestion.crawler import fetch_text_from_url
# from collections import Counter

# # Sample representative URLs for classification review
# # Take first 20 clean links to verify classifier behavior
# sample_urls = clean_links[:20] if len(clean_links) >= 20 else clean_links

# classify_results = []
# print(f"Classifying {len(sample_urls)} sample URLs...\n")

# for url_info in sample_urls:
#     url = url_info if isinstance(url_info, str) else url_info.get("url", "")
    
#     # Fetch text — handle tuple return (text, final_url)
#     fetch_result = fetch_text_from_url(url)
#     if isinstance(fetch_result, tuple):
#         text, _ = fetch_result  # Unpack (text, url_final)
#     else:
#         text = fetch_result  # Fallback if returns string
    
#     if not text:
#         continue
        
#     classification = classify_page(text, url, content_type=content_type)
    
#     # Determine label
#     if classification == _PAGE_EDUCATIONAL:
#         label = "EDU"
#     elif classification == _PAGE_NAVIGATION:
#         label = "NAV"
#     else:
#         label = "JUNK"
    
#     classify_results.append({
#         "url": url,
#         "label": label,
#         "text_len": len(text),
#     })

# # Print results table
# print(f"{'Label':<6} {'Text Len':<10} {'URL':<60}")
# print("-" * 80)

# for result in classify_results:
#     # Truncate URL for display
#     url_display = result["url"][:60]
#     print(f"{result['label']:<6} {result['text_len']:<10} {url_display}")

# # Distribution summary
# label_counter = Counter(r["label"] for r in classify_results)
# print("\n" + "-" * 80)
# print(f"Classification Distribution:")
# print(f"  EDUCATIONAL : {label_counter.get('EDU', 0):3d} ({100*label_counter.get('EDU', 0)//len(classify_results) if classify_results else 0}%)")
# print(f"  NAVIGATION  : {label_counter.get('NAV', 0):3d} ({100*label_counter.get('NAV', 0)//len(classify_results) if classify_results else 0}%)")
# print(f"  JUNK        : {label_counter.get('JUNK', 0):3d} ({100*label_counter.get('JUNK', 0)//len(classify_results) if classify_results else 0}%)")

# # Highlight special cases to verify fixes
# print("\n" + "-" * 80)
# print("Special Cases Verification:")

# # Check for wikihow (should be EDU for practical/lifestyle)
# wikihow_found = [r for r in classify_results if "wikihow.com" in r["url"].lower()]
# if wikihow_found:
#     for w in wikihow_found:
#         status = "✓ PASS" if w["label"] == "EDU" else "✗ FAIL"
#         print(f"  wikihow.com → {w['label']:<6} {status}")
# else:
#     print(f"  wikihow.com → not in sample")

# # Check for news sites (should be JUNK)
# news_domains = ["vtcnews", "dantri", "tuoitre", "vnexpress", "thanhnien"]
# news_found = [r for r in classify_results if any(d in r["url"].lower() for d in news_domains)]
# if news_found:
#     for n in news_found:
#         status = "✓ PASS" if n["label"] == "JUNK" else "✗ FAIL"
#         domain = next(d for d in news_domains if d in n["url"].lower())
#         print(f"  {domain} → {n['label']:<6} {status}")
# else:
#     print(f"  news sites → not in sample")

# # Check for listing sites (should be JUNK)
# listing_domains = ["toplist.vn", "cali.vn", "topshop.com", "mcivietnam.com"]
# listing_found = [r for r in classify_results if any(d in r["url"].lower() for d in listing_domains)]
# if listing_found:
#     for l in listing_found:
#         status = "✓ PASS" if l["label"] == "JUNK" else "✗ FAIL"
#         domain = next(d for d in listing_domains if d in l["url"].lower())
#         print(f"  {domain} → {l['label']:<6} {status}")
# else:
#     print(f"  listing sites → not in sample")

# print("-" * 80)

# # ─────────────────────────────────────────────────────────────
# # STEP 2: ChromaDB stats
# # ─────────────────────────────────────────────────────────────
# print("\n" + "=" * 60)
# print("STEP 2: CHROMADB STATS")
# print("=" * 60)

# from collections import Counter
# from src.agents.researcher import _get_researcher
# from urllib.parse import urlparse

# researcher = _get_researcher()
# collection = researcher.vector_db._collection
# all_data   = collection.get(include=["metadatas"])
# metadatas  = all_data["metadatas"] or []  # type: ignore

# total_chunks = len(metadatas)
# print(f"Total chunks in ChromaDB : {total_chunks}")

# # Domain distribution
# domain_counter: Counter = Counter()
# for m in metadatas:
#     src    = m.get("source", "")
#     domain = urlparse(src).netloc.lower() #type: ignore
#     # Normalize mobile subdomains
#     import re
#     domain = re.sub(r'^([a-z]{2,3}\.)?m\.', lambda x: x.group(1) or '', domain)
#     domain_counter[domain] += 1

# print(f"\nTop 15 domains:")
# for domain, count in domain_counter.most_common(15):
#     bar = "█" * min(count, 30)
#     print(f"  {count:3d}  {bar}  {domain}")

# # Quality signal: how many chunks likely from high-value sources
# trusted = (
#     "wikipedia.org", "britannica.com", "openstax.org", "ocw.mit.edu",
#     "stanford.edu", "mit.edu", "arxiv.org", "geeksforgeeks.org",
#     "pmc.ncbi.nlm.nih.gov", "iep.utm.edu", "plato.stanford.edu",
#     "triethoc.edu.vn", "machinelearningcoban.com",
# )
# trusted_count = sum(
#     c for d, c in domain_counter.items()
#     if any(t in d for t in trusted)
# )
# print(f"\nTrusted edu domain chunks : {trusted_count}/{total_chunks} "
#       f"({100*trusted_count//total_chunks if total_chunks else 0}%)")

# # ─────────────────────────────────────────────────────────────
# # STEP 3: Researcher retrieval quality
# # ─────────────────────────────────────────────────────────────
# print("\n" + "=" * 60)
# print(f"STEP 3: RETRIEVAL QUALITY — query: '{RAG_QUERY}'")
# print("=" * 60)

# researcher.reset_retrieved_ids()
# context = researcher.retrieve_context(RAG_QUERY, k=3)

# if not context:
#     print("⚠️  No context retrieved — check quality filter thresholds")
# else:
#     print(f"Retrieved context : {len(context)} chars")
#     print(f"\n--- Context preview (first 600 chars) ---")
#     print(context[:600])
#     print("--- end preview ---")

#     # Count how many Documents were returned
#     doc_count = context.count("Document ")
#     print(f"\nDocument chunks in context : {doc_count}")

#     # Check for known junk patterns as sanity check
#     JUNK_SIGNALS = [
#         "Volume:", "Issue:", "DOI:", "Received:",          # paper metadata
#         "Unit 1:", "Unit 2:", "Week 1:", "Module 1:",      # course outline
#         "Đăng nhập", "Trang chủ", "Giỏ hàng",             # navigation
#         "Download PDF", "Read Download",                    # aggregator
#         "Children's Encyclopedia", "Ages 8-11",             # kids content
#     ]
#     junk_found = [s for s in JUNK_SIGNALS if s in context]
#     if junk_found:
#         print(f"\n⚠️  Junk signals detected in context: {junk_found}")
#     else:
#         print(f"\n✓ No known junk signals detected in retrieved context")

# # ─────────────────────────────────────────────────────────────
# # STEP 4: ContextRetrievalAgent enrichment
# # ─────────────────────────────────────────────────────────────
# print("\n" + "=" * 60)
# print(f"STEP 4: CONTEXT ENRICHMENT — tool query: '{TOOL_QUERY}'")
# print("=" * 60)

# from src.agents.writer import ContextRetrievalAgent

# retriever = ContextRetrievalAgent()

# # Simulate initial context being thin
# thin_context = context[:300] if context else "No initial context."

# enriched, queries_used = retriever.enrich_context(
#     section_description=f"Key concepts and principles of {TEST_TOPIC}",
#     section_type="medium",
#     initial_context=thin_context,
#     section_summaries=[],
#     revision_feedback="",
#     used_queries=[],
# )

# print(f"Queries used in tool calls : {queries_used}")
# print(f"Enriched context length    : {len(enriched)} chars")
# print(f"\n--- Enriched context preview (first 600 chars) ---")
# print(enriched[:600])
# print("--- end preview ---")

# # Verify raw chunks were collected (not LLM synthesis)
# if "---" in enriched:
#     parts = [p.strip() for p in enriched.split("---") if p.strip()]
#     print(f"\nContext parts (initial + fetched chunks) : {len(parts)}")
# else:
#     print(f"\nNote: only initial context returned (no tool calls triggered)")

# # Junk check on enriched context
# junk_found_enriched = [s for s in JUNK_SIGNALS if s in enriched]
# if junk_found_enriched:
#     print(f"\n⚠️  Junk signals in enriched context: {junk_found_enriched}")
# else:
#     print(f"\n✓ No known junk signals in enriched context")

# # ─────────────────────────────────────────────────────────────
# # SUMMARY
# # ─────────────────────────────────────────────────────────────
# print("\n" + "=" * 60)
# print(f"TEST COMPLETE — topic: '{TEST_TOPIC}'")
# print(f"  ChromaDB chunks  : {total_chunks}")
# print(f"  Trusted domains  : {trusted_count}/{total_chunks}")
# print(f"  Initial context  : {len(context)} chars")
# print(f"  Enriched context : {len(enriched)} chars")
# print(f"  Tool queries     : {queries_used}")
# print("=" * 60)
# print("Check logs: logs/agents.log | logs/rag_context.log | logs/crawler.log")