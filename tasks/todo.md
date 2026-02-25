# DARK MIND — Task Tracker

## Current Phase: Phase 1 — Perfect Video Quality

---

## Sprint: Beat-Locked Visual Pipeline (started 2026-02-25)

### Implementation
- [x] `script_writer.py` — Output `beats` with `text` + `image_prompt` + `video_keywords` in one Groq call
- [x] `image_generator.py` — Add Pexels/Pixabay video clip fetching, alternate odd=image / even=clip per beat
- [x] `run_pipeline.py` — Pass beat-locked visual list directly to assembler, skip `build_visual_list`

### Verification (PENDING)
- [ ] Run full pipeline end-to-end: `python run_pipeline.py --idea "..."`
- [ ] Confirm `beats` key present in script output (not `image_prompts`)
- [ ] Confirm even beats produce `.mp4` clips in `clips/` dir
- [ ] Confirm odd beats produce `.jpg` images in `images/` dir
- [ ] Confirm files named `beat_NN_source.ext` in correct order
- [ ] Watch output video — does each visual match what is being said?
- [ ] Check captions sync to spoken words (not drifting)
- [ ] Check final video duration = voiceover duration ± 0.5s
- [ ] Check dark color grade applied throughout
- [ ] Check music at ~10% under voice — audible but not overpowering

### Quality Gate (before Phase 2)
- [ ] Video looks like a real professional dark content channel
- [ ] No generic visuals — every image/clip matches its beat's spoken text
- [ ] Captions readable, smooth, Netflix-style
- [ ] Hook in first 3 seconds strong enough to stop scrolling

---

## Phase 2 — Content Variety (BLOCKED until Phase 1 passes quality gate)
- [ ] Build topic bank with 100+ topics
- [ ] `trend_research.py` — YouTube + Google Trends + Reddit RSS
- [ ] Never-repeat-topics tracker

## Phase 3 — Scale & Automate (BLOCKED until Phase 2)
- [ ] Spanish version pipeline
- [ ] `auto_poster.py` — TikTok + YouTube Shorts
- [ ] `scheduler.py` — 7 posts/day at peak times
- [ ] `viral_monitor.py` — 3x views → auto Part 2
- [ ] Analytics dashboard
- [ ] Cloud deploy

---

## Review Log

### 2026-02-25
- **Built:** Beat-locked visual system. Script now writes beats with text+prompt+keywords in single Groq call. Image generator alternates images/clips by beat parity. Pipeline passes ordered list directly to assembler.
- **Not yet verified:** Full pipeline run with real API calls. Need to run and watch output video.
