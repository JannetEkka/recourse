"""Narration and captions from one script: an MP3 per scene and an SRT for the whole video.

    python narrate.py script.txt out_dir [voice]

Scenes are separated by blank lines. Caption timings come from the voice's own sentence
boundaries, so they line up with the speech. Prints each scene's length.
"""

import asyncio
import os
import ssl
import subprocess
import sys
from pathlib import Path

import edge_tts.communicate as communicate

CA_BUNDLE = "/root/.ccr/ca-bundle.crt"  # cloud sessions reach the internet through a proxy
if os.path.exists(CA_BUNDLE):
    communicate._SSL_CTX = ssl.create_default_context(cafile=CA_BUNDLE)

MAX_LINE = 46  # characters per caption line; two lines per caption at most


def stamp(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def cues(sentences: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Split each spoken sentence into captions of up to two lines, timed by length within it."""
    out = []
    for start, end, text in sentences:
        parts, cur = [], ""
        for word in text.split():
            nxt = f"{cur} {word}".strip()
            if cur and len(nxt) > 2 * MAX_LINE - 8:
                parts.append(cur)
                nxt = word
            elif cur.endswith(",") and len(cur) > MAX_LINE:
                parts.append(cur)
                nxt = word
            cur = nxt
        parts.append(cur)
        total = sum(len(x) for x in parts)
        t = start
        for x in parts:
            d = (end - start) * len(x) / total
            out.append((t, t + d, x))
            t += d
    return out


def wrap(line: str) -> str:
    if len(line) <= MAX_LINE:
        return line
    words, best = line.split(), None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = max(len(a), len(b))
        if best is None or score < best[0]:
            best = (score, a, b)
    return f"{best[1]}\n{best[2]}"


async def scene(text: str, voice: str, path: Path) -> list[tuple[float, float, str]]:
    sentences = []
    c = communicate.Communicate(text, voice, boundary="SentenceBoundary", proxy=os.environ.get("HTTPS_PROXY"))
    with open(path, "wb") as f:
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                start = chunk["offset"] / 1e7
                sentences.append((start, start + chunk["duration"] / 1e7, chunk["text"].strip()))
    return sentences


async def main(script: Path, out_dir: Path, voice: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = [s.strip().replace("\n", " ") for s in script.read_text().split("\n\n") if s.strip()]
    t, timed, lengths = 0.0, [], []
    for i, text in enumerate(scenes, 1):
        path = out_dir / f"scene{i:02d}.mp3"
        sentences = await scene(text, voice, path)
        length = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True).stdout)
        timed += [(t + a, t + b, line) for a, b, line in cues(sentences)]
        t += length
        lengths.append(length)
        print(f"{path.name}\t{length:.1f}s")
    srt = []
    for n, (a, b, line) in enumerate(timed, 1):
        nxt = timed[n][0] if n < len(timed) else t
        end = min(b + 0.4, nxt - 0.05)  # hold a moment, but never overlap the next caption
        srt.append(f"{n}\n{stamp(a)} --> {stamp(end)}\n{wrap(line)}\n")
    n = len(timed) + 1
    (out_dir / "captions.srt").write_text("\n".join(srt))
    (out_dir / "durations.txt").write_text(",".join(f"{x:.2f}" for x in lengths) + "\n")
    print(f"total {t:.1f}s, {n - 1} captions")


if __name__ == "__main__":
    voice = sys.argv[3] if len(sys.argv) > 3 else "en-IN-NeerjaNeural"
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), voice))
