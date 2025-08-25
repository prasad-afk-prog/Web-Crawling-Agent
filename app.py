import os
os.system("playwright install chromium")

import streamlit as st
import asyncio
import json
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy


# ------------------- URL VALIDATION -------------------
def is_valid_url(url: str) -> bool:
    """Validate if the provided string is a valid URL"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


# ------------------- LINK VALIDATION -------------------
def is_internal_link(base, link):
    if not link or link.startswith("#") or link.startswith("mailto:"):
        return False
    parsed_base = urlparse(base)
    parsed_link = urlparse(link)
    return parsed_link.netloc == "" or parsed_link.netloc == parsed_base.netloc


# ------------------- CRAWLER STATISTICS -------------------
async def crawl_single_website(start_url, max_depth=2):
    browser_cfg = BrowserConfig(browser_type="firefox", headless=True)
    schema = {
        "name": "Services",
        "baseSelector": "li, a, div, section, h2, h3",
        "fields": [
            {"name": "text", "selector": "*", "type": "text"},
            {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
        ],
    }
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=JsonCssExtractionStrategy(schema),
        word_count_threshold=5,
        remove_overlay_elements=True,
        wait_for="css:body",
    )

    site_data = {}
    visited_urls = set()
    stats = {
        "total_pages_found": 0,
        "successful_pages": 0,
        "failed_pages": 0,
        "navigation_errors": 0,
        "extraction_errors": 0,
        "error_log": [],
    }

    async def crawl(url, depth):
        if url in visited_urls or depth > max_depth:
            return
        stats["total_pages_found"] += 1
        visited_urls.add(url)

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            try:
                result = await crawler.arun(url=url, config=run_cfg)
                if result.success:
                    try:
                        if result.extracted_content:
                            page_data = json.loads(result.extracted_content)
                            site_data[url] = {"url": url, "data": page_data}
                            stats["successful_pages"] += 1
                        else:
                            stats["extraction_errors"] += 1
                            stats["failed_pages"] += 1
                            stats["error_log"].append(f"Empty content at: {url}")
                    except Exception as e:
                        stats["extraction_errors"] += 1
                        stats["failed_pages"] += 1
                        stats["error_log"].append(f"Extraction error at {url}: {str(e)}")
                else:
                    stats["extraction_errors"] += 1
                    stats["failed_pages"] += 1
                    stats["error_log"].append(f"Crawl failed at {url}: {result.error_message}")
            except RuntimeError as e:
                if "ACS-GOTO" in str(e):
                    # Catch ACS-GOTO navigation errors (e.g., PDFs, unsupported content)
                    stats["navigation_errors"] += 1
                    stats["failed_pages"] += 1
                    stats["error_log"].append(f"Navigation error (ACS-GOTO) at {url}: {str(e)}")
                else:
                    # Catch other RuntimeError cases
                    stats["navigation_errors"] += 1
                    stats["failed_pages"] += 1
                    stats["error_log"].append(f"Navigation error at {url}: {str(e)}")
            except Exception as e:
                stats["navigation_errors"] += 1
                stats["failed_pages"] += 1
                stats["error_log"].append(f"Unexpected error at {url}: {str(e)}")

            # Follow internal links
            if "result" in locals() and hasattr(result, "links"):
                for link in result.links.get("internal", []):
                    href = link.get("href", "")
                    full_url = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")
                    if is_internal_link(url, href):
                        await crawl(full_url, depth + 1)

    await crawl(start_url, 0)
    return site_data, stats


# ------------------- SAVE RESULTS -------------------
def save_results_to_json(data, url):
    """Save crawl results into JSON file inside /crawl_results, named after domain"""
    directory = "crawl_results"
    # Create directory if not exists
    os.makedirs(directory, exist_ok=True)
    
    domain = urlparse(url).netloc.replace(".", "_")
    filename = f"{domain}.json"
    filepath = os.path.join(directory, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    return filepath

# ------------------- STREAMLIT APP -------------------
def main():
    st.title("Web Crawler")

    url = st.text_input("Enter a website URL:", "https://www.envigo.co.in")
    max_depth = st.slider("Max crawl depth", 1, 3, 2)

    if st.button("🚀 Start Crawling"):
        if not is_valid_url(url):
            st.error("❌ Invalid URL. Please enter a valid URL (e.g. https://example.com)")
            return

        st.info(f"Valid URL ✅ Crawling {url} ... Please wait.")
        progress = st.progress(0)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results, stats = loop.run_until_complete(crawl_single_website(url, max_depth=max_depth))

        progress.progress(100)

        st.subheader("Crawl Statistics")
        st.markdown(f"**Total pages discovered:** {stats['total_pages_found']}")
        st.markdown(f"**Successful pages crawled:** {stats['successful_pages']}")
        st.markdown(f"**Failed to crawl (total):** {stats['failed_pages']}")
        st.markdown(f"**Navigation errors (e.g., PDFs):** {stats['navigation_errors']}")
        st.markdown(f"**Extraction/content errors:** {stats['extraction_errors']}")

        if results:
            filename = save_results_to_json(results, url)
            st.success(f"✅ Crawl completed. Results saved to `{filename}`")
        else:
            st.warning("No data extracted.")


if __name__ == "__main__":
    main()
