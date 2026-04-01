TRANSCRIPTION_PROMPT = """IMPORTANT: The active application name and window title are provided above as ground truth. Use them directly in your transcription — do not guess the application from visual cues alone.

Transcribe ALL visible content in markdown exactly as shown. Include the application name from the context above, URLs, file paths, and timestamps.

While transcribing, note ONLY what you can clearly see:
- Application names and window titles (use the provided context as the authoritative source)
- Visible text content and UI elements
- URLs and file paths that are clearly displayed
- Any timestamps or dates visible on screen

DO NOT make assumptions about:
- Cursor position (unless clearly visible)
- Active window focus (unless obvious from UI)
- User interaction state (unless clearly indicated)
- Temporal context (unless explicitly shown)

Provide complete word-for-word transcription with ONLY observable interface context."""

SUMMARY_PROMPT = """Analyze the screenshots to understand what the user is doing based on clearly visible evidence.

Focus on what you can definitively observe:

**Visible Activity**: What specific actions can you see the user taking? (Only what's clearly visible)

**Content Type**: What type of information/interface is visible? (Based on clearly displayed content)

**Interface Elements**: What UI elements are clearly visible? (Windows, tabs, buttons, etc.)

**Behavioral Context**: What does the visible content suggest about user activity? (Be conservative in interpretation)

IMPORTANT: Only make observations based on clearly visible evidence. If something is unclear or not visible, do not make assumptions about it.

Generate 3-4 specific observations about what you can clearly see the user doing."""