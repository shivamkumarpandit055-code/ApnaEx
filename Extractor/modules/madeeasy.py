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
