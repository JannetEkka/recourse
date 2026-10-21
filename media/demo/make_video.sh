#!/usr/bin/env bash
# Join the narration, trim the recording to where it starts, and burn in the captions.
#   make_video.sh recording.webm offset_seconds audio_dir out.mp4
# Also writes out.srt next to the video, for players and uploads that take captions separately.
set -euo pipefail
video=$1; offset=$2; audio=$3; out=$4
list=$(mktemp)
for f in "$audio"/scene*.mp3; do echo "file '$(realpath "$f")'" >> "$list"; done
ffmpeg -y -loglevel error -f concat -safe 0 -i "$list" -c copy "$audio/narration.mp3"
style="FontName=Inter,FontSize=13,Bold=0,PrimaryColour=&H00FFFFFF,OutlineColour=&H40000000,BorderStyle=3,Outline=5,Shadow=0,MarginV=14,Alignment=2"
ffmpeg -y -loglevel error -ss "$offset" -i "$video" -i "$audio/narration.mp3" \
  -vf "subtitles=$audio/captions.srt:force_style='$style'" \
  -c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 22 -c:a aac -b:a 128k -shortest -movflags +faststart "$out"
cp "$audio/captions.srt" "${out%.mp4}.srt"
rm -f "$list"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$out"
