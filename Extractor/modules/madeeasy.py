import requests
import asyncio
import aiohttp
import os
import re
import unicodedata
import time
from datetime import datetime
import pytz

india_timezone = pytz.timezone('Asia/Kolkata')
current_time = datetime.now(india_timezone)
time_new = current_time.strftime("%d-%m-%Y %I:%M %p")

# TODO: sniff karke sahi API base URL daalo
BASE_URL = "https://api.madeeasy.in/v1"

async def fetch_content(session, url, headers) -> dict:
    async with session.get(url, headers=headers) as response:
        return await response.json()

async def process_subject_content(session, batch_id, subject_id, headers, all_links, total_links):
    tasks = []
    for page in range(1, 12):  # max 12 pages (adjust as needed)
        url = f"{BASE_URL}/batches/{batch_id}/subject/{subject_id}/contents?page={page}&contentType=exercises-notes-videos"
        tasks.append(fetch_content(session, url, headers))

    responses = await asyncio.gather(*tasks)

    for content_response in responses:
        if not content_response.get("data"):
            continue

        for item in content_response.get("data", []):
            try:
                video_details = item.get("videoDetails", {})
                content_id = video_details.get("findKey") if video_details else None
                topic = clean_text(item.get("topic", ""))
                url = item.get("url", "")
                content_type = item.get("lectureType", "video").lower()

                if url:
                    if ".mpd" in url or ".m3u8" in url:
                        final_url, parent_id, child_id = extract_mpd_info(url, content_id, batch_id)
                        line = format_content_line(topic, final_url, content_type, parent_id, child_id)
                    else:
                        line = format_content_line(topic, url, content_type)
                    all_links.append(line)
                    total_links[0] += 1

                # Notes / Attachments
                for hw in item.get("homeworkIds", []):
                    hw_id = hw.get("_id")
                    for attachment in hw.get("attachmentIds", []):
                        try:
                            name = clean_text(attachment.get("name", ""))
                            base_url = attachment.get("baseUrl", "")
                            key = attachment.get("key", "")
                            if key:
                                full_url = f"{base_url}{key}"
                                line = format_content_line(name, full_url, "notes")
                                all_links.append(line)
                                total_links[0] += 1
                        except Exception:
                            continue
            except Exception:
                continue

def extract_mpd_info(url, content_id=None, batch_id=None):
    if "cloudfront.net" in url:
        return url, batch_id, content_id

    base_url = url.split("parentId=")[0].rstrip("&") if "parentId=" in url else url
    parent_match = re.search(r"parentId=([^&]+)", url)
    child_match = re.search(r"childId=([^&]+)", url)

    parent_id = parent_match.group(1) if parent_match else batch_id
    child_id = child_match.group(1) if child_match else content_id

    return base_url, parent_id, child_id

def clean_text(text):
    if not text:
        return ""
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.replace(":", "_").replace("/", "_").replace("|", "_").replace("\\", "_")

def format_content_line(name, url, content_type="", parent_id=None, child_id=None):
    name = clean_text(name)
    prefix = f"[{content_type}] " if content_type else ""
    if parent_id and child_id:
        return f"{prefix}{name}:{url}&parentId={parent_id}&childId={child_id}"
    return f"{prefix}{name}:{url}"

async def run_madeeasy(token, batch_id, output_file="madeeasy_links.txt"):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "MadeEasy/1.0"
    }

    # Fetch batch details
    batch_details = requests.get(f"{BASE_URL}/batches/{batch_id}/details", headers=headers).json()
    subjects = batch_details.get("data", {}).get("subjects", [])

    all_links = []
    total_links = [0]
    async with aiohttp.ClientSession() as session:
        tasks = []
        for subject in subjects:
            sid = subject.get("_id")
            sn = clean_text(subject.get("subject", ""))
            task = process_subject_content(session, batch_id, sid, headers, all_links, total_links)
            tasks.append(task)
        await asyncio.gather(*tasks)

    # Save to file
    with open(output_file, "w", encoding="utf-8") as f:
        for line in all_links:
            f.write(line + "\n")
        f.write("\n━━━━━━━━━━━━━━━\n")
        f.write("Extracted via MadeEasy Extractor\n")
        f.write("━━━━━━━━━━━━━━━\n")

    return output_file
import asyncio
import aiofiles
import tempfile
from urllib.parse import urlparse
import shutil

# ---------- subtitle helpers ----------
async def download_text_from_url(session, url, headers=None):
    """Download subtitle file (.vtt/.srt/.txt) and return plain text."""
    headers = headers or {}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None
            content = await resp.text()
            # If .vtt, strip WEBVTT header and timestamps
            if url.endswith(".vtt") or "<vtt" in content.lower():
                return vtt_to_text(content)
            # If .srt, strip timestamps
            if url.endswith(".srt") or re.search(r"\d+\:\d+\:\d+,\d+", content):
                return srt_to_text(content)
            # else plain text
            return content
    except Exception:
        return None

def vtt_to_text(vtt_content: str) -> str:
    lines = []
    for line in vtt_content.splitlines():
        if not line.strip():
            continue
        if line.strip().upper().startswith("WEBVTT"):
            continue
        # skip timestamps
        if re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}", line) or "-->" in line:
            continue
        # skip cue ids (numeric)
        if line.strip().isdigit():
            continue
        lines.append(line.strip())
    return "\n".join(lines).strip()

def srt_to_text(srt_content: str) -> str:
    lines = []
    for line in srt_content.splitlines():
        if not line.strip():
            continue
        # skip sequence numbers
        if line.strip().isdigit():
            continue
        # skip timestamps
        if re.search(r"\d{2}:\d{2}:\d{2},\d{3}", line):
            continue
        lines.append(line.strip())
    return "\n".join(lines).strip()

async def try_save_subtitles_from_item(session, item, headers, save_dir):
    """
    Look inside item for subtitles or attachments and save .txt file.
    Returns saved filepath or None.
    """
    # 1) look for known fields
    # Example paths: item['subtitles'], item['videoDetails']['subtitles'], item['attachments']
    candidates = []
    # common shapes
    if isinstance(item.get("subtitles"), list):
        for s in item["subtitles"]:
            url = s.get("url") or s.get("file") or s.get("src")
            if url:
                candidates.append((url, s.get("lang") or s.get("language") or "subtitle"))
    vdet = item.get("videoDetails") or {}
    if isinstance(vdet.get("subtitles"), list):
        for s in vdet["subtitles"]:
            url = s.get("url") or s.get("file")
            if url:
                candidates.append((url, s.get("lang") or "subtitle"))
    # attachments
    for hw in item.get("homeworkIds", []) or []:
        for att in hw.get("attachmentIds", []) or []:
            base = att.get("baseUrl", "")
            key = att.get("key", "")
            if key:
                candidates.append((f"{base}{key}", att.get("name", "attachment")))

    # attempt download sequentially until success
    for url, tag in candidates:
        text = await download_text_from_url(session, url, headers=headers)
        if text:
            safe_name = clean_text(item.get("topic") or item.get("name") or tag)
            os.makedirs(save_dir, exist_ok=True)
            out_path = os.path.join(save_dir, f"{safe_name}.txt")
            async with aiofiles.open(out_path, "w", encoding="utf-8") as af:
                await af.write(text)
            return out_path
    return None

# ---------- sync runner ----------
def run_madeeasy_sync(token, batch_id, output_file="madeeasy_links.txt"):
    """
    Simple sync wrapper so core/func.py can call this directly.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_madeeasy(token, batch_id, output_file=output_file))
    finally:
        loop.close()
