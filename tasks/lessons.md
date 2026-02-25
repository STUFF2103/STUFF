# DARK MIND — Lessons Learned

## Rules for this project

---

### L001 — Never mark phase complete without a real video to look at
**Context:** Phase 1 goal is a professional-looking video.
**Rule:** Code changes alone are never "done". Must run the pipeline, open the output file, and visually confirm quality before calling anything complete.

---

### L002 — Script and visuals must be generated in the same AI call
**Context:** Original pipeline generated script first, then images separately. They never matched.
**Rule:** Any prompt that generates script content MUST also generate the matching visual instructions in the same response. Separate calls = mismatched output.

---

### L003 — Generic visuals are a hard failure
**Context:** Image prompts like "dark silhouette cinematic" with no connection to what is being said = AI slop.
**Rule:** Every image_prompt must reference the specific thing being talked about in that beat's `text`. If the script says "he lost $420k" the prompt must describe that moment — not just "dark dramatic".

---

### L004 — Build order matters — don't skip ahead
**Context:** Full automation (scheduler, auto-poster, viral monitor) is Phase 3.
**Rule:** Do not build Phase 2 or Phase 3 features until the Phase 1 quality gate passes. A bad video posted automatically is worse than no video.

---

### L005 — FFmpeg filter_script file, not inline filter string on Windows
**Context:** Long drawtext filter chains break on Windows CMD due to character escaping and length limits.
**Rule:** Always write complex FFmpeg filters to a temp `.txt` file and use `-filter_script:v` to reference it. Never inline long filter strings on Windows.

---

### L006 — Always use beat number (not loop index) for filenames
**Context:** Beat numbers come from the script JSON (`beat_data["beat"]`), not the loop position `i`.
**Rule:** Filenames must be `beat_{beat_num:02d}_source.ext`. Using loop index would break ordering if beats start at non-1 or are reordered.

---

### L007 — Verify JSON keys before trusting script output
**Context:** Groq sometimes wraps JSON in markdown code blocks.
**Rule:** Always strip ``` and "json" prefix from Groq response before `json.loads()`. The script_writer.py already does this — don't remove it.
