#!/usr/bin/env python3
"""
Sync publications from ORCID to Jekyll _publications folder.
Preserves manual overrides defined in _data/publication_overrides.yml
"""

import requests
import yaml
import re
import os
from datetime import datetime
from pathlib import Path

ORCID_ID = "0009-0009-5849-1889"
ORCID_API_URL = f"https://pub.orcid.org/v3.0/{ORCID_ID}/works"
REPO_ROOT = Path(__file__).parent.parent
PUBLICATIONS_DIR = REPO_ROOT / "_publications"
OVERRIDES_FILE = REPO_ROOT / "_data" / "publication_overrides.yml"


def fetch_orcid_works():
    """Fetch all works from ORCID public API."""
    headers = {"Accept": "application/json"}
    response = requests.get(ORCID_API_URL, headers=headers)
    response.raise_for_status()
    return response.json()


def fetch_work_details(put_code):
    """Fetch detailed information for a specific work."""
    url = f"https://pub.orcid.org/v3.0/{ORCID_ID}/work/{put_code}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def load_overrides():
    """Load publication overrides from YAML file."""
    if OVERRIDES_FILE.exists():
        with open(OVERRIDES_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def extract_date(work):
    """Extract publication date from work data."""
    pub_date = work.get("publication-date")
    if not pub_date:
        return None, None

    year_obj = pub_date.get("year")
    year = year_obj.get("value") if year_obj else None

    if not year:
        return None, None

    month_obj = pub_date.get("month")
    day_obj = pub_date.get("day")

    month = month_obj.get("value") if month_obj else "01"
    day = day_obj.get("value") if day_obj else "01"

    # Pad month and day
    month = str(month).zfill(2) if month else "01"
    day = str(day).zfill(2) if day else "01"

    date_str = f"{year}-{month}-{day}"
    return date_str, year


def extract_venue(work):
    """Extract venue/journal name from work data."""
    journal = work.get("journal-title")
    if journal and journal.get("value"):
        return journal["value"]
    return None


def extract_doi_url(work):
    """Extract DOI URL from work external IDs."""
    external_ids = work.get("external-ids", {}).get("external-id", [])
    for ext_id in external_ids:
        if ext_id.get("external-id-type") == "doi":
            doi = ext_id.get("external-id-value")
            if doi:
                return f"https://doi.org/{doi}"
    return None


def extract_url(work):
    """Extract any available URL for the work."""
    # First try DOI
    doi_url = extract_doi_url(work)
    if doi_url:
        return doi_url

    # Then try work URL
    url_obj = work.get("url")
    if url_obj and url_obj.get("value"):
        return url_obj["value"]

    return None


def extract_authors(work):
    """Extract author list from work contributors."""
    contributors = work.get("contributors", {}).get("contributor", [])
    authors = []

    for contrib in contributors:
        name_obj = contrib.get("credit-name")
        if name_obj and name_obj.get("value"):
            authors.append(name_obj["value"])

    return authors


def format_citation(title, authors, venue, year):
    """Format a basic citation string."""
    if not authors:
        author_str = ""
    elif len(authors) == 1:
        author_str = authors[0]
    elif len(authors) == 2:
        author_str = f"{authors[0]} & {authors[1]}"
    else:
        author_str = ", ".join(authors[:-1]) + f", & {authors[-1]}"

    parts = []
    if author_str:
        parts.append(author_str)
    if year:
        parts.append(f"({year})")

    title_escaped = title.replace('"', '&quot;')
    parts.append(f'&quot;{title_escaped}.&quot;')

    if venue:
        parts.append(f"<i>{venue}</i>.")

    return " ".join(parts)


def slugify(text):
    """Convert text to URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')[:50]


def generate_filename(date_str, title):
    """Generate filename for publication."""
    slug = slugify(title)
    if date_str:
        return f"{date_str}-{slug}.md"
    return f"{slug}.md"


def generate_permalink(date_str, title):
    """Generate permalink for publication."""
    slug = slugify(title)
    if date_str:
        return f"/publication/{date_str}-{slug}"
    return f"/publication/{slug}"


def work_to_markdown(work, overrides):
    """Convert ORCID work to Jekyll markdown front matter."""
    title = work.get("title", {}).get("title", {}).get("value", "Untitled")
    date_str, year = extract_date(work)
    venue = extract_venue(work)
    paper_url = extract_url(work)
    authors = extract_authors(work)

    # Generate identifiers
    put_code = str(work.get("put-code", ""))
    filename = generate_filename(date_str, title)
    permalink = generate_permalink(date_str, title)

    # Build front matter
    front_matter = {
        "title": title,
        "collection": "publications",
        "permalink": permalink,
    }

    if date_str:
        front_matter["date"] = date_str

    if venue:
        front_matter["venue"] = venue

    if paper_url:
        front_matter["paperurl"] = paper_url

    # Generate citation
    citation = format_citation(title, authors, venue, year)
    if citation:
        front_matter["citation"] = citation

    # Apply overrides (by put_code or title match)
    override_key = None
    if put_code in overrides:
        override_key = put_code
    else:
        # Try matching by title (case-insensitive)
        title_lower = title.lower()
        for key, val in overrides.items():
            if isinstance(val, dict) and val.get("title_match", "").lower() in title_lower:
                override_key = key
                break

    if override_key and override_key in overrides:
        override = overrides[override_key]
        if isinstance(override, dict):
            # Skip if marked as skip
            if override.get("skip"):
                return None, None

            # Apply field overrides
            for field in ["status", "venue", "paperurl", "citation", "date", "permalink"]:
                if field in override:
                    front_matter[field] = override[field]

            # Custom filename
            if "filename" in override:
                filename = override["filename"]

    # Generate YAML
    yaml_content = "---\n"
    yaml_content += yaml.dump(front_matter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    yaml_content += "---\n"

    return filename, yaml_content


def cleanup_auto_generated(manual_files):
    """Remove auto-generated publication files, keeping manual ones."""
    if not PUBLICATIONS_DIR.exists():
        return

    for filepath in PUBLICATIONS_DIR.glob("*.md"):
        if filepath.name not in manual_files:
            print(f"  Removing old file: {filepath.name}")
            filepath.unlink()


def sync_publications():
    """Main sync function."""
    print(f"Fetching works from ORCID: {ORCID_ID}")

    # Fetch works summary
    works_data = fetch_orcid_works()
    work_groups = works_data.get("group", [])

    print(f"Found {len(work_groups)} work groups")

    # Load overrides
    overrides = load_overrides()
    print(f"Loaded {len(overrides)} overrides")

    # Get list of manual files to preserve
    manual_files = set(overrides.get("_manual_files", []))
    print(f"Manual files to preserve: {manual_files}")

    # Clean up old auto-generated files
    print("\nCleaning up old auto-generated files...")
    cleanup_auto_generated(manual_files)

    # Ensure publications directory exists
    PUBLICATIONS_DIR.mkdir(exist_ok=True)

    # Track generated files
    generated_files = set()

    print("\nGenerating publication files from ORCID...")
    for group in work_groups:
        work_summaries = group.get("work-summary", [])
        if not work_summaries:
            continue

        # Use the first (preferred) work summary
        summary = work_summaries[0]
        put_code = summary.get("put-code")

        # Fetch full work details
        print(f"Fetching details for put-code: {put_code}")
        work = fetch_work_details(put_code)

        # Convert to markdown
        filename, content = work_to_markdown(work, overrides)

        if filename is None:
            print(f"  Skipped (marked in overrides)")
            continue

        # Write file
        filepath = PUBLICATIONS_DIR / filename
        with open(filepath, "w") as f:
            f.write(content)

        print(f"  -> {filename}")
        generated_files.add(filename)

    print(f"\nSync complete. Generated {len(generated_files)} publication files.")
    print(f"Manual files preserved: {len(manual_files)}")
    return generated_files


if __name__ == "__main__":
    sync_publications()
